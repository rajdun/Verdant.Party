"""Koszt nadania paczki pobierany z rozliczeń Allegro.

Allegro nie wystawia osobnego endpointu „ile kosztowała ta przesyłka" — opłata
za nadanie pojawia się jako wpis rozliczeniowy powiązany z zamówieniem. Czytamy
więc te same `billing-entries`, których import używa do prowizji, i wybieramy
wpisy przesyłkowe.

Wpis powstaje dopiero po nadaniu paczki, więc brak wpisu to normalny stan, a nie
awaria — dlatego `ShippingCostUnavailable` jest osobnym wyjątkiem od błędów HTTP.
"""

import logging
import unicodedata
from decimal import Decimal

from django.conf import settings

from apps.marketplaces.allegro.client import AllegroClient, parse_amount
from apps.marketplaces.allegro.oauth import ensure_access_token

logger = logging.getLogger(__name__)

# Fragmenty nazw typów rozliczeniowych — awaryjne dopasowanie, gdy konto zwraca
# identyfikator spoza `settings.ALLEGRO["shipping_billing_types"]`.
SHIPPING_NAME_HINTS = ("przesylk", "dostaw", "nadani", "shipment", "delivery")


# „ł" nie rozkłada się w NFKD na literę + znak łączący, więc trzeba je podmienić
# ręcznie — bez tego „przesyłka" nigdy nie trafiłaby w podpowiedź „przesylk".
_STROKED = str.maketrans({"ł": "l", "Ł": "L"})


def _fold(text):
    """Bez diakrytyków i wielkości liter — nazwy typów bywają niespójne."""
    normalized = unicodedata.normalize("NFKD", str(text or "").translate(_STROKED))
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def is_shipping_entry(entry):
    """Czy wpis rozliczeniowy to opłata za przesyłkę."""
    entry_type = entry.get("type") or {}
    codes = settings.ALLEGRO.get("shipping_billing_types") or []
    if entry_type.get("id") in codes:
        return True
    name = _fold(entry_type.get("name"))
    return any(hint in name for hint in SHIPPING_NAME_HINTS)


class ShippingCostUnavailable(Exception):
    """Allegro odpowiedziało, ale nie zna jeszcze kosztu przesyłki."""


def fetch_shipping_cost(order, client=None):
    """Zwraca koszt nadania paczki dla zamówienia jako Decimal.

    Rzuca `ShippingCostUnavailable` gdy nie ma wpisu przesyłkowego oraz
    `AllegroError` (w tym `AllegroApiError`, `AllegroAuthError`) przy problemie
    z komunikacją — wywołujący rozróżnia je w komunikacie dla operatora.
    """
    if not order.external_order_id:
        raise ShippingCostUnavailable("Zamówienie nie ma identyfikatora Allegro.")

    if client is None:
        ensure_access_token(order.marketplace)
        client = AllegroClient(order.marketplace)

    entries = client.get_billing_entries(order.external_order_id)
    matched = [entry for entry in entries if is_shipping_entry(entry)]
    if not matched:
        raise ShippingCostUnavailable(
            "Allegro nie ma jeszcze wpisu rozliczeniowego za przesyłkę "
            "dla tego zamówienia."
        )

    total = sum(
        (parse_amount((entry.get("value") or {}).get("amount")) for entry in matched),
        Decimal("0"),
    )
    # Obciążenia sprzedawcy Allegro zwraca jako wartości dodatnie, ale korekty
    # bywają ujemne — koszt nigdy nie może wyjść poniżej zera.
    if total < 0:
        logger.warning(
            "Ujemna suma opłat przesyłkowych dla %s: %s", order.external_order_id, total
        )
        raise ShippingCostUnavailable(
            "Suma wpisów przesyłkowych jest ujemna — sprawdź rozliczenia w Allegro."
        )
    return total
