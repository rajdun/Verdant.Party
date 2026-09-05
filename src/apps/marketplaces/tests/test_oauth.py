from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.marketplaces.allegro import oauth
from apps.marketplaces.allegro.client import AllegroAuthError
from apps.marketplaces.models import Marketplace
from apps.marketplaces.tests.factories import make_marketplace


class FakeTokenResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload if payload is not None else {
            "access_token": "nowy-access",
            "refresh_token": "nowy-refresh",
            "expires_in": 43199,
        }
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.reason = "OK" if self.ok else "Unauthorized"
        self.text = text

    def json(self):
        return self._payload


class AuthorizeUrlTests(TestCase):
    def test_url_carries_required_parameters_and_saves_state(self):
        marketplace = make_marketplace(connected=False)

        url = oauth.build_authorize_url(marketplace, "https://app.example.com/callback/")

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        self.assertEqual(parsed.path, "/auth/oauth/authorize")
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["client_id"], ["client-id"])
        self.assertEqual(params["redirect_uri"], ["https://app.example.com/callback/"])

        marketplace.refresh_from_db()
        self.assertEqual(params["state"], [marketplace.oauth_state])
        self.assertGreater(marketplace.oauth_state_expires_at, timezone.now())

    def test_missing_credentials_blocks_start(self):
        marketplace = Marketplace.objects.create(name="Bez danych")

        with self.assertRaises(AllegroAuthError):
            oauth.build_authorize_url(marketplace, "https://app.example.com/callback/")


class ExchangeCodeTests(TestCase):
    def setUp(self):
        self.marketplace = make_marketplace(connected=False)
        self.redirect_uri = "https://app.example.com/callback/"
        oauth.build_authorize_url(self.marketplace, self.redirect_uri)
        self.marketplace.refresh_from_db()
        self.state = self.marketplace.oauth_state

    def test_valid_state_exchanges_code_and_stores_tokens(self):
        with patch("apps.marketplaces.allegro.oauth.requests.post", return_value=FakeTokenResponse()):
            oauth.exchange_code(self.marketplace, "kod", self.state, self.redirect_uri)

        reloaded = Marketplace.objects.get(pk=self.marketplace.pk)
        self.assertEqual(reloaded.access_token, "nowy-access")
        self.assertEqual(reloaded.refresh_token, "nowy-refresh")
        self.assertTrue(reloaded.is_connected())

    def test_state_is_single_use(self):
        with patch("apps.marketplaces.allegro.oauth.requests.post", return_value=FakeTokenResponse()):
            oauth.exchange_code(self.marketplace, "kod", self.state, self.redirect_uri)

        with self.assertRaises(ValidationError):
            oauth.exchange_code(self.marketplace, "kod", self.state, self.redirect_uri)

    def test_mismatched_state_is_rejected(self):
        with self.assertRaises(ValidationError):
            oauth.exchange_code(self.marketplace, "kod", "podrobione", self.redirect_uri)

    def test_expired_state_is_rejected(self):
        self.marketplace.oauth_state_expires_at = timezone.now() - timedelta(minutes=1)
        self.marketplace.save(update_fields=["oauth_state_expires_at"])

        with self.assertRaises(ValidationError):
            oauth.exchange_code(self.marketplace, "kod", self.state, self.redirect_uri)


class RefreshTokenTests(TestCase):
    def test_rotated_refresh_token_is_saved(self):
        marketplace = make_marketplace()

        with patch("apps.marketplaces.allegro.oauth.requests.post", return_value=FakeTokenResponse()):
            oauth.refresh_token(marketplace)

        reloaded = Marketplace.objects.get(pk=marketplace.pk)
        self.assertEqual(reloaded.refresh_token, "nowy-refresh")
        self.assertEqual(reloaded.access_token, "nowy-access")

    def test_rejected_refresh_disconnects_integration(self):
        marketplace = make_marketplace()

        with patch(
            "apps.marketplaces.allegro.oauth.requests.post",
            return_value=FakeTokenResponse(payload={}, status_code=401, text="invalid_grant"),
        ):
            with self.assertRaises(AllegroAuthError):
                oauth.refresh_token(marketplace)

        reloaded = Marketplace.objects.get(pk=marketplace.pk)
        self.assertFalse(reloaded.is_connected())
        self.assertEqual(reloaded.refresh_token, "")
        # Client ID/secret zostają — wystarczy ponowna autoryzacja.
        self.assertTrue(reloaded.has_credentials())

    def test_ensure_access_token_refreshes_expiring_session(self):
        marketplace = make_marketplace()
        # Token ważny 5 minut — poniżej bufora, więc wymaga odświeżenia.
        marketplace.store_tokens("stary-access", "stary-refresh", expires_in=300)

        with patch(
            "apps.marketplaces.allegro.oauth.requests.post", return_value=FakeTokenResponse()
        ) as mocked:
            token = oauth.ensure_access_token(marketplace)

        self.assertEqual(token, "nowy-access")
        self.assertEqual(mocked.call_args.kwargs["data"]["grant_type"], "refresh_token")
