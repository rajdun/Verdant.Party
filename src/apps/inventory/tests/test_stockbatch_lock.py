"""Ruszona partia (coś z niej zeszło) jest niezmienna — zostaje tylko przeniesienie."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.inventory.models import StockBatch
from apps.logistics.tests.factories import make_batch, make_location
from apps.marketplaces.tests.factories import make_product


class StockBatchLockTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="magazyn", password="tajne123"
        )
        self.client.force_login(self.user)

        self.product = make_product()
        self.location = make_location()
        self.other_location = make_location("Regał B")
        self.batch = make_batch(self.product, self.location, quantity=10, unit_cost="10.00")

    def form_payload(self, **overrides):
        payload = {
            "product": self.product.pk,
            "location": self.location.pk,
            "quantity_received": 99,
            "unit_cost": "99.00",
            "received_at": self.batch.received_at.isoformat(),
            "supplier_name": "",
            "document_reference": "",
            "note": "",
        }
        payload.update(overrides)
        return payload

    def test_fresh_batch_is_not_locked(self):
        self.assertFalse(self.batch.is_locked)

    def test_batch_is_locked_after_fifo_consumption(self):
        StockBatch.consume_fifo(self.product, 3)
        self.batch.refresh_from_db()
        self.assertTrue(self.batch.is_locked)

    def test_batch_is_locked_after_partial_relocation(self):
        self.client.post(
            reverse("inventory:stockbatch_relocate", args=[self.batch.pk]),
            {"location": self.other_location.pk, "quantity": 4},
        )
        self.batch.refresh_from_db()
        self.assertTrue(self.batch.is_locked)

    def test_update_of_locked_batch_is_blocked(self):
        StockBatch.consume_fifo(self.product, 3)
        url = reverse("inventory:stockbatch_update", args=[self.batch.pk])

        response = self.client.get(url)
        self.assertRedirects(response, reverse("inventory:stockbatch_list"))

        response = self.client.post(url, self.form_payload())
        self.assertRedirects(response, reverse("inventory:stockbatch_list"))

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_received, 10)
        self.assertEqual(self.batch.unit_cost, Decimal("10.00"))

    def test_delete_of_locked_batch_is_blocked(self):
        StockBatch.consume_fifo(self.product, 3)
        url = reverse("inventory:stockbatch_delete", args=[self.batch.pk])

        response = self.client.get(url)
        self.assertRedirects(response, reverse("inventory:stockbatch_list"))

        response = self.client.post(url)
        self.assertRedirects(response, reverse("inventory:stockbatch_list"))
        self.assertTrue(StockBatch.objects.filter(pk=self.batch.pk).exists())

    def test_untouched_batch_can_still_be_edited(self):
        response = self.client.post(
            reverse("inventory:stockbatch_update", args=[self.batch.pk]),
            self.form_payload(quantity_remaining=10),
        )
        self.assertRedirects(response, reverse("inventory:stockbatch_list"))

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.quantity_received, 99)
        self.assertEqual(self.batch.unit_cost, Decimal("99.00"))

    def test_untouched_batch_can_still_be_deleted(self):
        response = self.client.post(
            reverse("inventory:stockbatch_delete", args=[self.batch.pk])
        )
        self.assertRedirects(response, reverse("inventory:stockbatch_list"))
        self.assertFalse(StockBatch.objects.filter(pk=self.batch.pk).exists())

    def test_locked_batch_can_still_be_relocated(self):
        StockBatch.consume_fifo(self.product, 3)

        response = self.client.post(
            reverse("inventory:stockbatch_relocate", args=[self.batch.pk]),
            {"location": self.other_location.pk, "quantity": 7},
        )
        self.assertRedirects(response, reverse("inventory:stock_overview"))

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.location, self.other_location)
        self.assertEqual(self.batch.quantity_remaining, 7)

    def test_quantity_remaining_field_hidden_on_locked_batch_form(self):
        StockBatch.consume_fifo(self.product, 3)
        self.batch.refresh_from_db()
        from apps.inventory.forms import StockBatchForm

        self.assertNotIn("quantity_remaining", StockBatchForm(instance=self.batch).fields)
