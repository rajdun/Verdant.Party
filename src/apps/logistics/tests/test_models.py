from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.logistics.models import (
    FulfillmentBatch,
    FulfillmentBatchStatus,
    FulfillmentOrder,
)
from apps.logistics.tests.factories import make_order
from apps.marketplaces.tests.factories import make_marketplace


class FulfillmentBatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marketplace = make_marketplace()

    def test_finish_is_idempotent(self):
        batch = FulfillmentBatch.objects.create()
        batch.finish()
        finished_at = batch.finished_at

        batch.finish()

        batch.refresh_from_db()
        self.assertEqual(batch.status, FulfillmentBatchStatus.DONE)
        self.assertEqual(batch.finished_at, finished_at)

    def test_cannot_finish_cancelled_batch(self):
        batch = FulfillmentBatch.objects.create()
        batch.cancel()

        with self.assertRaises(ValidationError):
            batch.finish()

    def test_cancel_is_idempotent(self):
        batch = FulfillmentBatch.objects.create()
        batch.cancel()
        batch.cancel()

        batch.refresh_from_db()
        self.assertEqual(batch.status, FulfillmentBatchStatus.CANCELLED)

    def test_cannot_cancel_batch_with_packed_orders(self):
        batch = FulfillmentBatch.objects.create()
        order = make_order(self.marketplace)
        item = FulfillmentOrder.objects.create(batch=batch, order=order)
        item.mark_packed()

        with self.assertRaises(ValidationError):
            batch.cancel()

        batch.refresh_from_db()
        self.assertEqual(batch.status, FulfillmentBatchStatus.OPEN)

    def test_is_complete_requires_orders(self):
        batch = FulfillmentBatch.objects.create()
        self.assertFalse(batch.is_complete)

        order = make_order(self.marketplace)
        item = FulfillmentOrder.objects.create(batch=batch, order=order)
        self.assertFalse(batch.is_complete)

        item.mark_packed()
        self.assertTrue(batch.is_complete)

    def test_order_cannot_appear_twice_in_one_batch(self):
        batch = FulfillmentBatch.objects.create()
        order = make_order(self.marketplace)
        FulfillmentOrder.objects.create(batch=batch, order=order)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                FulfillmentOrder.objects.create(batch=batch, order=order)

    def test_mark_packed_is_idempotent(self):
        batch = FulfillmentBatch.objects.create()
        item = FulfillmentOrder.objects.create(
            batch=batch, order=make_order(self.marketplace)
        )
        item.mark_packed()
        packed_at = item.packed_at

        item.mark_packed()

        item.refresh_from_db()
        self.assertEqual(item.packed_at, packed_at)
