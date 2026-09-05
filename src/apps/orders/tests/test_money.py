from decimal import Decimal

from django.test import TestCase

from apps.marketplaces.tests.factories import make_marketplace, make_product
from apps.orders.models import Order, OrderLine


class OrderMoneyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marketplace = make_marketplace()
        cls.product = make_product()
        cls.order = Order.objects.create(
            marketplace=cls.marketplace,
            external_order_id="ORDER-MONEY-1",
            total_to_pay=Decimal("115.00"),
            delivery_cost=Decimal("15.00"),
            total_cogs=Decimal("32.00"),
            platform_commission=Decimal("13.80"),
            shipping_cost=Decimal("13.99"),
        )
        OrderLine.objects.create(
            order=cls.order,
            product=cls.product,
            external_offer_id="12345",
            quantity=2,
            unit_price=Decimal("50.00"),
        )

    def test_items_total_pomija_dostawe(self):
        self.assertEqual(self.order.items_total, Decimal("100.00"))

    def test_total_costs_sumuje_trzy_koszty(self):
        self.assertEqual(self.order.total_costs, Decimal("59.79"))

    def test_gross_profit_liczy_od_total_to_pay(self):
        # Dostawa opłacona przez kupującego (15 zł) musi zostać po stronie
        # wpływów — inaczej marża jest zaniżona o tę kwotę, mimo że nadanie
        # paczki siedzi w kosztach.
        self.assertEqual(self.order.gross_profit, Decimal("55.21"))
