from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, DecimalField, Q, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from apps.marketplaces.models import Marketplace
from apps.orders.models import Order, OrderStatus

SORTABLE_FIELDS = ("placed_at", "external_order_id", "total_to_pay", "status")


class OrderListView(LoginRequiredMixin, ListView):
    """Okno zamówień — przegląd zamówień ze wszystkich marketplace'ów."""

    model = Order
    context_object_name = "orders"
    template_name = "orders/order_list.html"
    paginate_by = 24

    def get_queryset(self):
        qs = Order.objects.select_related("marketplace").prefetch_related("lines__product")
        params = self.request.GET

        query = params.get("q")
        if query:
            qs = qs.filter(
                Q(external_order_id__icontains=query)
                | Q(buyer_full_name__icontains=query)
                | Q(buyer_login__icontains=query)
                | Q(delivery_recipient_name__icontains=query)
                | Q(lines__external_offer_name__icontains=query)
            ).distinct()

        if marketplace := params.get("marketplace"):
            qs = qs.filter(marketplace_id=marketplace)

        if status := params.get("status"):
            qs = qs.filter(status=status)

        if date_from := params.get("date_from"):
            qs = qs.filter(placed_at__date__gte=date_from)
        if date_to := params.get("date_to"):
            qs = qs.filter(placed_at__date__lte=date_to)

        # Zamówienia z pozycją bez mapowania — sygnał, że brakuje powiązania oferty.
        if params.get("unmapped") == "true":
            qs = qs.filter(lines__product__isnull=True).distinct()

        sort = params.get("sort")
        order = params.get("order", "asc")
        if sort in SORTABLE_FIELDS:
            qs = qs.order_by(sort if order != "desc" else f"-{sort}")

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET

        # Podsumowanie liczone na całym przefiltrowanym zbiorze, nie na stronie.
        # Przez podzapytanie po pk, bo filtry po pozycjach zwielokrotniają wiersze
        # złączeniem i sumy liczyłyby te same zamówienia wielokrotnie.
        money = DecimalField(max_digits=12, decimal_places=2)
        totals = Order.objects.filter(pk__in=self.get_queryset().values("pk")).aggregate(
            count=Count("id"),
            revenue=Coalesce(Sum("total_to_pay"), Decimal("0"), output_field=money),
            commission=Coalesce(Sum("platform_commission"), Decimal("0"), output_field=money),
        )

        context["current_params"] = params
        context["marketplaces"] = Marketplace.objects.all()
        context["status_choices"] = OrderStatus.choices
        context["sortable_fields"] = SORTABLE_FIELDS
        context["totals"] = totals
        return context


class OrderDetailView(LoginRequiredMixin, DetailView):
    model = Order
    context_object_name = "order"
    template_name = "orders/order_detail.html"

    def get_queryset(self):
        return Order.objects.select_related("marketplace").prefetch_related("lines__product")


def _change_status(request, pk, action, success_message):
    order = get_object_or_404(Order, pk=pk)
    try:
        getattr(order, action)()
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
    else:
        messages.success(request, success_message)
    return redirect("orders:order_detail", pk=order.pk)


@login_required
@require_POST
def order_start_fulfillment(request, pk):
    return _change_status(request, pk, "start_fulfillment", "Zamówienie przekazane do realizacji.")


@login_required
@require_POST
def order_mark_shipped(request, pk):
    return _change_status(request, pk, "mark_shipped", "Zamówienie oznaczone jako wysłane.")


@login_required
@require_POST
def order_cancel(request, pk):
    return _change_status(request, pk, "cancel", "Zamówienie anulowane.")
