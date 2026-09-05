"""Wspólne dane testowe dla integracji marketplace."""

from datetime import timedelta

from django.utils import timezone

from apps.catalog.models import Product
from apps.marketplaces.models import Marketplace, MarketplaceListing


def make_product(**overrides):
    defaults = dict(
        sku="plant-1",
        name="Ficus lyrata",
        item_type=Product.ItemType.MERCHANDISE,
        species="Ficus lyrata",
        latin_name="Ficus lyrata",
        genus="Ficus",
        variety="Lyrata",
        pot_size="12cm",
        low_stock_threshold=5,
    )
    defaults.update(overrides)
    product = Product(**defaults)
    product.full_clean()
    product.save()
    return product


def make_marketplace(connected=True, **overrides):
    defaults = dict(name="Allegro sandbox", notification_email="sklep@example.com")
    defaults.update(overrides)
    marketplace = Marketplace.objects.create(**defaults)
    marketplace.set_credentials("client-id", "client-secret")
    if connected:
        marketplace.store_tokens("access-token", "refresh-token", expires_in=43199)
    return marketplace


def make_listing(marketplace, product, external_id="12345", **overrides):
    defaults = dict(
        title="Ficus lyrata 12cm",
        current_price="99.90",
        currency="PLN",
    )
    defaults.update(overrides)
    return MarketplaceListing.objects.create(
        marketplace=marketplace, product=product, external_id=external_id, **defaults
    )


def checkout_form_payload(order_id="ORDER-1", offer_id="12345", **overrides):
    """Kształt odpowiedzi /order/checkout-forms/{id} — kwoty jako stringi."""
    payload = {
        "id": order_id,
        "status": "READY_FOR_PROCESSING",
        "messageToSeller": "Proszę o staranne zapakowanie.",
        "buyer": {
            "login": "kupujacy1",
            "email": "kupujacy@example.com",
            "firstName": "Anna",
            "lastName": "Kowalska",
            "companyName": None,
            "phoneNumber": "600100200",
            "address": {
                "street": "Polna 1",
                "city": "Warszawa",
                # Adres kupującego używa postCode...
                "postCode": "00-001",
                "countryCode": "PL",
            },
        },
        "payment": {"finishedAt": "2026-08-30T10:15:00Z"},
        "delivery": {
            "address": {
                "firstName": "Anna",
                "lastName": "Kowalska",
                "street": "Leśna 7",
                "city": "Kraków",
                # ...a adres dostawy zipCode.
                "zipCode": "30-001",
                "countryCode": "PL",
                "phoneNumber": "600100200",
            },
            "method": {"id": "m1", "name": "Kurier"},
            "cost": {"amount": "15.00", "currency": "PLN"},
        },
        "lineItems": [
            {
                "id": "line-1",
                "offer": {"id": offer_id, "name": "Ficus lyrata 12cm"},
                "quantity": 2,
                "price": {"amount": "99.90", "currency": "PLN"},
                "boughtAt": "2026-08-30T10:12:00Z",
            }
        ],
        "summary": {"totalToPay": {"amount": "214.80", "currency": "PLN"}},
    }
    payload.update(overrides)
    return payload


def events_payload(order_ids, first_event_id=1):
    """Strumień zdarzeń — jedno zamówienie zwykle generuje ich kilka."""
    events = []
    for index, order_id in enumerate(order_ids):
        events.append(
            {
                "id": f"evt-{first_event_id + index}",
                "occurredAt": (
                    timezone.now() - timedelta(minutes=len(order_ids) - index)
                ).isoformat(),
                "type": "READY_FOR_PROCESSING",
                "order": {"checkoutForm": {"id": order_id}},
            }
        )
    return events


def billing_payload(order_id="ORDER-1", amounts=("-11.50", "-2.30")):
    """Obciążenia sprzedawcy — Allegro podaje je ze znakiem minus."""
    return [
        {
            "id": f"be-{index}",
            "value": {"amount": amount, "currency": "PLN"},
            "order": {"id": order_id},
            "type": {"name": "Prowizja od sprzedaży"},
        }
        for index, amount in enumerate(amounts)
    ]


class FakeAllegroClient:
    """Podstawka pod klienta — zapisuje wywołania, nie rusza sieci."""

    def __init__(self, orders=None, events=None, billing=None, offers=None):
        self.orders = orders or {}
        self.events = events or []
        self.billing = billing or {}
        self.offers = offers or []
        self.fetched_orders = []

    def get_order_events(self, from_id="", limit=100):
        return self.events

    def get_order(self, order_id):
        self.fetched_orders.append(order_id)
        return self.orders[order_id]

    def get_billing_entries(self, order_id, limit=100):
        return self.billing.get(order_id, [])

    def get_offers(self, page_size=100, max_pages=100):
        return self.offers
