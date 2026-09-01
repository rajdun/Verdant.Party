import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from apps.catalog.models import Product, ProductImage

MEDIA_ROOT_OVERRIDE = "/tmp/verdant_party_test_media_views"


def make_test_image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (200, 200), color="green").save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()


def make_merchandise(**overrides):
    defaults = dict(
        sku="plant-1",
        name="Ficus",
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


class ProductListViewTests(TestCase):
    def test_list_returns_200(self):
        make_merchandise()
        response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(response.status_code, 200)

    def test_pagination(self):
        for i in range(30):
            make_merchandise(sku=f"plant-{i}", name=f"Plant {i}")
        response = self.client.get(reverse("catalog:product_list"))
        self.assertTrue(response.context["is_paginated"])
        self.assertEqual(len(response.context["products"]), 24)

    def test_free_text_query_filters_by_name_or_sku_or_latin_name(self):
        make_merchandise(sku="plant-1", name="Ficus", latin_name="Ficus lyrata")
        make_merchandise(sku="plant-2", name="Monstera", latin_name="Monstera deliciosa")

        response = self.client.get(reverse("catalog:product_list"), {"q": "Monstera"})
        products = list(response.context["products"])
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].sku, "PLANT-2")

    def test_field_filter_contains(self):
        make_merchandise(sku="plant-1", name="Ficus")
        make_merchandise(sku="plant-2", name="Monstera")

        response = self.client.get(reverse("catalog:product_list"), {"name__contains": "fic"})
        products = list(response.context["products"])
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].name, "Ficus")

    def test_field_filter_exact(self):
        make_merchandise(sku="plant-1", name="Ficus")
        make_merchandise(sku="plant-2", name="Monstera")

        response = self.client.get(reverse("catalog:product_list"), {"sku": "PLANT-1"})
        products = list(response.context["products"])
        self.assertEqual(len(products), 1)

    def test_field_filter_in(self):
        make_merchandise(sku="plant-1", name="Ficus")
        make_merchandise(sku="plant-2", name="Monstera")
        make_merchandise(sku="plant-3", name="Aloe")

        response = self.client.get(reverse("catalog:product_list"), {"sku__in": "PLANT-1,PLANT-3"})
        products = {p.sku for p in response.context["products"]}
        self.assertEqual(products, {"PLANT-1", "PLANT-3"})

    def test_is_active_filter(self):
        make_merchandise(sku="plant-1", name="Ficus", is_active=True)
        make_merchandise(sku="plant-2", name="Monstera", is_active=False)

        response = self.client.get(reverse("catalog:product_list"), {"is_active": "false"})
        products = list(response.context["products"])
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0].sku, "PLANT-2")

    def test_sort_whitelist_falls_back_for_disallowed_field(self):
        make_merchandise(sku="plant-2", name="B Plant")
        make_merchandise(sku="plant-1", name="A Plant")

        response = self.client.get(reverse("catalog:product_list"), {"sort": "created_at"})
        products = list(response.context["products"])
        # Falls back to Meta.ordering = ["name"], not an error response.
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p.name for p in products], ["A Plant", "B Plant"])


class ProductDetailViewTests(TestCase):
    def test_detail_by_slug_returns_200(self):
        product = make_merchandise()
        response = self.client.get(reverse("catalog:product_detail", args=[product.slug]))
        self.assertEqual(response.status_code, 200)

    def test_detail_404_for_unknown_slug(self):
        response = self.client.get(reverse("catalog:product_detail", args=["does-not-exist"]))
        self.assertEqual(response.status_code, 404)


