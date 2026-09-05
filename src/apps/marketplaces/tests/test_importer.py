from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.marketplaces.allegro.importer import OrderImportError, fetch_events, import_order
from apps.marketplaces.models import SyncStatus
from apps.marketplaces.tests.factories import (
    FakeAllegroClient,
    billing_payload,
    checkout_form_payload,
    events_payload,
    make_listing,
    make_marketplace,
    make_product,
)
from apps.orders.models import Order


class ImportOrderTests(TestCase):
    def setUp(self):
        self.marketplace = make_marketplace()
        self.product = make_product()
        make_listing(self.marketplace, self.product, external_id="12345")
        self.client_stub = FakeAllegroClient(
            orders={"ORDER-1": checkout_form_payload()},
            billing={"ORDER-1": billing_payload()},
        )

    def test_order_and_lines_are_created(self):
        order, created = import_order(self.marketplace, "ORDER-1", client=self.client_stub)

        self.assertTrue(created)
        self.assertEqual(order.external_order_id, "ORDER-1")
        self.assertEqual(order.buyer_full_name, "Anna Kowalska")
        self.assertEqual(order.buyer_postal_code, "00-001")
        # Dostawa ma własny adres i inną nazwę pola kodu pocztowego niż kupujący.
        self.assertEqual(order.delivery_postal_code, "30-001")
        self.assertEqual(order.delivery_city, "Kraków")
        self.assertEqual(order.delivery_method_name, "Kurier")
        self.assertEqual(order.total_to_pay, Decimal("214.80"))
        self.assertEqual(order.delivery_cost, Decimal("15.00"))
        self.assertIsNotNone(order.placed_at)

        line = order.lines.get()
        self.assertEqual(line.product, self.product)
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.unit_price, Decimal("99.90"))
        self.assertEqual(line.total_price, Decimal("199.80"))

    def test_commission_is_sum_of_billing_entries(self):
        order, _ = import_order(self.marketplace, "ORDER-1", client=self.client_stub)

        self.assertEqual(order.platform_commission, Decimal("13.80"))

    def test_shipping_fee_is_excluded_from_commission(self):
        # Opłata za przesyłkę trafia osobno do Order.shipping_cost przy pakowaniu
        # — policzona też jako prowizja podwoiłaby koszt w marży.
        self.client_stub.billing["ORDER-1"] = billing_payload() + [
            {
                "id": "be-shipping",
                "value": {"amount": "-14.50", "currency": "PLN"},
                "order": {"id": "ORDER-1"},
                "type": {"name": "Opłata za przesyłkę"},
            }
        ]

        order, _ = import_order(self.marketplace, "ORDER-1", client=self.client_stub)

        self.assertEqual(order.platform_commission, Decimal("13.80"))

    def test_second_import_does_not_duplicate(self):
        import_order(self.marketplace, "ORDER-1", client=self.client_stub)

        order, created = import_order(self.marketplace, "ORDER-1", client=self.client_stub)

        self.assertIsNone(order)
        self.assertFalse(created)
        self.assertEqual(Order.objects.count(), 1)

    def test_unmapped_line_is_kept_without_product(self):
        payload = checkout_form_payload()
        payload["lineItems"].append(
            {
                "id": "line-2",
                "offer": {"id": "99999", "name": "Doniczka ceramiczna"},
                "quantity": 1,
                "price": {"amount": "19.00", "currency": "PLN"},
                "boughtAt": "2026-08-30T10:12:00Z",
            }
        )
        client_stub = FakeAllegroClient(orders={"ORDER-1": payload}, billing={})

        order, _ = import_order(self.marketplace, "ORDER-1", client=client_stub)

        unmapped = order.lines.get(external_offer_id="99999")
        self.assertIsNone(unmapped.product)
        self.assertEqual(unmapped.external_offer_name, "Doniczka ceramiczna")
        self.assertTrue(order.has_unmapped_lines)

    def test_order_without_any_mapping_is_rejected(self):
        payload = checkout_form_payload(offer_id="00000")
        client_stub = FakeAllegroClient(orders={"ORDER-2": payload}, billing={})

        with self.assertRaises(OrderImportError):
            import_order(self.marketplace, "ORDER-2", client=client_stub)

        self.assertFalse(Order.objects.filter(external_order_id="ORDER-2").exists())

    def test_buyer_name_falls_back_to_login(self):
        payload = checkout_form_payload()
        payload["buyer"].update({"firstName": None, "lastName": None, "companyName": None})
        client_stub = FakeAllegroClient(
            orders={"ORDER-3": payload}, billing={}
        )

        order, _ = import_order(self.marketplace, "ORDER-3", client=client_stub)

        self.assertEqual(order.buyer_full_name, "kupujacy1")


class FetchEventsTests(TestCase):
    def setUp(self):
        self.marketplace = make_marketplace()
        self.product = make_product()
        make_listing(self.marketplace, self.product, external_id="12345")

    def _client(self, order_ids, events=None):
        return FakeAllegroClient(
            orders={
                order_id: checkout_form_payload(order_id=order_id) for order_id in set(order_ids)
            },
            events=events if events is not None else events_payload(order_ids),
            billing={order_id: billing_payload(order_id) for order_id in set(order_ids)},
        )

    def test_duplicate_events_fetch_each_order_once(self):
        client_stub = self._client(["ORDER-1", "ORDER-1", "ORDER-2"])

        run = fetch_events(self.marketplace, client=client_stub)

        self.assertEqual(client_stub.fetched_orders, ["ORDER-1", "ORDER-2"])
        self.assertEqual(run.events_seen, 3)
        self.assertEqual(run.orders_imported, 2)
        self.assertEqual(run.status, SyncStatus.OK)

    def test_cursor_advances_to_last_event(self):
        client_stub = self._client(["ORDER-1", "ORDER-2"])

        fetch_events(self.marketplace, client=client_stub)

        self.marketplace.refresh_from_db()
        self.assertEqual(self.marketplace.last_event_id, "evt-2")
        self.assertIsNotNone(self.marketplace.last_synced_at)

    def test_empty_batch_leaves_cursor_untouched(self):
        self.marketplace.last_event_id = "evt-9"
        self.marketplace.save(update_fields=["last_event_id"])
        client_stub = self._client([], events=[])

        run = fetch_events(self.marketplace, client=client_stub)

        self.marketplace.refresh_from_db()
        self.assertEqual(self.marketplace.last_event_id, "evt-9")
        self.assertEqual(run.status, SyncStatus.OK)

    def test_failed_fetch_does_not_move_cursor(self):
        self.marketplace.last_event_id = "evt-9"
        self.marketplace.save(update_fields=["last_event_id"])

        with patch(
            "apps.marketplaces.allegro.importer.ensure_access_token",
            side_effect=RuntimeError("Allegro niedostępne"),
        ):
            run = fetch_events(self.marketplace)

        self.marketplace.refresh_from_db()
        self.assertEqual(self.marketplace.last_event_id, "evt-9")
        self.assertEqual(run.status, SyncStatus.FAILED)
        self.assertIn("Allegro niedostępne", run.message)

    def test_rejected_order_marks_run_partial(self):
        client_stub = FakeAllegroClient(
            orders={"ORDER-9": checkout_form_payload(order_id="ORDER-9", offer_id="00000")},
            events=events_payload(["ORDER-9"]),
            billing={},
        )

        run = fetch_events(self.marketplace, client=client_stub)

        self.assertEqual(run.status, SyncStatus.PARTIAL)
        self.assertEqual(run.orders_imported, 0)
        self.assertEqual(run.orders_skipped, 1)
        self.assertIn("ORDER-9", run.message)
