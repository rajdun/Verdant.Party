"""Import zamówień z Allegro.

Allegro nie ma webhooków na zamówienia — jedyną drogą jest odpytywanie
strumienia zdarzeń. Identyfikator ostatniego przetworzonego zdarzenia jest
kursorem zapisanym w bazie; przesuwamy go dopiero po przetworzeniu całej paczki,
żeby błąd importu nie spowodował cichego pominięcia zamówień.
"""

import logging
from decimal import Decimal

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.marketplaces.allegro.client import AllegroClient, parse_amount
from apps.marketplaces.allegro.oauth import ensure_access_token
from apps.marketplaces.allegro.shipping import is_shipping_entry
from apps.marketplaces.models import SyncKind, SyncRun, SyncStatus
from apps.orders.models import Order, OrderLine

logger = logging.getLogger(__name__)


class OrderImportError(Exception):
    """Zamówienia nie dało się zaimportować."""


def _get(payload, *path, default=None):
    """Bezpieczne zejście po zagnieżdżonym JSON-ie (Allegro często zwraca null)."""
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _buyer_name(buyer):
    full_name = f"{_get(buyer, 'firstName', default='')} {_get(buyer, 'lastName', default='')}".strip()
    return full_name or _get(buyer, "companyName", default="") or _get(buyer, "login", default="")


def map_order_payload(payload):
    """Spłaszcza odpowiedź /order/checkout-forms do pól modelu `Order`.

    Uwaga na niespójność Allegro: adres kupującego ma `postCode`,
    a adres dostawy i faktury — `zipCode`.
    """
    buyer = _get(payload, "buyer", default={}) or {}
    buyer_address = _get(buyer, "address", default={}) or {}
    delivery = _get(payload, "delivery", default={}) or {}
    delivery_address = _get(delivery, "address", default={}) or {}

    recipient = (
        f"{_get(delivery_address, 'firstName', default='')} "
        f"{_get(delivery_address, 'lastName', default='')}"
    ).strip()

    line_items = payload.get("lineItems") or []
    bought_at = next((item.get("boughtAt") for item in line_items if item.get("boughtAt")), None)
    placed_at = bought_at or _get(payload, "payment", "finishedAt")

    return {
        "external_status": payload.get("status") or "",
        "buyer_login": _get(buyer, "login", default="") or "",
        "buyer_full_name": _buyer_name(buyer),
        "buyer_email": _get(buyer, "email", default="") or "",
        "buyer_phone": _get(buyer, "phoneNumber", default="") or "",
        "buyer_address": _get(buyer_address, "street", default="") or "",
        "buyer_city": _get(buyer_address, "city", default="") or "",
        "buyer_postal_code": _get(buyer_address, "postCode", default="") or "",
        "buyer_country": _get(buyer_address, "countryCode", default="") or "",
        # Dane dostawy potrafią być puste (odbiór osobisty) — wtedy schodzimy
        # na adres kupującego, tak jak robi to referencyjna implementacja.
        "delivery_recipient_name": recipient or _buyer_name(buyer),
        "delivery_street": (
            _get(delivery_address, "street", default="")
            or _get(buyer_address, "street", default="")
            or ""
        ),
        "delivery_city": (
            _get(delivery_address, "city", default="")
            or _get(buyer_address, "city", default="")
            or ""
        ),
        "delivery_postal_code": (
            _get(delivery_address, "zipCode", default="")
            or _get(buyer_address, "postCode", default="")
            or ""
        ),
        "delivery_country_code": (
            _get(delivery_address, "countryCode", default="")
            or _get(buyer_address, "countryCode", default="")
            or ""
        ),
        "delivery_phone": (
            _get(delivery_address, "phoneNumber", default="")
            or _get(buyer, "phoneNumber", default="")
            or ""
        ),
        "delivery_company_name": (
            _get(delivery_address, "companyName", default="")
            or _get(buyer, "companyName", default="")
            or ""
        ),
        "delivery_method_name": _get(delivery, "method", "name", default="") or "",
        "delivery_pickup_point_id": _get(delivery, "pickupPoint", "id", default="") or "",
        "delivery_pickup_point_name": _get(delivery, "pickupPoint", "name", default="") or "",
        "delivery_cost": parse_amount(_get(delivery, "cost", "amount")),
        "currency": _get(payload, "summary", "totalToPay", "currency", default="PLN") or "PLN",
        "total_to_pay": parse_amount(_get(payload, "summary", "totalToPay", "amount")),
        "placed_at": parse_datetime(placed_at) if placed_at else None,
        "message_to_seller": payload.get("messageToSeller") or "",
    }


def sum_commission(billing_entries):
    """Suma obciążeń sprzedawcy jako koszt dodatni.

    Allegro zwraca obciążenia ze znakiem minus (a zwroty opłat na plus), więc
    sumę odwracamy — `Order.platform_commission` stoi po stronie kosztów i musi
    być dodatnia, inaczej `total_costs` odejmowałoby prowizję zamiast ją dodać.

    Opłaty za przesyłkę są pomijane: trafiają osobno do `Order.shipping_cost`
    przy pakowaniu, więc wliczone tutaj podwoiłyby koszt w rachunku zysku.
    """
    return -sum(
        (
            parse_amount(_get(entry, "value", "amount"))
            for entry in billing_entries
            if not is_shipping_entry(entry)
        ),
        Decimal("0"),
    )


