from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import Product

User = get_user_model()


class ProductAdminTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password123"
        )
        self.client.force_login(self.superuser)

    def test_product_admin_changelist_loads(self):
        Product.objects.create(
            sku="PLANT-1",
            name="Ficus",
            item_type=Product.ItemType.MERCHANDISE,
            species="Ficus lyrata",
            latin_name="Ficus lyrata",
            genus="Ficus",
            variety="Lyrata",
            pot_size="12cm",
            low_stock_threshold=5,
        )
        response = self.client.get(reverse("admin:catalog_product_changelist"))
        self.assertEqual(response.status_code, 200)
