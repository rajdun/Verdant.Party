from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from apps.marketplaces.allegro.client import (
    ACCEPT_HEADER,
    AllegroApiError,
    AllegroAuthError,
    AllegroClient,
    parse_amount,
)
from apps.marketplaces.tests.factories import make_marketplace


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.reason = "OK" if self.ok else "Bad Request"
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


class ParseAmountTests(TestCase):
    def test_string_amount_becomes_exact_decimal(self):
        self.assertEqual(parse_amount("99.90"), Decimal("99.90"))

    def test_missing_amount_is_zero(self):
        self.assertEqual(parse_amount(None), Decimal("0"))
        self.assertEqual(parse_amount(""), Decimal("0"))


class ClientRequestTests(TestCase):
    def setUp(self):
        self.marketplace = make_marketplace()
        self.client_under_test = AllegroClient(self.marketplace)

    def test_headers_follow_allegro_contract(self):
        with patch.object(
            self.client_under_test.session, "get", return_value=FakeResponse({"events": []})
        ) as mocked:
            self.client_under_test.get_order_events()

        headers = mocked.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer access-token")
        self.assertEqual(headers["Accept"], ACCEPT_HEADER)
        self.assertEqual(headers["User-Agent"], "Verdant.Party")

    def test_event_filter_is_sent_as_query_parameter(self):
        with patch.object(
            self.client_under_test.session, "get", return_value=FakeResponse({"events": []})
        ) as mocked:
            self.client_under_test.get_order_events(from_id="evt-7")

        params = mocked.call_args.kwargs["params"]
        self.assertEqual(params["type"], "READY_FOR_PROCESSING")
        self.assertEqual(params["from"], "evt-7")

    def test_first_fetch_omits_cursor(self):
        with patch.object(
            self.client_under_test.session, "get", return_value=FakeResponse({"events": []})
        ) as mocked:
            self.client_under_test.get_order_events(from_id="")

        self.assertNotIn("from", mocked.call_args.kwargs["params"])

    def test_order_path_has_no_double_slash(self):
        with patch.object(
            self.client_under_test.session, "get", return_value=FakeResponse({"id": "ORDER-1"})
        ) as mocked:
            self.client_under_test.get_order("ORDER-1")

        url = mocked.call_args.args[0]
        self.assertTrue(url.endswith("/order/checkout-forms/ORDER-1"))
        self.assertNotIn("//order", url.replace("https://", ""))

    def test_offers_are_paginated_to_the_end(self):
        pages = [
            FakeResponse({"offers": [{"id": str(i)} for i in range(100)], "totalCount": 150}),
            FakeResponse({"offers": [{"id": str(i)} for i in range(50)], "totalCount": 150}),
        ]
        with patch.object(self.client_under_test.session, "get", side_effect=pages):
            offers = self.client_under_test.get_offers()

        self.assertEqual(len(offers), 150)

    def test_error_response_carries_status_and_body(self):
        with patch.object(
            self.client_under_test.session,
            "get",
            return_value=FakeResponse(status_code=400, text='{"errors":[{"code":"BAD"}]}'),
        ):
            with self.assertRaises(AllegroApiError) as ctx:
                self.client_under_test.get_order("ORDER-1")

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("BAD", ctx.exception.body)

    def test_missing_token_fails_before_any_request(self):
        marketplace = make_marketplace(connected=False, name="Rozłączona")

        with self.assertRaises(AllegroAuthError):
            AllegroClient(marketplace).get_order("ORDER-1")
