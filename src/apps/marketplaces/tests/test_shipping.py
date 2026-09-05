from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.marketplaces.allegro.client import AllegroApiError
from apps.marketplaces.allegro.shipping import (
    ShippingCostUnavailable,
    fetch_shipping_cost,
    is_shipping_entry,
)
from apps.marketplaces.tests.factories import make_marketplace

SHIPPING_SETTINGS = {
    "sandbox": {"base_url": "https://s", "api_base_url": "https://api.s"},
    "production": {"base_url": "https://p", "api_base_url": "https://api.p"},
    "app_name": "Verdant.Party",
    "rate_limit_per_minute": 1000,
    "rate_limit_window_seconds": 60,
    "timeout_seconds": 30,
    "redirect_uri": "",
    "shipping_billing_types": ["SUC"],
}


def entry(amount, type_id=None, name=""):
    return {"value": {"amount": amount, "currency": "PLN"}, "type": {"id": type_id, "name": name}}


class FakeBillingClient:
    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def get_billing_entries(self, order_id, limit=100):
        self.calls.append(order_id)
        return self.entries


class Order:
    """Minimalny obiekt zamówienia — moduł potrzebuje tylko tych dwóch pól."""

    def __init__(self, external_order_id="ORDER-1", marketplace=None):
        self.external_order_id = external_order_id
        self.marketplace = marketplace


@override_settings(ALLEGRO=SHIPPING_SETTINGS)
class IsShippingEntryTests(TestCase):
    def test_matches_configured_type_id(self):
        self.assertTrue(is_shipping_entry(entry("10.00", type_id="SUC")))

    def test_matches_name_without_diacritics(self):
        self.assertTrue(is_shipping_entry(entry("10.00", name="Opłata za przesyłkę")))

    def test_commission_is_not_shipping(self):
        self.assertFalse(is_shipping_entry(entry("10.00", name="Prowizja od sprzedaży")))


@override_settings(ALLEGRO=SHIPPING_SETTINGS)
class FetchShippingCostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.marketplace = make_marketplace()

    def test_sums_matching_entries(self):
        client = FakeBillingClient(
            [
                entry("11.50", type_id="SUC"),
                entry("2.30", type_id="SUC"),
                entry("13.80", name="Prowizja od sprzedaży"),
            ]
        )

        cost = fetch_shipping_cost(Order(marketplace=self.marketplace), client=client)

        self.assertEqual(cost, Decimal("13.80"))
        self.assertEqual(client.calls, ["ORDER-1"])

    def test_no_shipping_entry_raises_unavailable(self):
        client = FakeBillingClient([entry("13.80", name="Prowizja od sprzedaży")])

        with self.assertRaises(ShippingCostUnavailable):
            fetch_shipping_cost(Order(marketplace=self.marketplace), client=client)

    def test_empty_billing_raises_unavailable(self):
        with self.assertRaises(ShippingCostUnavailable):
            fetch_shipping_cost(
                Order(marketplace=self.marketplace), client=FakeBillingClient([])
            )

    def test_order_without_external_id_raises_unavailable(self):
        with self.assertRaises(ShippingCostUnavailable):
            fetch_shipping_cost(
                Order(external_order_id="", marketplace=self.marketplace),
                client=FakeBillingClient([entry("11.50", type_id="SUC")]),
            )

    def test_api_error_propagates(self):
        class FailingClient:
            def get_billing_entries(self, order_id, limit=100):
                raise AllegroApiError(500, "Server Error", "{}")

        with self.assertRaises(AllegroApiError):
            fetch_shipping_cost(
                Order(marketplace=self.marketplace), client=FailingClient()
            )

    @patch("apps.marketplaces.allegro.shipping.ensure_access_token")
    @patch("apps.marketplaces.allegro.shipping.AllegroClient")
    def test_builds_client_when_none_given(self, client_cls, ensure):
        client_cls.return_value = FakeBillingClient([entry("11.50", type_id="SUC")])
        order = Order(marketplace=self.marketplace)

        cost = fetch_shipping_cost(order)

        self.assertEqual(cost, Decimal("11.50"))
        ensure.assert_called_once_with(self.marketplace)
        client_cls.assert_called_once_with(self.marketplace)