def _notify_failure(marketplace, subject, body):
    recipient = marketplace.notification_recipient
    if not recipient:
        logger.warning("Brak adresu do powiadomień dla %s: %s", marketplace.name, subject)
        return
    try:
        send_mail(subject, body, None, [recipient], fail_silently=True)
    except Exception:  # noqa: BLE001 — powiadomienie nie może wywrócić importu
        logger.exception("Nie udało się wysłać powiadomienia na %s", recipient)


def import_order(marketplace, external_order_id, client=None):
    """Pobiera i zapisuje jedno zamówienie. Zwraca (Order|None, utworzone)."""
    if Order.objects.filter(external_order_id=external_order_id).exists():
        # Strumień zdarzeń zwraca to samo zamówienie wielokrotnie — to nie błąd.
        return None, False

    client = client or AllegroClient(marketplace)
    payload = client.get_order(external_order_id)

    line_items = payload.get("lineItems") or []
    if not line_items:
        raise OrderImportError(f"Zamówienie {external_order_id} nie ma żadnych pozycji.")

    offer_ids = {
        _get(item, "offer", "id") for item in line_items if _get(item, "offer", "id")
    }
    # Bez filtra po statusie — zamówienie potrafi dotrzeć po zakończeniu oferty,
    # a mapowanie na produkt jest wtedy nadal poprawne.
    listings = marketplace.listings.filter(external_id__in=offer_ids).select_related("product")
    product_by_offer = {listing.external_id: listing.product for listing in listings}

    if not any(_get(item, "offer", "id") in product_by_offer for item in line_items):
        raise OrderImportError(
            f"Zamówienie {external_order_id} odrzucone — żadna z ofert "
            f"({', '.join(sorted(offer_ids))}) nie jest zmapowana na produkt."
        )

    commission = sum_commission(client.get_billing_entries(external_order_id))
    fields = map_order_payload(payload)

    with transaction.atomic():
        order = Order.objects.create(
            external_order_id=external_order_id,
            marketplace=marketplace,
            platform_commission=commission,
            **fields,
        )
        for item in line_items:
            offer_id = _get(item, "offer", "id") or ""
            product = product_by_offer.get(offer_id)
            if product is None:
                logger.warning(
                    "Oferta %s w zamówieniu %s bez mapowania — pozycja bez produktu.",
                    offer_id,
                    external_order_id,
                )
            OrderLine.objects.create(
                order=order,
                product=product,
                external_offer_id=offer_id,
                external_offer_name=_get(item, "offer", "name", default="") or "",
                quantity=item.get("quantity") or 1,
                unit_price=parse_amount(_get(item, "price", "amount")),
            )

    return order, True


def fetch_events(marketplace, client=None):
    """Jeden przebieg importu dla integracji. Zwraca `SyncRun`."""
    run = SyncRun.objects.create(marketplace=marketplace, kind=SyncKind.EVENTS)
    problems = []

    try:
        ensure_access_token(marketplace)
        client = client or AllegroClient(marketplace)
        events = client.get_order_events(from_id=marketplace.last_event_id)
    except Exception as exc:  # noqa: BLE001 — przebieg zawsze kończy się wpisem w logu
        run.finish(SyncStatus.FAILED, str(exc))
        _notify_failure(
            marketplace, f"Błąd synchronizacji {marketplace.name}", str(exc)
        )
        return run

    events = sorted(events, key=lambda event: event.get("occurredAt") or "")
    run.events_seen = len(events)

    if not events:
        marketplace.last_synced_at = timezone.now()
        marketplace.save(update_fields=["last_synced_at", "updated_at"])
        run.finish(SyncStatus.OK, "Brak nowych zdarzeń.")
        return run

    # Jedno zamówienie generuje wiele zdarzeń — bierzemy każde tylko raz.
    seen = []
    for event in events:
        order_id = _get(event, "order", "checkoutForm", "id")
        if order_id and order_id not in seen:
            seen.append(order_id)

    for order_id in seen:
        try:
            _, created = import_order(marketplace, order_id, client=client)
            if created:
                run.orders_imported += 1
            else:
                run.orders_skipped += 1
        except Exception as exc:  # noqa: BLE001 — jedno złe zamówienie nie blokuje reszty
            logger.exception("Import zamówienia %s nieudany", order_id)
            run.orders_skipped += 1
            problems.append(f"{order_id}: {exc}")

    # Kursor przesuwamy niezależnie od pojedynczych odrzuceń (te są trwałe i
    # ponowna próba nic by nie zmieniła), ale całą listę błędów zapisujemy.
    marketplace.last_event_id = events[-1].get("id") or marketplace.last_event_id
    marketplace.last_synced_at = timezone.now()
    marketplace.save(update_fields=["last_event_id", "last_synced_at", "updated_at"])

    if problems:
        message = "\n".join(problems)
        run.finish(SyncStatus.PARTIAL, message)
        _notify_failure(
            marketplace,
            f"Problemy przy imporcie zamówień — {marketplace.name}",
            message,
        )
    else:
        run.finish(SyncStatus.OK, f"Zaimportowano {run.orders_imported} zamówień.")

    return run
