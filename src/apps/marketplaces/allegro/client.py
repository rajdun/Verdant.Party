"""Klient HTTP Allegro REST API.

Cienka warstwa nad sześcioma endpointami, których używa integracja. Nie
publikuje niczego na Allegro — ruch jest wyłącznie odczytowy poza wymianą
tokenów OAuth.
"""

import logging
import time
from collections import deque
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

AUTHORIZE_PATH = "/auth/oauth/authorize"
TOKEN_PATH = "/auth/oauth/token"
OFFERS_PATH = "/sale/offers"
# Bez końcowego ukośnika — ścieżka jest sklejana z identyfikatorem zamówienia.
ORDER_PATH = "/order/checkout-forms"
ORDER_EVENTS_PATH = "/order/events"
BILLING_PATH = "/billing/billing-entries"

ACCEPT_HEADER = "application/vnd.allegro.public.v1+json"

# Typ zdarzenia oznaczający zamówienie gotowe do przetworzenia — pozostałe
# (BOUGHT, FILLED_IN, CANCELLED, ...) importu nie wyzwalają.
EVENT_TYPE_READY = "READY_FOR_PROCESSING"

MAX_RETRIES = 3


class AllegroError(Exception):
    """Błąd komunikacji z Allegro."""


class AllegroApiError(AllegroError):
    def __init__(self, status_code, reason, body):
        self.status_code = status_code
        self.reason = reason
        self.body = body
        super().__init__(f"Allegro API {status_code} {reason}: {body[:500]}")


class AllegroAuthError(AllegroError):
    """Brak ważnego tokenu — integracja wymaga ponownej autoryzacji."""


def parse_amount(value):
    """Kwoty w Allegro API są stringami z kropką — nigdy nie parsuj ich jako float."""
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise AllegroError(f"Nieprawidłowa kwota z Allegro: {value!r}") from exc


class RateLimiter:
    """Przesuwne okno żądań.

    Synchronizacja chodzi w jednym procesie (cron/przycisk w UI), więc licznik
    w pamięci wystarcza — nie ma współbieżnych workerów do skoordynowania.
    """

    def __init__(self, limit, window_seconds):
        self.limit = limit
        self.window = window_seconds
        self._hits = deque()

    def acquire(self):
        now = time.monotonic()
        while self._hits and now - self._hits[0] >= self.window:
            self._hits.popleft()

        if len(self._hits) >= self.limit:
            sleep_for = self.window - (now - self._hits[0])
            if sleep_for > 0:
                logger.warning("Limit żądań Allegro osiągnięty — czekam %.1fs", sleep_for)
                time.sleep(sleep_for)
            return self.acquire()

        self._hits.append(now)


class AllegroClient:
    """Klient związany z jedną integracją (`Marketplace`)."""

    def __init__(self, marketplace, access_token=None):
        self.marketplace = marketplace
        self._access_token = access_token
        self.config = settings.ALLEGRO
        self.session = requests.Session()
        self.rate_limiter = RateLimiter(
            self.config["rate_limit_per_minute"], self.config["rate_limit_window_seconds"]
        )

    @property
    def access_token(self):
        token = self._access_token or self.marketplace.access_token
        if not token:
            raise AllegroAuthError(
                f"Integracja „{self.marketplace.name}” nie ma ważnego tokenu — "
                "połącz ją ponownie z Allegro."
            )
        return token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": ACCEPT_HEADER,
            "User-Agent": self.config["app_name"],
        }

    def _get(self, path, params=None):
        url = f"{self.marketplace.api_base_url}{path}"

        for attempt in range(1, MAX_RETRIES + 1):
            self.rate_limiter.acquire()
            try:
                response = self.session.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    timeout=self.config["timeout_seconds"],
                )
            except requests.RequestException as exc:
                if attempt == MAX_RETRIES:
                    raise AllegroError(f"Błąd połączenia z Allegro ({url}): {exc}") from exc
                time.sleep(2**attempt)
                continue

            if response.status_code == 429 and attempt < MAX_RETRIES:
                retry_after = int(response.headers.get("Retry-After", 5))
                logger.warning("Allegro 429 — ponawiam za %ss", retry_after)
                time.sleep(retry_after)
                continue

            if not response.ok:
                # Treść błędu Allegro jest istotna diagnostycznie — nigdy jej nie gub.
                raise AllegroApiError(response.status_code, response.reason, response.text)

            return response.json()

        raise AllegroError(f"Nie udało się pobrać {url} po {MAX_RETRIES} próbach.")

    # --- endpointy ---------------------------------------------------------

    def get_offers(self, page_size=100, max_pages=100):
        """Wszystkie oferty sprzedawcy — z przewijaniem stron do końca listy."""
        offers = []
        offset = 0

        for _ in range(max_pages):
            payload = self._get(OFFERS_PATH, {"limit": page_size, "offset": offset})
            page = payload.get("offers") or []
            offers.extend(page)

            total = payload.get("totalCount")
            offset += len(page)
            if not page or (total is not None and offset >= total):
                break

        return offers

    def get_order_events(self, from_id="", limit=100):
        params = {"limit": limit, "type": EVENT_TYPE_READY}
        if from_id:
            params["from"] = from_id
        return self._get(ORDER_EVENTS_PATH, params).get("events") or []

    def get_order(self, order_id):
        return self._get(f"{ORDER_PATH}/{order_id}")

    def get_billing_entries(self, order_id, limit=100):
        """Wpisy rozliczeniowe zamówienia (prowizje i opłaty Allegro)."""
        entries = []
        offset = 0

        while True:
            payload = self._get(
                BILLING_PATH, {"order.id": order_id, "limit": limit, "offset": offset}
            )
            page = payload.get("billingEntries") or []
            entries.extend(page)
            offset += len(page)
            if len(page) < limit:
                break

        return entries
