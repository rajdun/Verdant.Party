from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import DecimalField, F, ProtectedError, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.catalog.models import Product
from apps.inventory.forms import LocationForm, StockBatchForm, StockBatchRelocateForm
from apps.inventory.models import Location, StockBatch

SORTABLE_FIELDS = ("sku", "name", "total_quantity", "total_value")


class LocationListView(LoginRequiredMixin, ListView):
    model = Location
    context_object_name = "locations"
    template_name = "inventory/location_list.html"
    paginate_by = 24

    def get_queryset(self):
        qs = Location.objects.all()
        query = self.request.GET.get("q")
        if query:
            qs = qs.filter(Q(name__icontains=query) | Q(code__icontains=query))
        is_active = self.request.GET.get("is_active")
        if is_active in ("true", "false"):
            qs = qs.filter(is_active=(is_active == "true"))
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_params"] = self.request.GET
        return context


class LocationCreateView(LoginRequiredMixin, CreateView):
    model = Location
    form_class = LocationForm
    template_name = "inventory/location_form.html"

    def get_success_url(self):
        return reverse("inventory:location_list")


class LocationUpdateView(LoginRequiredMixin, UpdateView):
    model = Location
    form_class = LocationForm
    template_name = "inventory/location_form.html"

    def get_success_url(self):
        return reverse("inventory:location_list")


class LocationDeleteView(LoginRequiredMixin, DeleteView):
    model = Location
    template_name = "inventory/location_confirm_delete.html"

    def get_success_url(self):
        return reverse("inventory:location_list")

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except ProtectedError:
            messages.error(
                request,
                "Nie można usunąć lokalizacji — posiada powiązane przyjęcia magazynowe.",
            )
            return redirect("inventory:location_list")


@login_required
@require_POST
def location_activate(request, pk):
    location = get_object_or_404(Location, pk=pk)
    location.is_active = True
    location.save(update_fields=["is_active", "updated_at"])
    return redirect("inventory:location_list")


@login_required
@require_POST
def location_deactivate(request, pk):
    location = get_object_or_404(Location, pk=pk)
    location.is_active = False
    location.save(update_fields=["is_active", "updated_at"])
    return redirect("inventory:location_list")


class StockOverviewView(LoginRequiredMixin, ListView):
    """Stany magazynowe grupowane po towarze — rozwijane do rozbicia na lokalizacje."""

    model = Product
    context_object_name = "products"
    template_name = "inventory/stock_overview.html"
    paginate_by = 24

    def get_queryset(self):
        params = self.request.GET

        remaining = Sum("stock_batches__quantity_remaining")
        value = Sum(
            F("stock_batches__quantity_remaining") * F("stock_batches__unit_cost"),
            output_field=DecimalField(max_digits=12, decimal_places=2),
        )

        location = params.get("location")
        if location:
            batch_filter = Q(stock_batches__location_id=location)
            remaining = Sum("stock_batches__quantity_remaining", filter=batch_filter)
            value = Sum(
                F("stock_batches__quantity_remaining") * F("stock_batches__unit_cost"),
                filter=batch_filter,
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )

        qs = Product.objects.annotate(
            total_quantity=Coalesce(remaining, 0),
            total_value=Coalesce(value, Decimal("0"), output_field=DecimalField(max_digits=12, decimal_places=2)),
        ).filter(total_quantity__gt=0)

        query = params.get("q")
        if query:
            qs = qs.filter(Q(sku__icontains=query) | Q(name__icontains=query))

        sort = params.get("sort")
        order = params.get("order", "asc")
        if sort in SORTABLE_FIELDS:
            qs = qs.order_by(sort if order != "desc" else f"-{sort}")

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET

        products = list(context["products"])
        batches = StockBatch.objects.select_related("location").filter(
            product_id__in=[product.pk for product in products], quantity_remaining__gt=0
        )
        if location := params.get("location"):
            batches = batches.filter(location_id=location)

        # {product_id: {location_id: {"location": ..., "quantity": ..., "value": ..., "batches": [...]}}}
        breakdown = {}
        for batch in batches:
            locations = breakdown.setdefault(batch.product_id, {})
            row = locations.setdefault(
                batch.location_id,
                {"location": batch.location, "quantity": 0, "value": Decimal("0"), "batches": []},
            )
            row["quantity"] += batch.quantity_remaining
            row["value"] += batch.remaining_value
            row["batches"].append(batch)

        for product in products:
            product.location_rows = sorted(
                breakdown.get(product.pk, {}).values(), key=lambda row: row["location"].name
            )
            product.avg_unit_cost = (
                product.total_value / product.total_quantity if product.total_quantity else Decimal("0")
            )

        context["current_params"] = params
        context["locations"] = Location.objects.filter(is_active=True)
        context["sortable_fields"] = SORTABLE_FIELDS
        return context


