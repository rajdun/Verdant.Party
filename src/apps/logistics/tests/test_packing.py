from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.logistics.models import FulfillmentBatch, FulfillmentOrder
from apps.logistics.tests.factories import (
    make_batch,
    make_line,
    make_location,
    make_order,
)
from apps.marketplaces.allegro.shipping import ShippingCostUnavailable
from apps.marketplaces.tests.factories import make_marketplace, make_product
from apps.orders.models import OrderStatus, ShippingCostSource


class PackConfirmTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="magazyn", password="tajne123"
        )
        self.client.force_login(self.user)

        self.marketplace = make_marketplace()
        self.product = make_product()
        self.location = make_location()

        today = timezone.localdate()
        self.older = make_batch(
            self.product,
            self.location,
            quantity=2,
            unit_cost="10.00",
            received_at=today - timedelta(days=5),
        )
        self.newer = make_batch(
            self.product,
            self.location,
            quantity=5,
            unit_cost="12.00",
            received_at=today,
        )

        self.batch = FulfillmentBatch.objects.create()
        self.order = make_order(self.marketplace, "ORDER-1")
        make_line(self.order, self.product, quantity=3)
        self.item = FulfillmentOrder.objects.create(batch=self.batch, order=self.order)

        self.url = reverse(
            "logistics:order_pack_confirm", args=[self.batch.pk, self.order.pk]
        )

    def test_confirm_consumes_stock_fifo_and_records_costs(self):
        response = self.client.post(self.url, {"shipping_cost": "13.99"})

        self.older.refresh_from_db()
        self.newer.refresh_from_db()
        self.order.refresh_from_db()
        self.item.refresh_from_db()

        # 2 szt. ze starszej partii po 10 zł + 1 szt. z nowszej po 12 zł
        self.assertEqual(self.older.quantity_remaining, 0)
        self.assertEqual(self.newer.quantity_remaining, 4)
        self.assertEqual(self.order.total_cogs, Decimal("32.00"))
        self.assertEqual(self.order.shipping_cost, Decimal("13.99"))
        self.assertEqual(self.order.shipping_cost_source, ShippingCostSource.MANUAL)
        self.assertEqual(self.order.status, OrderStatus.SHIPPED)
        self.assertTrue(self.item.is_packed)
        self.assertIsNotNone(self.item.packed_at)
        self.assertRedirects(
            response, reverse("logistics:batch_summary", args=[self.batch.pk])
        )

    def test_second_confirm_does_not_consume_stock_again(self):
        self.client.post(self.url, {"shipping_cost": "13.99"})
        self.newer.refresh_from_db()
        remaining_after_first = self.newer.quantity_remaining

        self.client.post(self.url, {"shipping_cost": "99.00"})

        self.newer.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.newer.quantity_remaining, remaining_after_first)
        self.assertEqual(self.order.shipping_cost, Decimal("13.99"))

    def test_insufficient_stock_rolls_everything_back(self):
        make_line(self.order, self.product, quantity=100)

        response = self.client.post(self.url, {"shipping_cost": "13.99"})

        self.older.refresh_from_db()
        self.newer.refresh_from_db()
        self.order.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.older.quantity_remaining, 2)
        self.assertEqual(self.newer.quantity_remaining, 5)
        self.assertEqual(self.order.total_cogs, Decimal("0"))
        self.assertEqual(self.order.status, OrderStatus.NEW)
        self.assertFalse(self.item.is_packed)
        self.assertRedirects(
            response,
            reverse(
                "logistics:batch_packing_order", args=[self.batch.pk, self.order.pk]
            ),
        )

    def test_unmapped_line_does_not_block_packing(self):
        make_line(self.order, None, quantity=1, external_offer_id="99999")

        self.client.post(self.url, {"shipping_cost": "0"})

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.SHIPPED)
        self.assertEqual(self.order.total_cogs, Decimal("32.00"))

    def test_invalid_cost_is_rejected(self):
        response = self.client.post(self.url, {"shipping_cost": "-5"})

        self.item.refresh_from_db()
        self.assertFalse(self.item.is_packed)
        self.assertRedirects(
            response,
            reverse(
                "logistics:batch_packing_order", args=[self.batch.pk, self.order.pk]
            ),
        )

    def test_confirm_redirects_to_next_unpacked_order(self):
        second = make_order(self.marketplace, "ORDER-2")
        make_line(second, self.product, quantity=1)
        FulfillmentOrder.objects.create(batch=self.batch, order=second, position=1)

        response = self.client.post(self.url, {"shipping_cost": "10.00"})

        self.assertRedirects(
            response,
            reverse("logistics:batch_packing_order", args=[self.batch.pk, second.pk]),
        )


class FetchShippingCostViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="magazyn", password="tajne123"
        )
        self.client.force_login(self.user)

        self.marketplace = make_marketplace()
        self.product = make_product()
        self.location = make_location()
        make_batch(self.product, self.location, quantity=5)

        self.batch = FulfillmentBatch.objects.create()
        self.order = make_order(self.marketplace, "ORDER-1")
        make_line(self.order, self.product, quantity=1)
        FulfillmentOrder.objects.create(batch=self.batch, order=self.order)

        self.fetch_url = reverse(
            "logistics:order_fetch_shipping_cost", args=[self.batch.pk, self.order.pk]
        )
        self.packing_url = reverse(
            "logistics:batch_packing_order", args=[self.batch.pk, self.order.pk]
        )

    @patch("apps.logistics.views.fetch_shipping_cost", return_value=Decimal("14.50"))
    def test_fetched_cost_prefills_the_form(self, fetch):
        response = self.client.post(self.fetch_url)
        self.assertRedirects(response, self.packing_url)

        page = self.client.get(self.packing_url)
        self.assertTrue(page.context["fetched_from_allegro"])
        self.assertEqual(
            page.context["form"].initial["shipping_cost"], Decimal("14.50")
        )
        fetch.assert_called_once()

    @patch("apps.logistics.views.fetch_shipping_cost", return_value=Decimal("14.50"))
    def test_confirming_fetched_cost_marks_source_as_allegro(self, _fetch):
        self.client.post(self.fetch_url)

        self.client.post(
            reverse(
                "logistics:order_pack_confirm", args=[self.batch.pk, self.order.pk]
            ),
            {"shipping_cost": "14.50"},
        )

        self.order.refresh_from_db()
        self.assertEqual(self.order.shipping_cost, Decimal("14.50"))
        self.assertEqual(self.order.shipping_cost_source, ShippingCostSource.ALLEGRO)

    @patch("apps.logistics.views.fetch_shipping_cost", return_value=Decimal("14.50"))
    def test_overwriting_fetched_cost_marks_source_as_manual(self, _fetch):
        self.client.post(self.fetch_url)

        self.client.post(
            reverse(
                "logistics:order_pack_confirm", args=[self.batch.pk, self.order.pk]
            ),
            {"shipping_cost": "20.00"},
        )

        self.order.refresh_from_db()
        self.assertEqual(self.order.shipping_cost_source, ShippingCostSource.MANUAL)

    @patch(
        "apps.logistics.views.fetch_shipping_cost",
        side_effect=ShippingCostUnavailable("Brak wpisu."),
    )
    def test_failed_fetch_falls_back_to_manual_entry(self, _fetch):
        response = self.client.post(self.fetch_url, follow=True)

        self.assertFalse(response.context["fetched_from_allegro"])
        self.assertContains(response, "Wpisz kwotę ręcznie")
