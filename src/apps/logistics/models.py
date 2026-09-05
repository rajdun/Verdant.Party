"""Realizacja zamówień — fale zbierania i pakowania.

Fala (`FulfillmentBatch`) to paczka robocza: operator zaznacza zamówienia,
zbiera towar z jednej zsumowanej listy, a potem pakuje je jedno po drugim.
Stan pakowania trzymamy w bazie, a nie w sesji, żeby przeżył odświeżenie
strony i był widoczny dla całego zespołu.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import TimeStampedModel


class FulfillmentBatchStatus(models.TextChoices):
    OPEN = "OPEN", "Otwarta"
    DONE = "DONE", "Zakończona"
    CANCELLED = "CANCELLED", "Anulowana"


class FulfillmentBatch(TimeStampedModel):
    """Fala realizacji — zbiór zamówień obsługiwanych za jednym podejściem."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fulfillment_batches",
    )
    status = models.CharField(
        max_length=20,
        choices=FulfillmentBatchStatus.choices,
        default=FulfillmentBatchStatus.OPEN,
    )
    note = models.CharField(max_length=255, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Fala realizacji"
        verbose_name_plural = "Fale realizacji"
        indexes = [
            models.Index(fields=["status"], name="logistics_batch_status_idx"),
        ]

    def __str__(self):
        return f"Fala #{self.pk} ({self.get_status_display()})"

    @property
    def is_open(self):
        return self.status == FulfillmentBatchStatus.OPEN

    @property
    def total_orders(self):
        return self.items.count()

    @property
    def packed_orders(self):
        return self.items.filter(is_packed=True).count()

    @property
    def is_complete(self):
        """Wszystko spakowane. Pusta fala nie jest kompletna — nie ma czego pakować."""
        total = self.total_orders
        return total > 0 and self.packed_orders == total

    def finish(self):
        if self.status == FulfillmentBatchStatus.DONE:
            return  # idempotentne
        if self.status != FulfillmentBatchStatus.OPEN:
            raise ValidationError("Zakończyć można tylko otwartą falę.")
        self.status = FulfillmentBatchStatus.DONE
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at", "updated_at"])

    def cancel(self):
        if self.status == FulfillmentBatchStatus.CANCELLED:
            return
        if self.status != FulfillmentBatchStatus.OPEN:
            raise ValidationError("Anulować można tylko otwartą falę.")
        if self.items.filter(is_packed=True).exists():
            raise ValidationError(
                "Nie można anulować fali, w której są już spakowane zamówienia."
            )
        self.status = FulfillmentBatchStatus.CANCELLED
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "finished_at", "updated_at"])


class FulfillmentOrder(TimeStampedModel):
    """Zamówienie w fali wraz z postępem pakowania.

    `order` jest chronione `PROTECT` — zamówienie, które przeszło przez falę,
    nie może zniknąć bez śladu, bo to ono zdjęło stan magazynowy.
    """

    batch = models.ForeignKey(
        FulfillmentBatch, on_delete=models.CASCADE, related_name="items"
    )
    order = models.ForeignKey(
        "orders.Order", on_delete=models.PROTECT, related_name="fulfillment_items"
    )
    position = models.PositiveIntegerField(default=0)
    is_packed = models.BooleanField(default=False)
    packed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Zamówienie w fali"
        verbose_name_plural = "Zamówienia w fali"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "order"], name="logistics_batch_order_unique"
            ),
        ]

    def __str__(self):
        return f"{self.order.external_order_id} w fali #{self.batch_id}"

    def mark_packed(self):
        if self.is_packed:
            return  # idempotentne
        self.is_packed = True
        self.packed_at = timezone.now()
        self.save(update_fields=["is_packed", "packed_at", "updated_at"])
