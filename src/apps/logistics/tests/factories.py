"""Wspólne dane testowe dla realizacji zamówień."""

from decimal import Decimal

from django.utils import timezone

from apps.inventory.models import Location, StockBatch
from apps.orders.models import Order, OrderLine


def make_order(marketplace, external_order_id="ORDER-1", **overrides):
    defaults = dict(
        buyer_full_name="Anna Kowalska",
        delivery_recipient_name="Anna Kowalska",
        delivery_city="Kraków",
        delivery_method_name="Kurier",
        total_to_pay=Decimal("214.80"),
        placed_at=timezone.now(),
    )
    defaults.update(overrides)
    return Order.objects.create(
        marketplace=marketplace, external_order_id=external_order_id, **defaults
    )


def make_line(order, product=None, quantity=1, **overrides):
    defaults = dict(
        external_offer_id="12345",
        external_offer_name="Ficus lyrata 12cm",
        unit_price=Decimal("99.90"),
    )
    defaults.update(overrides)
    return OrderLine.objects.create(
        order=order, product=product, quantity=quantity, **defaults
    )


def make_location(name="Regał A"):
    return Location.objects.create(name=name)


def make_batch(product, location, quantity=10, unit_cost="10.00", received_at=None):
    return StockBatch.objects.create(
        product=product,
        location=location,
        quantity_received=quantity,
        quantity_remaining=quantity,
        unit_cost=Decimal(unit_cost),
        received_at=received_at or timezone.localdate(),
    )