class StockBatchListView(LoginRequiredMixin, ListView):
    model = StockBatch
    context_object_name = "batches"
    template_name = "inventory/stockbatch_list.html"
    paginate_by = 24

    def get_queryset(self):
        qs = StockBatch.objects.select_related("product", "location")
        params = self.request.GET

        query = params.get("q")
        if query:
            qs = qs.filter(Q(product__sku__icontains=query) | Q(product__name__icontains=query))

        if location := params.get("location"):
            qs = qs.filter(location_id=location)

        if document := params.get("document"):
            qs = qs.filter(document_reference__icontains=document)

        if date_from := params.get("date_from"):
            qs = qs.filter(received_at__gte=date_from)
        if date_to := params.get("date_to"):
            qs = qs.filter(received_at__lte=date_to)

        if params.get("only_available") == "true":
            qs = qs.filter(quantity_remaining__gt=0)

        return qs.order_by("-received_at", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["current_params"] = self.request.GET
        context["locations"] = Location.objects.filter(is_active=True)
        return context


class StockBatchCreateView(LoginRequiredMixin, CreateView):
    model = StockBatch
    form_class = StockBatchForm
    template_name = "inventory/stockbatch_form.html"

    def form_valid(self, form):
        form.instance.quantity_remaining = form.cleaned_data["quantity_received"]
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("inventory:stockbatch_list")


class LockedStockBatchGuardMixin:
    """Ruszonej partii nie edytujemy ani nie usuwamy — tylko przenosimy."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and self.get_object().is_locked:
            messages.error(
                request,
                "Z tej partii zszedł już towar — nie można jej edytować ani usunąć. "
                "Dostępna jest tylko zmiana lokalizacji.",
            )
            return redirect("inventory:stockbatch_list")
        return super().dispatch(request, *args, **kwargs)


class StockBatchUpdateView(LoginRequiredMixin, LockedStockBatchGuardMixin, UpdateView):
    model = StockBatch
    form_class = StockBatchForm
    template_name = "inventory/stockbatch_form.html"

    def get_success_url(self):
        return reverse("inventory:stockbatch_list")


class StockBatchDeleteView(LoginRequiredMixin, LockedStockBatchGuardMixin, DeleteView):
    model = StockBatch
    template_name = "inventory/stockbatch_confirm_delete.html"

    def get_success_url(self):
        return reverse("inventory:stockbatch_list")


@login_required
def stockbatch_relocate(request, pk):
    source = get_object_or_404(StockBatch.objects.select_related("product", "location"), pk=pk)

    if request.method == "POST":
        form = StockBatchRelocateForm(request.POST, source=source)
        if form.is_valid():
            quantity = form.cleaned_data["quantity"]
            destination_location = form.cleaned_data["location"]
            origin_name = source.location.name

            with transaction.atomic():
                if quantity == source.quantity_remaining:
                    source.location = destination_location
                    source.save(update_fields=["location", "updated_at"])
                else:
                    source.quantity_remaining -= quantity
                    source.save(update_fields=["quantity_remaining", "updated_at"])
                    StockBatch.objects.create(
                        product=source.product,
                        location=destination_location,
                        quantity_received=quantity,
                        quantity_remaining=quantity,
                        unit_cost=source.unit_cost,
                        received_at=source.received_at,
                        supplier_name=source.supplier_name,
                        document_reference=source.document_reference,
                        note=f"Przeniesiono z: {origin_name}",
                    )

            messages.success(request, "Lokalizacja zaktualizowana.")
            return redirect("inventory:stock_overview")
    else:
        form = StockBatchRelocateForm(source=source)

    return render(request, "inventory/stockbatch_relocate.html", {"source": source, "form": form})
