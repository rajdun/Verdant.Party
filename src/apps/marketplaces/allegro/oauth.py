"""Przepływ OAuth2 Authorization Code Grant dla Allegro.

Parametr `state` generowany jest wyłącznie po stronie serwera, zapisywany na
integracji z 15-minutową ważnością i kasowany przy pierwszej weryfikacji.
Access token nigdy nie trafia do przeglądarki — wymiana kodu na token dzieje
się w całości tutaj.
"""

import base64
import logging
import secrets
from urllib.parse import urlencode

import requests
from django.conf import settings

from apps.marketplaces.allegro.client import (
    AUTHORIZE_PATH,
    TOKEN_PATH,
    AllegroAuthError,
    AllegroError,
)

logger = logging.getLogger(__name__)


def get_redirect_uri():
    redirect_uri = settings.ALLEGRO.get("redirect_uri")
    if not redirect_uri:
        raise AllegroError(
            "Brak ALLEGRO_REDIRECT_URI — ustaw adres powrotny i zarejestruj go "
            "w panelu deweloperskim Allegro."
        )
    return redirect_uri


def build_authorize_url(marketplace, redirect_uri=None):
    """Adres, na który przekierowujemy sprzedawcę, plus zapis parametru state."""
    if not marketplace.has_credentials():
        raise AllegroAuthError(
            "Uzupełnij Client ID i Client Secret przed połączeniem z Allegro."
        )

    redirect_uri = redirect_uri or get_redirect_uri()
    state = secrets.token_hex(32)
    marketplace.start_oauth(state)

    query = urlencode(
        {
            "response_type": "code",
            "client_id": marketplace.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{marketplace.base_url}{AUTHORIZE_PATH}?{query}"


def _post_token(marketplace, data):
    """Wywołanie /auth/oauth/token z uwierzytelnieniem Basic."""
    basic = base64.b64encode(
        f"{marketplace.client_id}:{marketplace.client_secret}".encode()
    ).decode()

    try:
        response = requests.post(
            f"{marketplace.base_url}{TOKEN_PATH}",
            data=data,
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=settings.ALLEGRO["timeout_seconds"],
        )
    except requests.RequestException as exc:
        raise AllegroError(f"Błąd połączenia z Allegro OAuth: {exc}") from exc

    if not response.ok:
        raise AllegroAuthError(
            f"Allegro OAuth {response.status_code} {response.reason}: {response.text[:500]}"
        )

    payload = response.json()
    if not payload.get("access_token"):
        raise AllegroAuthError("Allegro nie zwróciło access tokenu.")

    # Refresh token jest rotowany przy każdym odświeżeniu — zapisujemy nowy.
    marketplace.store_tokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token", ""),
        expires_in=payload.get("expires_in", 0),
    )
    return payload


def exchange_code(marketplace, code, state, redirect_uri=None):
    """Wymiana kodu autoryzacyjnego na tokeny (po powrocie z Allegro)."""
    # Rzuca ValidationError przy niezgodnym lub wygasłym state; kasuje go zawsze.
    marketplace.consume_oauth_state(state)

    redirect_uri = redirect_uri or get_redirect_uri()
    return _post_token(
        marketplace,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )


def refresh_token(marketplace):
    """Odświeżenie sesji. Niepowodzenie = integracja wymaga ponownego OAuth."""
    if not marketplace.refresh_token:
        raise AllegroAuthError(
            f"Integracja „{marketplace.name}” nie ma refresh tokenu — połącz ją ponownie."
        )

    try:
        return _post_token(
            marketplace,
            {"grant_type": "refresh_token", "refresh_token": marketplace.refresh_token},
        )
    except AllegroAuthError:
        # Refresh token unieważniony — czyścimy sesję, żeby UI pokazało „rozłączona".
        marketplace.clear_tokens()
        raise


def ensure_access_token(marketplace):
    """Zwraca ważny access token, odświeżając go w razie potrzeby."""
    if marketplace.access_token:
        return marketplace.access_token
    refresh_token(marketplace)
    return marketplace.access_token
