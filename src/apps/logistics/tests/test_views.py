from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.logistics.models import (
    FulfillmentBatch,
    FulfillmentBatchStatus,
    FulfillmentOrder,
)
from apps.logistics.tests.factories import (
    make_batch,
    make_line,
    make_location,
    make_order,
)
from apps.marketplaces.tests.factories import make_marketplace, make_product
from apps.orders.models import OrderStatus


class BatchListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="magazyn", password="tajne123"
        )
        cls.marketplace = make_marketplace()
        cls.free = make_order(cls.marketplace, "ORDER-FREE")
        cls.shipped = make_order(
            cls.marketplace, "ORDER-SHIPPED", status=OrderStatus.SHIPPED
        )
        cls.taken = make_order(cls.marketplace, "ORDER-TAKEN")
        open_batch = FulfillmentBatch.objects.create()
        FulfillmentOrder.objects.create(batch=open_batch, order=cls.taken)

    def setUp(self):
        self.client.force_login(self.user)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("logistics:batch_list"))
        self.assertEqual(response.status_code, 302)

    def test_candidates_exclude_shipped_and_orders_in_open_batch(self):
        response = self.client.get(reverse("logistics:batch_list"))

        candidates = list(response.context["candidates"])
        self.assertIn(self.free, candidates)
        self.assertNotIn(self.shipped, candidates)
        self.assertNotIn(self.taken, candidates)

    def test_order_returns_to_pool_after_batch_cancelled(self):
        batch = FulfillmentOrder.objects.get(order=self.taken).batch
        batch.cancel()

        response = self.client.get(reverse("logistics:batch_list"))

        self.assertIn(self.taken, list(response.context["candidates"]))

    def test_create_batch_from_selected_orders(self):
        response = self.client.post(
            reverse("logistics:batch_create"),
            {"orders": [self.free.pk], "note": "wysyłka poranna"},
        )

        batch = FulfillmentBatch.objects.latest("id")
        self.assertRedirects(
            response, reverse("logistics:batch_summary", args=[batch.pk])
        )
        self.assertEqual(batch.note, "wysyłka poranna")
        self.assertEqual(batch.created_by, self.user)
        self.assertEqual([item.order for item in batch.items.all()], [self.free])

    def test_create_batch_skips_orders_already_in_open_batch(self):
        batches_before = FulfillmentBatch.objects.count()

        self.client.post(
            reverse("logistics:batch_create"), {"orders": [self.taken.pk]}
        )

        self.assertEqual(FulfillmentBatch.objects.count(), batches_before)

    def test_create_batch_without_selection_is_rejected(self):
        batches_before = FulfillmentBatch.objects.count()

        response = self.client.post(reverse("logistics:batch_create"), {})

        self.assertRedirects(response, reverse("logistics:batch_list"))
        self.assertEqual(FulfillmentBatch.objects.count(), batches_before)


class PickingViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="magazyn", password="tajne123"
        )
        cls.marketplace = make_marketplace()
        cls.product = make_product()
        cls.location_old = make_location("Regał A")
        cls.location_new = make_location("Regał B")

        today = timezone.localdate()
        # Starsza partia ma mniejszy stan, niż wynosi zapotrzebowanie — FIFO musi
        # sięgnąć po obie i wskazać je w tej właśnie kolejności.
        cls.older = make_batch(
            cls.product,
            cls.location_old,
            quantity=3,
            unit_cost="10.00",
            received_at=today - timedelta(days=5),
        )
        cls.newer = make_batch(
            cls.product,
            cls.location_new,
            quantity=10,
            unit_cost="12.00",
            received_at=today,
        )

        cls.batch = FulfillmentBatch.objects.create()
        first = make_order(cls.marketplace, "ORDER-1")
        second = make_order(cls.marketplace, "ORDER-2")
        make_line(first, cls.product, quantity=2)
        make_line(second, cls.product, quantity=3)
        # Pozycja bez mapowania — trafia do osobnej sekcji.
        make_line(second, None, quantity=1, external_offer_id="99999")
        FulfillmentOrder.objects.create(batch=cls.batch, order=first, position=0)
        FulfillmentOrder.objects.create(batch=cls.batch, order=second, position=1)

    def setUp(self):
        self.client.force_login(self.user)

    def test_quantities_are_summed_across_orders(self):
        response = self.client.get(
            reverse("logistics:batch_picking", args=[self.batch.pk])
        )

        rows = response.context["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["quantity"], 5)

    def test_locations_follow_fifo_order(self):
        response = self.client.get(
            reverse("logistics:batch_picking", args=[self.batch.pk])
        )

        locations = response.context["rows"][0]["locations"]
        self.assertEqual(
            [(entry["location"], entry["quantity"]) for entry in locations],
            [(self.location_old, 3), (self.location_new, 2)],
        )
        self.assertEqual(response.context["rows"][0]["missing"], 0)

    def test_shortage_is_reported(self):
        self.newer.delete()

        response = self.client.get(
            reverse("logistics:batch_picking", args=[self.batch.pk])
        )

        self.assertEqual(response.context["rows"][0]["missing"], 2)
        self.assertEqual(response.context["shortages"], 1)

    def test_unmapped_lines_listed_separately(self):
        response = self.client.get(
            reverse("logistics:batch_picking", args=[self.batch.pk])
        )

        unmapped = list(response.context["unmapped"])
        self.assertEqual(len(unmapped), 1)
        self.assertEqual(unmapped[0]["external_offer_id"], "99999")
        self.assertEqual(unmapped[0]["quantity"], 1)

    def test_summary_totals(self):
        response = self.client.get(
            reverse("logistics:batch_summary", args=[self.batch.pk])
        )

        self.assertEqual(response.context["total_orders"], 2)
        self.assertEqual(response.context["total_units"], 6)
        self.assertEqual(response.context["total_value"], Decimal("429.60"))

    def test_packing_tab_redirects_to_first_unpacked_order(self):
        first = self.batch.items.first()

        response = self.client.get(
            reverse("logistics:batch_packing", args=[self.batch.pk])
        )

        self.assertRedirects(
            response,
            reverse(
                "logistics:batch_packing_order", args=[self.batch.pk, first.order_id]
            ),
        )

    def test_batch_can_be_finished(self):
        response = self.client.post(
            reverse("logistics:batch_finish", args=[self.batch.pk])
        )

        self.batch.refresh_from_db()
        self.assertRedirects(
            response, reverse("logistics:batch_summary", args=[self.batch.pk])
        )
        self.assertEqual(self.batch.status, FulfillmentBatchStatus.DONE)
