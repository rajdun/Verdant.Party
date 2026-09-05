"""Okno realizacji — zbieranie i pakowanie zamówień w falach.

Trzy zakładki to trzy osobne adresy, nie przełączanie w JS: dzięki temu stan
przeżywa odświeżenie, da się wysłać link współpracownikowi, a mutacje trzymają
przyjęty w projekcie wzorzec POST → `messages` → redirect.
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import ListView

from apps.inventory.models import StockBatch
from apps.logistics.forms import FulfillmentBatchForm, ShippingCostForm
from apps.logistics.models import (
    FulfillmentBatch,
    FulfillmentBatchStatus,
    FulfillmentOrder,
)
from apps.marketplaces.allegro.client import AllegroError
from apps.marketplaces.allegro.shipping import ShippingCostUnavailable, fetch_shipping_cost
from apps.marketplaces.models import Marketplace
from apps.orders.models import Order, OrderLine, OrderStatus, ShippingCostSource

# Zamówienia, które w ogóle nadają się do realizacji.
FULFILLABLE_STATUSES = (OrderStatus.NEW, OrderStatus.IN_FULFILLMENT)

# Klucz sesji dla kwoty pobranej z Allegro — musi przeżyć redirect po POST,
# a nie chcemy zapisywać jej na zamówieniu przed zatwierdzeniem pakowania.
SHIPPING_COST_SESSION_PREFIX = "logistics:shipping_cost:"


def _fifo_locations(demand):
    """Rozpisuje zapotrzebowanie na konkretne partie w kolejności FIFO.

    `demand` to {product_id: ilość}. Zwraca {product_id: {"rows", "picked",
    "missing"}}, gdzie `rows` to lista {"location", "quantity", "unit_cost"}.
    Kolejność partii jest ta sama, którą przy zatwierdzeniu weźmie
    `StockBatch.consume_fifo()`, więc podpowiedź zgadza się z tym, co faktycznie
    zejdzie ze stanu.
    """
    if not demand:
        return {}

    batches = StockBatch.objects.select_related("location").filter(
        product_id__in=demand.keys(), quantity_remaining__gt=0
    )  # Meta.ordering = ["received_at", "id"] — czyli FIFO

    allocation = {
        product_id: {"rows": [], "picked": 0, "missing": quantity}
        for product_id, quantity in demand.items()
    }

    for batch in batches:
        entry = allocation[batch.product_id]
        if entry["missing"] == 0:
            continue
        taken = min(batch.quantity_remaining, entry["missing"])
        entry["rows"].append(
            {
                "location": batch.location,
                "quantity": taken,
                "unit_cost": batch.unit_cost,
            }
        )
        entry["picked"] += taken
        entry["missing"] -= taken

    return allocation


def _order_pick_rows(order):
    """Pozycje jednego zamówienia z podpowiedzią lokalizacji."""
    lines = list(order.lines.select_related("product").all())
    demand = {}
    for line in lines:
        if line.product_id:
            demand[line.product_id] = demand.get(line.product_id, 0) + line.quantity

    allocation = _fifo_locations(demand)
    rows = []
    for line in lines:
        entry = allocation.get(line.product_id) if line.product_id else None
        rows.append(
            {
                "line": line,
                "locations": entry["rows"] if entry else [],
                "missing": entry["missing"] if entry else 0,
            }
        )
    return rows


def _batch_context(batch):
    """Wspólna główka wszystkich trzech zakładek."""
    return {
        "batch": batch,
        "total_orders": batch.total_orders,
        "packed_orders": batch.packed_orders,
    }


class FulfillmentBatchListView(LoginRequiredMixin, ListView):
    """Lista fal plus wybór zamówień do nowej fali."""

    model = FulfillmentBatch
    context_object_name = "batches"
    template_name = "logistics/fulfillment_batch_list.html"
    paginate_by = 20

    def get_queryset(self):
        return (
            FulfillmentBatch.objects.select_related("created_by")
            .annotate(
                order_count=Count("items"),
                packed_count=Count("items", filter=Q(items__is_packed=True)),
            )
            .order_by("-created_at", "-id")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET

        # Kandydaci: zamówienia do realizacji, których nie ma w otwartej fali.
        candidates = (
            Order.objects.filter(status__in=FULFILLABLE_STATUSES)
            .exclude(fulfillment_items__batch__status=FulfillmentBatchStatus.OPEN)
            .select_related("marketplace")
            .prefetch_related("lines__product")
        )

        if query := params.get("q"):
            candidates = candidates.filter(
                Q(external_order_id__icontains=query)
                | Q(buyer_full_name__icontains=query)
                | Q(delivery_recipient_name__icontains=query)
            ).distinct()

        if marketplace := params.get("marketplace"):
            candidates = candidates.filter(marketplace_id=marketplace)

        context["candidates"] = candidates
        context["current_params"] = params
        context["marketplaces"] = Marketplace.objects.all()
        context["form"] = FulfillmentBatchForm()
        return context


@login_required
@require_POST
def batch_create(request):
    order_ids = request.POST.getlist("orders")
    if not order_ids:
        messages.error(request, "Zaznacz przynajmniej jedno zamówienie.")
        return redirect("logistics:batch_list")

    form = FulfillmentBatchForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Nieprawidłowy opis fali.")
        return redirect("logistics:batch_list")

    with transaction.atomic():
        # Ponowna walidacja w transakcji — między wyświetleniem listy a POST-em
        # ktoś inny mógł wciągnąć te same zamówienia do swojej fali.
        orders = list(
            Order.objects.filter(pk__in=order_ids, status__in=FULFILLABLE_STATUSES)
            .exclude(fulfillment_items__batch__status=FulfillmentBatchStatus.OPEN)
            .order_by("placed_at", "id")
        )
        if not orders:
            messages.error(
                request,
                "Żadne z zaznaczonych zamówień nie nadaje się już do realizacji "
                "— odśwież listę.",
            )
            return redirect("logistics:batch_list")

        batch = form.save(commit=False)
        batch.created_by = request.user
        batch.save()

        FulfillmentOrder.objects.bulk_create(
            FulfillmentOrder(batch=batch, order=order, position=position)
            for position, order in enumerate(orders)
        )

    skipped = len(order_ids) - len(orders)
    message = f"Utworzono falę #{batch.pk} z {len(orders)} zamówieniami."
    if skipped:
        message += f" Pominięto {skipped} — trafiły już do innej fali."
    messages.success(request, message)
    return redirect("logistics:batch_summary", pk=batch.pk)


def _get_batch(pk):
    return get_object_or_404(
        FulfillmentBatch.objects.select_related("created_by"), pk=pk
    )


@login_required
def batch_summary(request, pk):
    """Zakładka 1 — co jest w fali i na jakim etapie."""
    batch = _get_batch(pk)
    items = (
        batch.items.select_related("order__marketplace")
        .prefetch_related("order__lines__product")
        .all()
    )

    line_totals = OrderLine.objects.filter(
        order__fulfillment_items__batch=batch
    ).aggregate(units=Sum("quantity"), positions=Count("id"))

    value = Order.objects.filter(fulfillment_items__batch=batch).aggregate(
        total=Sum("total_to_pay")
    )["total"]

    context = _batch_context(batch)
    context.update(
        {
            "items": items,
            "total_units": line_totals["units"] or 0,
            "total_positions": line_totals["positions"] or 0,
            "total_value": value or Decimal("0"),
            "active_tab": "summary",
        }
    )
    return render(request, "logistics/fulfillment_summary.html", context)


@login_required
def batch_picking(request, pk):
    """Zakładka 2 — zsumowana lista towarów do zebrania z lokalizacjami."""
    batch = _get_batch(pk)

    wanted = (
        OrderLine.objects.filter(
            order__fulfillment_items__batch=batch, product__isnull=False
        )
        .values("product_id", "product__sku", "product__name")
        .annotate(quantity=Sum("quantity"))
        .order_by("product__sku")
    )

    allocation = _fifo_locations({row["product_id"]: row["quantity"] for row in wanted})

    rows = []
    for row in wanted:
        entry = allocation[row["product_id"]]
        rows.append(
            {
                "product_id": row["product_id"],
                "sku": row["product__sku"],
                "name": row["product__name"],
                "quantity": row["quantity"],
                "locations": entry["rows"],
                "missing": entry["missing"],
            }
        )

    # Pozycje bez mapowania nie zdejmą stanu i nie wejdą do COGS — pokazujemy je
    # osobno, żeby magazynier wiedział, że musi je znaleźć bez podpowiedzi.
    unmapped = (
        OrderLine.objects.filter(
            order__fulfillment_items__batch=batch, product__isnull=True
        )
        .values("external_offer_id", "external_offer_name")
        .annotate(quantity=Sum("quantity"))
        .order_by("external_offer_name")
    )

    context = _batch_context(batch)
    context.update(
        {
            "rows": rows,
            "unmapped": unmapped,
            "shortages": sum(1 for row in rows if row["missing"]),
            "active_tab": "picking",
        }
    )
    return render(request, "logistics/fulfillment_picking.html", context)


@login_required
def batch_packing(request, pk):
    """Zakładka 3 — wchodzi wprost na pierwsze niespakowane zamówienie."""
    batch = _get_batch(pk)
    item = batch.items.filter(is_packed=False).first() or batch.items.first()
    if item is None:
        messages.info(request, "Fala nie ma zamówień do spakowania.")
        return redirect("logistics:batch_summary", pk=batch.pk)
    return redirect("logistics:batch_packing_order", pk=batch.pk, order_pk=item.order_id)


def _session_key(order):
    return f"{SHIPPING_COST_SESSION_PREFIX}{order.pk}"


@login_required
def batch_packing_order(request, pk, order_pk):
    """Ekran pakowania jednego zamówienia."""
    batch = _get_batch(pk)
    item = get_object_or_404(
        batch.items.select_related("order__marketplace"), order_id=order_pk
    )
    order = item.order

    items = list(batch.items.values_list("order_id", flat=True))
    index = items.index(order.pk)

    fetched = request.session.get(_session_key(order))
    initial = {}
    if fetched is not None:
        initial["shipping_cost"] = Decimal(fetched)
    elif order.shipping_cost:
        initial["shipping_cost"] = order.shipping_cost

    context = _batch_context(batch)
    context.update(
        {
            "item": item,
            "order": order,
            "rows": _order_pick_rows(order),
            "form": ShippingCostForm(initial=initial),
            "fetched_from_allegro": fetched is not None,
            "position": index + 1,
            "previous_order_id": items[index - 1] if index > 0 else None,
            "next_order_id": items[index + 1] if index + 1 < len(items) else None,
            "active_tab": "packing",
        }
    )
    return render(request, "logistics/fulfillment_packing.html", context)


@login_required
@require_POST
def order_fetch_shipping_cost(request, pk, order_pk):
    """Pobiera koszt wysyłki z Allegro bez zatwierdzania pakowania."""
    batch = _get_batch(pk)
    item = get_object_or_404(batch.items.select_related("order__marketplace"), order_id=order_pk)

    try:
        cost = fetch_shipping_cost(item.order)
    except ShippingCostUnavailable as exc:
        messages.error(request, f"{exc} Wpisz kwotę ręcznie lub spróbuj ponownie.")
    except AllegroError as exc:
        messages.error(
            request, f"Błąd połączenia z Allegro: {exc} Wpisz kwotę ręcznie lub ponów."
        )
    else:
        request.session[_session_key(item.order)] = str(cost)
        messages.success(request, f"Pobrano koszt wysyłki z Allegro: {cost} zł.")

    return redirect("logistics:batch_packing_order", pk=batch.pk, order_pk=order_pk)


@login_required
@require_POST
def order_pack_confirm(request, pk, order_pk):
    """Zdejmuje stan FIFO, zapisuje koszty i oznacza zamówienie jako wysłane."""
    batch = _get_batch(pk)
    form = ShippingCostForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Podaj poprawny koszt wysyłki (liczba, min. 0).")
        return redirect("logistics:batch_packing_order", pk=batch.pk, order_pk=order_pk)

    shipping_cost = form.cleaned_data["shipping_cost"]
    fetched = request.session.get(f"{SHIPPING_COST_SESSION_PREFIX}{order_pk}")
    source = (
        ShippingCostSource.ALLEGRO
        if fetched is not None and Decimal(fetched) == shipping_cost
        else ShippingCostSource.MANUAL
    )

    try:
        with transaction.atomic():
            # Blokada chroni przed podwójnym POST-em — bez niej drugie kliknięcie
            # zdjęłoby stan magazynowy po raz drugi.
            item = get_object_or_404(
                FulfillmentOrder.objects.select_for_update(),
                batch=batch,
                order_id=order_pk,
            )
            if item.is_packed:
                messages.info(request, "To zamówienie jest już spakowane.")
                return redirect("logistics:batch_summary", pk=batch.pk)

            order = Order.objects.select_for_update().get(pk=item.order_id)

            total_cogs = Decimal("0")
            for line in order.lines.select_related("product").all():
                if line.product_id is None:
                    continue  # oferta bez mapowania — nie ma czego zdjąć ze stanu
                _, cost = StockBatch.consume_fifo(line.product, line.quantity)
                total_cogs += cost

            order.total_cogs = total_cogs
            order.shipping_cost = shipping_cost
            order.shipping_cost_source = source
            order.save(
                update_fields=[
                    "total_cogs",
                    "shipping_cost",
                    "shipping_cost_source",
                    "updated_at",
                ]
            )

            if order.status == OrderStatus.NEW:
                order.start_fulfillment()
            order.mark_shipped()

            item.mark_packed()
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("logistics:batch_packing_order", pk=batch.pk, order_pk=order_pk)

    request.session.pop(f"{SHIPPING_COST_SESSION_PREFIX}{order_pk}", None)
    messages.success(
        request,
        f"Spakowano {order.external_order_id} — koszt towaru {total_cogs} zł, "
        f"wysyłka {shipping_cost} zł.",
    )

    following = batch.items.filter(is_packed=False).first()
    if following is None:
        messages.success(request, "Wszystkie zamówienia w fali spakowane.")
        return redirect("logistics:batch_summary", pk=batch.pk)
    return redirect(
        "logistics:batch_packing_order", pk=batch.pk, order_pk=following.order_id
    )


def _change_batch_status(request, pk, action, success_message):
    batch = _get_batch(pk)
    try:
        getattr(batch, action)()
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, success_message)
    return redirect("logistics:batch_summary", pk=batch.pk)


@login_required
@require_POST
def batch_finish(request, pk):
    return _change_batch_status(request, pk, "finish", "Fala zakończona.")


@login_required
@require_POST
def batch_cancel(request, pk):
    return _change_batch_status(request, pk, "cancel", "Fala anulowana.")
