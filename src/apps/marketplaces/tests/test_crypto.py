from django.db import connection
from django.test import TestCase

from apps.marketplaces.models import Marketplace
from apps.marketplaces.tests.factories import make_marketplace


class EncryptedCredentialsTests(TestCase):
    def test_credentials_round_trip(self):
        marketplace = make_marketplace()
        reloaded = Marketplace.objects.get(pk=marketplace.pk)

        self.assertEqual(reloaded.client_id, "client-id")
        self.assertEqual(reloaded.client_secret, "client-secret")
        self.assertEqual(reloaded.refresh_token, "refresh-token")

    def test_secret_is_not_stored_in_plaintext(self):
        marketplace = make_marketplace()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT credentials FROM marketplaces_marketplace WHERE id = %s",
                [marketplace.pk],
            )
            stored = cursor.fetchone()[0]

        self.assertNotIn("client-secret", stored)
        self.assertNotIn("access-token", stored)
        self.assertTrue(stored.startswith("gAAAAA"))  # znacznik formatu Fernet

    def test_credentials_may_be_empty(self):
        marketplace = Marketplace.objects.create(name="Bez danych")

        reloaded = Marketplace.objects.get(pk=marketplace.pk)

        self.assertIsNone(reloaded.credentials)
        self.assertFalse(reloaded.has_credentials())
        self.assertFalse(reloaded.is_connected())
