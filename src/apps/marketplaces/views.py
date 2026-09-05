from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.catalog.models import Product
from apps.marketplaces.allegro.client import AllegroClient, AllegroError, parse_amount
from apps.marketplaces.allegro.importer import fetch_events
from apps.marketplaces.allegro.oauth import (
    build_authorize_url,
    ensure_access_token,
    exchange_code,
    refresh_token,
)
from apps.marketplaces.forms import (
    MarketplaceCredentialsForm,
    MarketplaceForm,
    MarketplaceListingForm,
)
from apps.marketplaces.models import (
    ListingStatus,
    Marketplace,
    MarketplaceListing,
    SyncRun,
    SyncStatus,
)

OAUTH_SESSION_KEY = "oauth_marketplace_id"


class MarketplaceListView(LoginRequiredMixin, ListView):
    model = Marketplace
    context_object_name = "marketplaces"
    template_name = "marketplaces/marketplace_list.html"
    paginate_by = 24

    def get_queryset(self):
        qs = Marketplace.objects.all()
        params = self.request.GET

        if query := params.get("q"):
            qs = qs.filter(Q(name__icontains=query))

        is_active = params.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=(is_active == "true"))

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_params"] = self.request.GET
        return context


class MarketplaceDetailView(LoginRequiredMixin, DetailView):
    model = Marketplace
    context_object_name = "marketplace"
    template_name = "marketplaces/marketplace_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        marketplace = self.object
        context["listings"] = marketplace.listings.select_related("product")[:10]
        context["listing_count"] = marketplace.listings.count()
        context["order_count"] = marketplace.orders.count()
        context["recent_runs"] = marketplace.sync_runs.all()[:5]
        context["redirect_uri"] = self.request.build_absolute_uri(
            reverse("marketplaces:oauth_callback")
        )
        return context


class MarketplaceCreateView(LoginRequiredMixin, CreateView):
    model = Marketplace
    form_class = MarketplaceForm
    template_name = "marketplaces/marketplace_form.html"

    def get_success_url(self):
        messages.success(self.request, "Integracja utworzona — uzupełnij dane dostępowe.")
        return reverse("marketplaces:marketplace_credentials", args=[self.object.pk])


class MarketplaceUpdateView(LoginRequiredMixin, UpdateView):
    model = Marketplace
    form_class = MarketplaceForm
    template_name = "marketplaces/marketplace_form.html"

    def get_success_url(self):
        return reverse("marketplaces:marketplace_detail", args=[self.object.pk])


class MarketplaceDeleteView(LoginRequiredMixin, DeleteView):
    model = Marketplace
    template_name = "marketplaces/marketplace_confirm_delete.html"

    def get_success_url(self):
        return reverse("marketplaces:marketplace_list")

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except ProtectedError:
            messages.error(
                request,
                "Nie można usunąć integracji — ma powiązane zamówienia lub mapowania ofert.",
            )
            return redirect("marketplaces:marketplace_detail", pk=self.get_object().pk)


@login_required
def marketplace_credentials(request, pk):
    marketplace = get_object_or_404(Marketplace, pk=pk)

    if request.method == "POST":
        form = MarketplaceCredentialsForm(request.POST)
        if form.is_valid():
            marketplace.set_credentials(
                form.cleaned_data["client_id"], form.cleaned_data["client_secret"]
            )
            messages.success(request, "Dane dostępowe zapisane (zaszyfrowane).")
            return redirect("marketplaces:marketplace_detail", pk=marketplace.pk)
    else:
        # Client ID nie jest sekretem — podpowiadamy go; sekret zawsze pusty.
        form = MarketplaceCredentialsForm(initial={"client_id": marketplace.client_id})

    return render(
        request,
        "marketplaces/marketplace_credentials_form.html",
        {
            "form": form,
            "marketplace": marketplace,
            # Potrzebne przy zakładaniu aplikacji w panelu Allegro — musi być
            # zarejestrowany identycznie, inaczej OAuth padnie na etapie wymiany kodu.
            "redirect_uri": request.build_absolute_uri(reverse("marketplaces:oauth_callback")),
        },
    )


@login_required
@require_POST
def marketplace_activate(request, pk):
    marketplace = get_object_or_404(Marketplace, pk=pk)
    marketplace.is_active = True
    marketplace.save(update_fields=["is_active", "updated_at"])
    return redirect("marketplaces:marketplace_list")


@login_required
@require_POST
def marketplace_deactivate(request, pk):
    marketplace = get_object_or_404(Marketplace, pk=pk)
    marketplace.is_active = False
    marketplace.save(update_fields=["is_active", "updated_at"])
    return redirect("marketplaces:marketplace_list")


