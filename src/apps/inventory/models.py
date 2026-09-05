from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.common.models import TimeStampedModel


class Location(TimeStampedModel):
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=50, blank=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Lokalizacja"
        verbose_name_plural = "Lokalizacje"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.name:
            self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "Pole Nazwa jest wymagane."})

    def save(self, *args, **kwargs):
        if self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)


class StockBatch(TimeStampedModel):
    """Przyjęcie magazynowe — jednocześnie partia kosztowa.

    Stan magazynowy to suma `quantity_remaining` partii; koszt wydania zdejmowany
    jest z partii metodą FIFO (`consume_fifo`), dzięki czemu znany jest dokładny
    koszt zakupu wydanego towaru.
    """

    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="stock_batches"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="stock_batches"
    )
    quantity_received = models.PositiveIntegerField()
    quantity_remaining = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2)
    received_at = models.DateField(default=timezone.localdate)
    supplier_name = models.CharField(max_length=200, blank=True)
    document_reference = models.CharField(max_length=100, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["received_at", "id"]
        verbose_name = "Przyjęcie magazynowe"
        verbose_name_plural = "Przyjęcia magazynowe"
        indexes = [
            models.Index(fields=["product", "location"], name="inventory_batch_prod_loc_idx"),
        ]

    def __str__(self):
        return f"{self.product.sku} @ {self.location.name}: {self.quantity_remaining}/{self.quantity_received}"

    @property
    def total_cost(self):
        return self.quantity_received * self.unit_cost

    @property
    def remaining_value(self):
        return self.quantity_remaining * self.unit_cost

    @property
    def is_locked(self):
        """Partia ruszona — coś z niej zeszło (wydanie FIFO lub częściowe
        przeniesienie). Nie edytujemy jej ani nie usuwamy, żeby nie zmieniać
        wstecznie kosztu wydanego towaru — zostaje tylko zmiana lokalizacji."""
        return self.quantity_remaining < self.quantity_received

    def clean(self):
        super().clean()
        errors = {}

        if self.quantity_received is not None and self.quantity_received <= 0:
            errors["quantity_received"] = "Przyjęta ilość musi być większa od 0."
        if self.unit_cost is not None and self.unit_cost < 0:
            errors["unit_cost"] = "Cena zakupu nie może być ujemna."
        if (
            self.quantity_remaining is not None
            and self.quantity_received is not None
            and self.quantity_remaining > self.quantity_received
        ):
            errors["quantity_remaining"] = "Ilość pozostała nie może przekraczać przyjętej."

        if errors:
            raise ValidationError(errors)

    @classmethod
    def consume_fifo(cls, product, quantity, location=None):
        """Zdejmuje `quantity` sztuk towaru z partii metodą FIFO.

        Zwraca (rozbicie, koszt_łączny), gdzie rozbicie to lista słowników
        {"batch", "quantity", "unit_cost", "cost"} — dokładny koszt zakupu
        wydanego towaru. Rzuca ValidationError gdy stan jest niewystarczający.
        """
        if quantity <= 0:
            raise ValidationError("Ilość do wydania musi być większa od 0.")

        with transaction.atomic():
            batches = cls.objects.select_for_update().filter(
                product=product, quantity_remaining__gt=0
            )
            if location is not None:
                batches = batches.filter(location=location)

            available = sum(batch.quantity_remaining for batch in batches)
            if available < quantity:
                raise ValidationError(
                    f"Niewystarczający stan magazynowy — dostępne: {available}, wymagane: {quantity}."
                )

            breakdown = []
            total_cost = Decimal("0")
            left = quantity

            for batch in batches:
                if left == 0:
                    break
                taken = min(batch.quantity_remaining, left)
                batch.quantity_remaining -= taken
                batch.save(update_fields=["quantity_remaining", "updated_at"])
                cost = taken * batch.unit_cost
                breakdown.append(
                    {
                        "batch": batch,
                        "quantity": taken,
                        "unit_cost": batch.unit_cost,
                        "cost": cost,
                    }
                )
                total_cost += cost
                left -= taken

        return breakdown, total_cost