class ProductCreateUpdateDeleteViewTests(TestCase):
    def _valid_merchandise_payload(self, **overrides):
        payload = {
            "sku": "plant-1",
            "name": "Ficus",
            "item_type": Product.ItemType.MERCHANDISE,
            "is_active": "on",
            "species": "Ficus lyrata",
            "latin_name": "Ficus lyrata",
            "genus": "Ficus",
            "variety": "Lyrata",
            "pot_size": "12cm",
            "low_stock_threshold": 5,
        }
        payload.update(overrides)
        return payload

    def test_create_view_post_valid_creates_product_and_redirects_to_detail(self):
        response = self.client.post(reverse("catalog:product_create"), self._valid_merchandise_payload())
        product = Product.objects.get(sku="PLANT-1")
        self.assertRedirects(response, reverse("catalog:product_detail", args=[product.slug]))

    def test_create_view_post_invalid_shows_form_errors(self):
        payload = self._valid_merchandise_payload(species="")
        response = self.client.post(reverse("catalog:product_create"), payload)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "species", "Pole Gatunek jest wymagane.")
        self.assertFalse(Product.objects.exists())

    def test_update_view_changes_persist(self):
        product = make_merchandise()
        payload = self._valid_merchandise_payload(name="Ficus Updated")
        response = self.client.post(reverse("catalog:product_update", args=[product.slug]), payload)
        product.refresh_from_db()
        self.assertEqual(product.name, "Ficus Updated")
        self.assertRedirects(response, reverse("catalog:product_detail", args=[product.slug]))

    def test_delete_view_removes_product_and_redirects_to_list(self):
        product = make_merchandise()
        response = self.client.post(reverse("catalog:product_delete", args=[product.slug]))
        self.assertRedirects(response, reverse("catalog:product_list"))
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())


class ProductActivateDeactivateViewTests(TestCase):
    def test_deactivate_requires_post(self):
        product = make_merchandise(is_active=True)
        response = self.client.get(reverse("catalog:product_deactivate", args=[product.slug]))
        self.assertEqual(response.status_code, 405)
        product.refresh_from_db()
        self.assertTrue(product.is_active)

    def test_deactivate_via_post_flips_flag(self):
        product = make_merchandise(is_active=True)
        response = self.client.post(reverse("catalog:product_deactivate", args=[product.slug]))
        product.refresh_from_db()
        self.assertFalse(product.is_active)
        self.assertRedirects(response, reverse("catalog:product_detail", args=[product.slug]))

    def test_activate_via_post_flips_flag(self):
        product = make_merchandise(is_active=False)
        response = self.client.post(reverse("catalog:product_activate", args=[product.slug]))
        product.refresh_from_db()
        self.assertTrue(product.is_active)


@override_settings(MEDIA_ROOT=MEDIA_ROOT_OVERRIDE)
class ProductImageViewTests(TestCase):
    def setUp(self):
        self.product = make_merchandise()

    def _upload(self, name="photo.png"):
        return SimpleUploadedFile(name, make_test_image_bytes(), content_type="image/png")

    def test_image_add_creates_image_and_sets_default_order(self):
        response = self.client.post(
            reverse("catalog:product_image_add", args=[self.product.slug]),
            {"image": self._upload(), "alt_text": "A ficus", "is_primary": "on"},
        )
        self.assertRedirects(response, reverse("catalog:product_detail", args=[self.product.slug]))
        image = ProductImage.objects.get(product=self.product)
        self.assertEqual(image.order, 0)

    def test_image_delete_removes_image(self):
        image = ProductImage.objects.create(product=self.product, image=self._upload())
        response = self.client.post(reverse("catalog:product_image_delete", args=[image.pk]))
        self.assertRedirects(response, reverse("catalog:product_detail", args=[self.product.slug]))
        self.assertFalse(ProductImage.objects.filter(pk=image.pk).exists())

    def test_image_set_primary_via_post(self):
        first = ProductImage.objects.create(product=self.product, image=self._upload(name="a.png"), is_primary=True)
        second = ProductImage.objects.create(product=self.product, image=self._upload(name="b.png"))

        self.client.post(reverse("catalog:product_image_set_primary", args=[second.pk]))

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)

    def test_image_reorder_updates_order_field(self):
        first = ProductImage.objects.create(product=self.product, image=self._upload(name="a.png"), order=0)
        second = ProductImage.objects.create(product=self.product, image=self._upload(name="b.png"), order=1)

        self.client.post(
            reverse("catalog:product_image_reorder", args=[self.product.slug]),
            {"image_id": [second.pk, first.pk]},
        )

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(second.order, 0)
        self.assertEqual(first.order, 1)