# --- OAuth -----------------------------------------------------------------


@login_required
@require_POST
def marketplace_connect(request, pk):
    """Start autoryzacji — przekierowanie sprzedawcy na Allegro."""
    marketplace = get_object_or_404(Marketplace, pk=pk)
    try:
        url = build_authorize_url(marketplace)
    except (AllegroError, ValidationError) as exc:
        messages.error(request, str(exc))
        return redirect("marketplaces:marketplace_detail", pk=marketplace.pk)

    # Adres powrotny jest wspólny dla wszystkich integracji, więc zapamiętujemy,
    # której dotyczy trwający przepływ.
    request.session[OAUTH_SESSION_KEY] = marketplace.pk
    return redirect(url)


@login_required
def oauth_callback(request):
    marketplace_id = request.session.pop(OAUTH_SESSION_KEY, None)
    if not marketplace_id:
        messages.error(request, "Brak kontekstu autoryzacji — rozpocznij łączenie od nowa.")
        return redirect("marketplaces:marketplace_list")

    marketplace = get_object_or_404(Marketplace, pk=marketplace_id)

    if error := request.GET.get("error"):
        messages.error(request, f"Allegro odrzuciło autoryzację: {error}")
        return redirect("marketplaces:marketplace_detail", pk=marketplace.pk)

    code = request.GET.get("code")
    state = request.GET.get("state")
    if not code:
        messages.error(request, "Allegro nie zwróciło kodu autoryzacyjnego.")
        return redirect("marketplaces:marketplace_detail", pk=marketplace.pk)

    try:
        exchange_code(marketplace, code, state)
    except (AllegroError, ValidationError) as exc:
        messages.error(request, f"Nie udało się połączyć z Allegro: {exc}")
        return redirect("marketplaces:marketplace_detail", pk=marketplace.pk)

    messages.success(request, f"Integracja „{marketplace.name}” połączona z Allegro.")
    return redirect("marketplaces:marketplace_detail", pk=marketplace.pk)


@login_required
@require_POST
def marketplace_refresh_token(request, pk):
    marketplace = get_object_or_404(Marketplace, pk=pk)
    try:
        refresh_token(marketplace)
    except (AllegroError, ValidationError) as exc:
        messages.error(request, f"Odświeżenie tokenu nieudane: {exc}")
    else:
        messages.success(request, "Token odświeżony.")
    return redirect("marketplaces:marketplace_detail", pk=marketplace.pk)


@login_required
@require_POST
def marketplace_sync(request, pk):
    """Ręczne uruchomienie importu — ten sam kod co cron, tylko synchronicznie."""
    marketplace = get_object_or_404(Marketplace, pk=pk)
    run = fetch_events(marketplace)

    summary = (
        f"Zdarzeń: {run.events_seen}, zaimportowano: {run.orders_imported}, "
        f"pominięto: {run.orders_skipped}."
    )
    if run.status == SyncStatus.OK:
        messages.success(request, f"Synchronizacja zakończona. {summary}")
    elif run.status == SyncStatus.PARTIAL:
        messages.warning(request, f"Synchronizacja częściowa. {summary}")
    else:
        messages.error(request, f"Synchronizacja nieudana: {run.message}")

    return redirect("marketplaces:marketplace_detail", pk=marketplace.pk)


# --- oferty i mapowania ----------------------------------------------------


@login_required
def external_listing_list(request, pk):
    """Oferty pobrane na żywo z Allegro, z możliwością zmapowania na produkty."""
    marketplace = get_object_or_404(Marketplace, pk=pk)
    offers, error = [], None

    try:
        ensure_access_token(marketplace)
        raw_offers = AllegroClient(marketplace).get_offers()
    except (AllegroError, ValidationError) as exc:
        error = str(exc)
        raw_offers = []

    mapped = dict(marketplace.listings.values_list("external_id", "product__sku"))

    for offer in raw_offers:
        external_id = str(offer.get("id") or "")
        offers.append(
            {
                "external_id": external_id,
                "title": offer.get("name") or "",
                "picture_url": (offer.get("primaryImage") or {}).get("url") or "",
                "price": parse_amount(
                    ((offer.get("sellingMode") or {}).get("price") or {}).get("amount")
                ),
                "currency": ((offer.get("sellingMode") or {}).get("price") or {}).get(
                    "currency"
                )
                or "PLN",
                "mapped_sku": mapped.get(external_id),
            }
        )

    if query := request.GET.get("q"):
        needle = query.lower()
        offers = [
            offer
            for offer in offers
            if needle in offer["title"].lower() or needle in offer["external_id"]
        ]

    if request.GET.get("only_unmapped") == "true":
        offers = [offer for offer in offers if not offer["mapped_sku"]]

    return render(
        request,
        "marketplaces/external_listing_list.html",
        {
            "marketplace": marketplace,
            "offers": offers,
            "error": error,
            "products": Product.objects.filter(is_active=True),
            "current_params": request.GET,
        },
    )


