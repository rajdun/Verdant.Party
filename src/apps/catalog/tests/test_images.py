import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from apps.catalog.models import Product, ProductImage
from apps.catalog.utils import make_thumbnail

MEDIA_ROOT_OVERRIDE = "/tmp/verdant_party_test_media"


def make_test_image_bytes(color="red", size=(800, 600), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format=fmt)
    buffer.seek(0)
    return buffer.read()


def make_product(**overrides):
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


@override_settings(MEDIA_ROOT=MEDIA_ROOT_OVERRIDE)
class ThumbnailGenerationTests(TestCase):
    def setUp(self):
        self.product = make_product()

    def _upload(self, name="photo.png", color="red"):
        return SimpleUploadedFile(name, make_test_image_bytes(color=color), content_type="image/png")

    def test_thumbnail_generated_on_upload(self):
        image = ProductImage.objects.create(product=self.product, image=self._upload())
        self.assertTrue(image.thumbnail)
        with Image.open(image.thumbnail) as thumb:
            self.assertLessEqual(thumb.width, 400)
            self.assertLessEqual(thumb.height, 400)

    def test_thumbnail_not_regenerated_when_unrelated_field_changes(self):
        image = ProductImage.objects.create(product=self.product, image=self._upload())
        original_thumbnail_name = image.thumbnail.name

        image.alt_text = "updated alt text"
        image.save()

        self.assertEqual(image.thumbnail.name, original_thumbnail_name)

    def test_thumbnail_regenerated_when_image_replaced(self):
        image = ProductImage.objects.create(product=self.product, image=self._upload(name="first.png"))
        original_thumbnail_name = image.thumbnail.name

        image.image = self._upload(name="second.png", color="blue")
        image.save()

        self.assertNotEqual(image.thumbnail.name, original_thumbnail_name)

    def test_setting_is_primary_unsets_other_images_on_same_product(self):
        first = ProductImage.objects.create(product=self.product, image=self._upload(name="a.png"), is_primary=True)
        second = ProductImage.objects.create(product=self.product, image=self._upload(name="b.png"), is_primary=True)

        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_primary)
        self.assertTrue(second.is_primary)

    def test_is_primary_scoped_per_product(self):
        other_product = make_product(sku="plant-2", name="Monstera")

        image_a = ProductImage.objects.create(product=self.product, image=self._upload(name="a.png"), is_primary=True)
        image_b = ProductImage.objects.create(product=other_product, image=self._upload(name="b.png"), is_primary=True)

        image_a.refresh_from_db()
        image_b.refresh_from_db()
        self.assertTrue(image_a.is_primary)
        self.assertTrue(image_b.is_primary)


class MakeThumbnailUtilTests(TestCase):
    def test_returns_none_for_invalid_image_data(self):
        garbage = SimpleUploadedFile("not-an-image.png", b"not actually image bytes", content_type="image/png")
        self.assertIsNone(make_thumbnail(garbage))
