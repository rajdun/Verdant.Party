from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.common.models import TimeStampedModel


class OrderStatus(models.TextChoices):
    NEW = "NEW", "Nowe"
    IN_FULFILLMENT = "IN_FULFILLMENT", "W realizacji"
    SHIPPED = "SHIPPED", "Wysłane"
    CANCELLED = "CANCELLED", "Anulowane"


class ShippingCostSource(models.TextChoices):
    MANUAL = "MANUAL", "Wpisany ręcznie"
    ALLEGRO = "ALLEGRO", "Pobrany z Allegro"


class Order(TimeStampedModel):
    """Zamówienie zaimportowane z marketplace'u.

    `external_order_id` jest kluczem idempotencji importu — ten sam identyfikator
    z Allegro nigdy nie utworzy drugiego wiersza, bo strumień zdarzeń zamówień
    potrafi zwrócić to samo zamówienie wielokrotnie.

    Kwoty pochodzą z dwóch momentów:

    * import z Allegro — `total_to_pay`, `delivery_cost`, `platform_commission`,
    * pakowanie (`logistics.views.order_pack_confirm`) — `total_cogs`,
      `shipping_cost`, `shipping_cost_source`.

    Do marży wchodzi `total_to_pay` po stronie wpływów i `total_costs` po stronie
    kosztów — patrz `gross_profit`.
    """

    external_order_id = models.CharField(max_length=100, unique=True)
    marketplace = models.ForeignKey(
        "marketplaces.Marketplace", on_delete=models.PROTECT, related_name="orders"
    )
    status = models.CharField(
        max_length=20, choices=OrderStatus.choices, default=OrderStatus.NEW
    )
    external_status = models.CharField(max_length=50, blank=True)

    # Kupujący
    buyer_login = models.CharField(max_length=100, blank=True)
    buyer_full_name = models.CharField(max_length=200, blank=True)
    buyer_email = models.EmailField(blank=True)
    buyer_phone = models.CharField(max_length=30, blank=True)
    buyer_address = models.CharField(max_length=300, blank=True)
    buyer_city = models.CharField(max_length=100, blank=True)
    buyer_postal_code = models.CharField(max_length=20, blank=True)
    buyer_country = models.CharField(max_length=50, blank=True)

    # Dostawa
    delivery_recipient_name = models.CharField(max_length=200, blank=True)
    delivery_street = models.CharField(max_length=300, blank=True)
    delivery_city = models.CharField(max_length=100, blank=True)
    delivery_postal_code = models.CharField(max_length=20, blank=True)
    delivery_country_code = models.CharField(max_length=10, blank=True)
    delivery_phone = models.CharField(max_length=30, blank=True)
    delivery_company_name = models.CharField(max_length=200, blank=True)
    delivery_method_name = models.CharField(max_length=100, blank=True)
    delivery_pickup_point_id = models.CharField(max_length=100, blank=True)
    delivery_pickup_point_name = models.CharField(max_length=200, blank=True)
    # Wpływ, nie koszt: tyle za dostawę zapłacił kupujący (nazwa pola jest z Allegro).
    # Zawiera się już w `total_to_pay`, więc do marży nie dodaje się go osobno.
    delivery_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))

    # Kwoty
    currency = models.CharField(max_length=3, default="PLN")
    total_to_pay = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_cogs = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    platform_commission = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    # Koszt nadania paczki poniesiony przez sprzedawcę — wypełniany przy pakowaniu.
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    shipping_cost_source = models.CharField(
        max_length=10, choices=ShippingCostSource.choices, blank=True
    )

    placed_at = models.DateTimeField(null=True, blank=True)
    message_to_seller = models.TextField(blank=True)

    class Meta:
        ordering = ["-placed_at", "-id"]
        verbose_name = "Zamówienie"
        verbose_name_plural = "Zamówienia"
        indexes = [
            models.Index(fields=["marketplace", "status"], name="orders_marketplace_status_idx"),
            models.Index(fields=["-placed_at"], name="orders_placed_at_idx"),
        ]

    def __str__(self):
        return f"{self.external_order_id} — {self.buyer_full_name or self.buyer_login}"

    @property
    def items_total(self):
        """Wartość samych pozycji, bez dostawy — kontrolna wobec `total_to_pay`."""
        return sum((line.total_price for line in self.lines.all()), Decimal("0"))

    @property
    def total_costs(self):
        return self.total_cogs + self.platform_commission + self.shipping_cost

    @property
    def gross_profit(self):
        """Wpływ od kupującego minus koszty własne.

        Przychodem jest `total_to_pay`, bo zawiera dostawę opłaconą przez
        kupującego — a po stronie kosztów stoi `shipping_cost`, czyli nadanie
        tej samej paczki. Liczenie marży od samych pozycji zaniżałoby ją
        o `delivery_cost`.
        """
        return self.total_to_pay - self.total_costs

    @property
    def has_unmapped_lines(self):
        return any(line.product_id is None for line in self.lines.all())

    @property
    def external_url(self):
        """Głęboki link do zamówienia w panelu sprzedawcy Allegro."""
        return (
            f"{self.marketplace.base_url}/moje-allegro/sprzedaz/zamowienia/"
            f"{self.external_order_id}"
        )

    def start_fulfillment(self):
        if self.status == OrderStatus.IN_FULFILLMENT:
            return  # idempotentne
        if self.status != OrderStatus.NEW:
            raise ValidationError("Do realizacji można przekazać tylko nowe zamówienie.")
        self.status = OrderStatus.IN_FULFILLMENT
        self.save(update_fields=["status", "updated_at"])

    def mark_shipped(self):
        if self.status == OrderStatus.SHIPPED:
            return
        if self.status != OrderStatus.IN_FULFILLMENT:
            raise ValidationError("Wysłać można tylko zamówienie w realizacji.")
        self.status = OrderStatus.SHIPPED
        self.save(update_fields=["status", "updated_at"])

    def cancel(self):
        if self.status == OrderStatus.CANCELLED:
            return
        if self.status == OrderStatus.SHIPPED:
            raise ValidationError("Nie można anulować wysłanego zamówienia.")
        self.status = OrderStatus.CANCELLED
        self.save(update_fields=["status", "updated_at"])


class OrderLine(TimeStampedModel):
    """Pozycja zamówienia.

    `product` bywa puste — oferta bez mapowania (`MarketplaceListing`) jest
    zapisywana z samą nazwą z marketplace'u, żeby zamówienie pozostało czytelne
    i dało się domapować później.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="order_lines",
        null=True,
        blank=True,
    )
    external_offer_id = models.CharField(max_length=50)
    external_offer_name = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]
        verbose_name = "Pozycja zamówienia"
        verbose_name_plural = "Pozycje zamówienia"
        indexes = [
            models.Index(fields=["external_offer_id"], name="orders_line_offer_idx"),
        ]

    def __str__(self):
        return f"{self.external_offer_name or self.external_offer_id} × {self.quantity}"

    @property
    def total_price(self):
        return self.unit_price * self.quantity

    def clean(self):
        super().clean()
        errors = {}
        if self.quantity is not None and self.quantity <= 0:
            errors["quantity"] = "Ilość musi być większa od 0."
        if self.unit_price is not None and self.unit_price < 0:
            errors["unit_price"] = "Cena nie może być ujemna."
        if errors:
            raise ValidationError(errors)