@login_required
@require_POST
def listing_map(request, pk):
    """Zapisuje mapowania zaznaczonych ofert — pola przychodzą z tabeli ofert."""
    marketplace = get_object_or_404(Marketplace, pk=pk)
    created, updated, skipped = 0, 0, 0

    for external_id in request.POST.getlist("external_id"):
        product_id = request.POST.get(f"product_{external_id}")
        if not product_id:
            continue

        product = Product.objects.filter(pk=product_id).first()
        if product is None:
            skipped += 1
            continue

        try:
            price = parse_amount(request.POST.get(f"price_{external_id}"))
        except (AllegroError, InvalidOperation):
            price = Decimal("0")

        try:
            _, was_created = MarketplaceListing.objects.update_or_create(
                marketplace=marketplace,
                external_id=external_id,
                defaults={
                    "product": product,
                    "title": request.POST.get(f"title_{external_id}", "")[:200],
                    "picture_url": request.POST.get(f"picture_{external_id}", "")[:500],
                    "current_price": price,
                    "currency": request.POST.get(f"currency_{external_id}", "PLN")[:3],
                    "status": ListingStatus.ACTIVE,
                },
            )
        except IntegrityError:
            skipped += 1
            continue

        created += int(was_created)
        updated += int(not was_created)

    if created or updated:
        messages.success(
            request, f"Zmapowano ofert: {created} nowych, {updated} zaktualizowanych."
        )
    if skipped:
        messages.warning(request, f"Pominięto ofert: {skipped}.")
    if not (created or updated or skipped):
        messages.info(request, "Nie wybrano żadnej oferty do zmapowania.")

    return redirect("marketplaces:external_listing_list", pk=marketplace.pk)


class ListingListView(LoginRequiredMixin, ListView):
    model = MarketplaceListing
    context_object_name = "listings"
    template_name = "marketplaces/listing_list.html"
    paginate_by = 24

    def get_queryset(self):
        qs = MarketplaceListing.objects.select_related("marketplace", "product")
        params = self.request.GET

        if query := params.get("q"):
            qs = qs.filter(
                Q(title__icontains=query)
                | Q(external_id__icontains=query)
                | Q(product__sku__icontains=query)
                | Q(product__name__icontains=query)
            )

        if marketplace := params.get("marketplace"):
            qs = qs.filter(marketplace_id=marketplace)

        if status := params.get("status"):
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_params"] = self.request.GET
        context["marketplaces"] = Marketplace.objects.all()
        context["status_choices"] = ListingStatus.choices
        return context


class ListingUpdateView(LoginRequiredMixin, UpdateView):
    model = MarketplaceListing
    form_class = MarketplaceListingForm
    template_name = "marketplaces/listing_form.html"

    def get_success_url(self):
        return reverse("marketplaces:listing_list")


class ListingDeleteView(LoginRequiredMixin, DeleteView):
    model = MarketplaceListing
    template_name = "marketplaces/listing_confirm_delete.html"

    def get_success_url(self):
        return reverse("marketplaces:listing_list")


@login_required
@require_POST
def listing_end(request, pk):
    listing = get_object_or_404(MarketplaceListing, pk=pk)
    listing.mark_ended()
    return redirect("marketplaces:listing_list")


@login_required
@require_POST
def listing_reactivate(request, pk):
    listing = get_object_or_404(MarketplaceListing, pk=pk)
    listing.reactivate()
    return redirect("marketplaces:listing_list")


class SyncRunListView(LoginRequiredMixin, ListView):
    model = SyncRun
    context_object_name = "runs"
    template_name = "marketplaces/syncrun_list.html"
    paginate_by = 24

    def get_queryset(self):
        qs = SyncRun.objects.select_related("marketplace")
        params = self.request.GET

        if marketplace := params.get("marketplace"):
            qs = qs.filter(marketplace_id=marketplace)
        if status := params.get("status"):
            qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_params"] = self.request.GET
        context["marketplaces"] = Marketplace.objects.all()
        context["status_choices"] = SyncStatus.choices
        return context
