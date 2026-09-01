from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify

from apps.common.models import TimeStampedModel


class Product(TimeStampedModel):
    class ItemType(models.TextChoices):
        MERCHANDISE = "MERCHANDISE", "Towar (roślina)"
        CONSUMABLE = "CONSUMABLE", "Materiał eksploatacyjny"

    class DimensionUnit(models.TextChoices):
        CENTIMETERS = "CM", "Centymetry (cm)"
        METERS = "M", "Metry (m)"

    class MaterialUnit(models.TextChoices):
        PIECES = "PIECES", "Sztuka (szt.)"
        METERS = "METERS", "Metr (m)"

    sku = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    item_type = models.CharField(max_length=20, choices=ItemType.choices, default=ItemType.MERCHANDISE)
    is_active = models.BooleanField(default=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # Plant specifics — required when item_type == MERCHANDISE
    species = models.CharField(max_length=200, blank=True)
    latin_name = models.CharField(max_length=200, blank=True)
    genus = models.CharField(max_length=200, blank=True)
    variety = models.CharField(max_length=200, blank=True)
    pot_size = models.CharField(max_length=200, blank=True)
    low_stock_threshold = models.PositiveIntegerField(null=True, blank=True)

    # Material specifics — required when item_type == CONSUMABLE
    length = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    width = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    height = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    dimension_unit = models.CharField(max_length=2, choices=DimensionUnit.choices, blank=True)
    material_unit = models.CharField(max_length=10, choices=MaterialUnit.choices, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Produkt"
        verbose_name_plural = "Produkty"
        constraints = [
            models.UniqueConstraint(fields=["sku"], name="catalog_product_sku_unique"),
        ]

    def __str__(self):
        return f"{self.sku} — {self.name}"

    def clean(self):
        super().clean()
        errors = {}

        if self.sku:
            self.sku = self.sku.strip().upper()
        if self.name:
            self.name = self.name.strip()

        field_labels = {
            "species": "Gatunek",
            "latin_name": "Nazwa łacińska",
            "genus": "Rodzaj",
            "variety": "Odmiana",
            "pot_size": "Rozmiar donicy",
            "length": "Długość",
            "width": "Szerokość",
            "height": "Wysokość",
            "dimension_unit": "Jednostka wymiaru",
            "material_unit": "Jednostka materiału",
        }

        if not self.sku:
            errors["sku"] = "Pole SKU jest wymagane."
        if not self.name:
            errors["name"] = "Pole Nazwa jest wymagane."

        if self.item_type == self.ItemType.MERCHANDISE:
            for field in ("species", "latin_name", "genus", "variety", "pot_size"):
                value = (getattr(self, field) or "").strip()
                setattr(self, field, value)
                if not value:
                    errors[field] = f"Pole {field_labels[field]} jest wymagane."
            if self.low_stock_threshold is None:
                errors["low_stock_threshold"] = "Próg niskiego stanu magazynowego jest wymagany."
            elif self.low_stock_threshold < 0:
                errors["low_stock_threshold"] = "Próg niskiego stanu musi być liczbą całkowitą ≥ 0."
            for field in ("length", "width", "height", "dimension_unit", "material_unit"):
                if getattr(self, field):
                    errors[field] = f"Pole {field_labels[field]} nie dotyczy towarów typu „Towar (roślina)”."
        elif self.item_type == self.ItemType.CONSUMABLE:
            for field in ("length", "width", "height"):
                value = getattr(self, field)
                if value is None or value <= 0:
                    errors[field] = f"{field_labels[field]} musi być liczbą większą od 0."
            if not self.dimension_unit:
                errors["dimension_unit"] = "Pole Jednostka wymiaru jest wymagane."
            if not self.material_unit:
                errors["material_unit"] = "Pole Jednostka materiału jest wymagane."
            for field in ("species", "latin_name", "genus", "variety", "pot_size"):
                if getattr(self, field):
                    errors[field] = f"Pole {field_labels[field]} nie dotyczy materiałów eksploatacyjnych."
            if self.low_stock_threshold is not None:
                errors["low_stock_threshold"] = "Próg niskiego stanu nie dotyczy materiałów eksploatacyjnych."
        else:
            errors["item_type"] = "Typ towaru musi być ustawiony na „Towar (roślina)” lub „Materiał eksploatacyjny”."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.sku:
            self.sku = self.sku.strip().upper()
        if not self.slug:
            base = slugify(f"{self.name}-{self.sku}")
            slug = base
            i = 1
            while Product.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                i += 1
                slug = f"{base}-{i}"
            self.slug = slug
        super().save(*args, **kwargs)


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="catalog/products/%Y/%m/")
    thumbnail = models.ImageField(
        upload_to="catalog/products/thumbnails/%Y/%m/", blank=True, editable=False
    )
    alt_text = models.CharField(max_length=200, blank=True)
    order = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Zdjęcie produktu"
        verbose_name_plural = "Zdjęcia produktu"

    def __str__(self):
        return f"Image #{self.pk} for {self.product.sku}"

    def save(self, *args, **kwargs):
        regenerate_thumbnail = self._image_changed()

        if self.is_primary:
            ProductImage.objects.filter(product_id=self.product_id, is_primary=True).exclude(
                pk=self.pk
            ).update(is_primary=False)

        super().save(*args, **kwargs)

        if regenerate_thumbnail and self.image:
            from apps.catalog.utils import make_thumbnail

            thumb_file = make_thumbnail(self.image, size=(400, 400))
            if thumb_file is not None:
                self.thumbnail.save(thumb_file.name, thumb_file, save=False)
                super().save(update_fields=["thumbnail"])

    def _image_changed(self):
        if not self.pk:
            return True
        try:
            old = ProductImage.objects.only("image").get(pk=self.pk)
        except ProductImage.DoesNotExist:
            return True
        return old.image.name != self.image.name
