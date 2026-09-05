from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.crypto import EncryptedJSONField
from apps.common.models import TimeStampedModel

# Access token uznajemy za bezużyteczny, gdy zostało mniej niż tyle do wygaśnięcia —
# odpowiednik bufora 10 min z cache'a tokenów w specyfikacji.
TOKEN_EXPIRY_BUFFER = timedelta(minutes=10)

# Okno ważności parametru `state` w przepływie OAuth.
OAUTH_STATE_TTL = timedelta(minutes=15)


class MarketplaceType(models.TextChoices):
    ALLEGRO = "ALLEGRO", "Allegro"


class MarketplaceEnvironment(models.TextChoices):
    SANDBOX = "sandbox", "Sandbox"
    PRODUCTION = "production", "Produkcja"


class Marketplace(TimeStampedModel):
    """Integracja z jednym kontem sprzedawcy na marketplace.

    Dane dostępowe (client_secret, tokeny OAuth) trzymane są w jednej
    zaszyfrowanej kolumnie `credentials` — nigdy jawnym tekstem w bazie.
    """

    name = models.CharField(max_length=200, unique=True)
    type = models.CharField(
        max_length=20, choices=MarketplaceType.choices, default=MarketplaceType.ALLEGRO
    )
    environment = models.CharField(
        max_length=20,
        choices=MarketplaceEnvironment.choices,
        default=MarketplaceEnvironment.SANDBOX,
    )
    is_active = models.BooleanField(default=True)
    notification_email = models.EmailField(blank=True)

    credentials = EncryptedJSONField(null=True, blank=True)

    # Kursor strumienia zdarzeń zamówień — trwały, w bazie (nie w cache'u),
    # żeby czyszczenie cache'a nie powodowało ponownego importu od zera.
    last_event_id = models.CharField(max_length=100, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    oauth_state = models.CharField(max_length=64, blank=True)
    oauth_state_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Integracja marketplace"
        verbose_name_plural = "Integracje marketplace"
        indexes = [
            models.Index(fields=["type", "is_active"], name="marketplace_type_active_idx"),
        ]

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

    # --- konfiguracja adresów ---------------------------------------------

    @property
    def urls(self):
        return settings.ALLEGRO[self.environment]

    @property
    def base_url(self):
        return self.urls["base_url"]

    @property
    def api_base_url(self):
        return self.urls["api_base_url"]

    # --- dane dostępowe ----------------------------------------------------

    def _credentials(self):
        return self.credentials or {}

    @property
    def client_id(self):
        return self._credentials().get("client_id", "")

    @property
    def client_secret(self):
        return self._credentials().get("client_secret", "")

    @property
    def refresh_token(self):
        return self._credentials().get("refresh_token", "")

    @property
    def access_token_expires_at(self):
        raw = self._credentials().get("access_token_expires_at")
        return datetime.fromisoformat(raw) if raw else None

    @property
    def access_token(self):
        """Access token, o ile jest ważny jeszcze przez co najmniej 10 minut.

        Zwraca None gdy token wygasł lub zaraz wygaśnie — wywołujący ma wtedy
        wykonać refresh, zamiast wysyłać żądanie skazane na 401.
        """
        expires_at = self.access_token_expires_at
        if not expires_at or expires_at - TOKEN_EXPIRY_BUFFER <= timezone.now():
            return None
        return self._credentials().get("access_token") or None

    def has_credentials(self):
        return bool(self.client_id and self.client_secret)

    has_credentials.boolean = True
    has_credentials.short_description = "Dane dostępowe"

    def is_connected(self):
        expires_at = self.access_token_expires_at
        return bool(expires_at and expires_at > timezone.now())

    is_connected.boolean = True
    is_connected.short_description = "Połączona"

    def needs_token_refresh(self, within=timedelta(hours=2)):
        """Czy token wygasa w zadanym oknie (domyślnie 2 h — jak w specyfikacji)."""
        if not self.refresh_token:
            return False
        expires_at = self.access_token_expires_at
        return expires_at is None or expires_at <= timezone.now() + within

    def set_credentials(self, client_id, client_secret):
        credentials = self._credentials()
        credentials.update({"client_id": client_id, "client_secret": client_secret})
        self.credentials = credentials
        self.save(update_fields=["credentials", "updated_at"])

    def store_tokens(self, access_token, refresh_token, expires_in):
        """Zapisuje parę tokenów zwróconą przez Allegro.

        Allegro rotuje refresh token przy każdym odświeżeniu — zawsze
        nadpisujemy go nową wartością z odpowiedzi.
        """
        credentials = self._credentials()
        credentials.update(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "access_token_expires_at": (
                    timezone.now() + timedelta(seconds=int(expires_in))
                ).isoformat(),
            }
        )
        self.credentials = credentials
        self.save(update_fields=["credentials", "updated_at"])

    def clear_tokens(self):
        """Zrywa sesję, zostawiając client_id/secret — wymusza ponowny OAuth."""
        credentials = self._credentials()
        for key in ("access_token", "refresh_token", "access_token_expires_at"):
            credentials.pop(key, None)
        self.credentials = credentials
        self.save(update_fields=["credentials", "updated_at"])

    # --- OAuth state -------------------------------------------------------

    def start_oauth(self, state):
        self.oauth_state = state
        self.oauth_state_expires_at = timezone.now() + OAUTH_STATE_TTL
        self.save(update_fields=["oauth_state", "oauth_state_expires_at", "updated_at"])

    def consume_oauth_state(self, state):
        """Weryfikuje state i kasuje go niezależnie od wyniku (jednorazowy użytek)."""
        expected = self.oauth_state
        expires_at = self.oauth_state_expires_at

        self.oauth_state = ""
        self.oauth_state_expires_at = None
        self.save(update_fields=["oauth_state", "oauth_state_expires_at", "updated_at"])

        if not expected or not state or expected != state:
            raise ValidationError("Nieprawidłowy parametr state — przerwij i spróbuj ponownie.")
        if not expires_at or expires_at <= timezone.now():
            raise ValidationError("Sesja autoryzacji wygasła — rozpocznij łączenie od nowa.")

    @property
    def notification_recipient(self):
        return self.notification_email or settings.ADMIN_NOTIFICATION_EMAIL


class ListingStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Aktywna"
    ENDED = "ENDED", "Zakończona"


class MarketplaceListing(TimeStampedModel):
    """Mapowanie oferty na marketplace → produkt w katalogu.

    Kopia oferty jest tylko do odczytu (nie publikujemy nic na Allegro).
    Bez tego mapowania pozycja zamówienia nie da się powiązać z towarem.
    """

    marketplace = models.ForeignKey(
        Marketplace, on_delete=models.PROTECT, related_name="listings"
    )
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="marketplace_listings"
    )
    external_id = models.CharField(max_length=50)
    title = models.CharField(max_length=200)
    picture_url = models.URLField(max_length=500, blank=True)
    current_price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="PLN")
    status = models.CharField(
        max_length=20, choices=ListingStatus.choices, default=ListingStatus.ACTIVE
    )

    class Meta:
        ordering = ["title"]
        verbose_name = "Mapowanie oferty"
        verbose_name_plural = "Mapowania ofert"
        constraints = [
            models.UniqueConstraint(
                fields=["marketplace", "external_id"], name="marketplace_listing_unique_offer"
            ),
        ]
        indexes = [
            models.Index(fields=["product"], name="marketplace_listing_prod_idx"),
        ]

    def __str__(self):
        return f"{self.external_id} → {self.product.sku}"

    def update_price(self, amount, currency=None):
        self.current_price = amount
        if currency:
            self.currency = currency
        self.save(update_fields=["current_price", "currency", "updated_at"])

    def reassign_product(self, product):
        self.product = product
        self.save(update_fields=["product", "updated_at"])

    def mark_ended(self):
        self.status = ListingStatus.ENDED
        self.save(update_fields=["status", "updated_at"])

    def reactivate(self):
        self.status = ListingStatus.ACTIVE
        self.save(update_fields=["status", "updated_at"])


class SyncKind(models.TextChoices):
    EVENTS = "EVENTS", "Import zamówień"
    TOKEN_REFRESH = "TOKEN_REFRESH", "Odświeżenie tokenu"


class SyncStatus(models.TextChoices):
    OK = "OK", "Zakończona"
    PARTIAL = "PARTIAL", "Częściowa"
    FAILED = "FAILED", "Błąd"


class SyncRun(TimeStampedModel):
    """Log pojedynczego przebiegu synchronizacji — źródło diagnostyki w UI."""

    marketplace = models.ForeignKey(
        Marketplace, on_delete=models.CASCADE, related_name="sync_runs"
    )
    kind = models.CharField(max_length=20, choices=SyncKind.choices)
    status = models.CharField(max_length=10, choices=SyncStatus.choices, default=SyncStatus.OK)
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    events_seen = models.PositiveIntegerField(default=0)
    orders_imported = models.PositiveIntegerField(default=0)
    orders_skipped = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        verbose_name = "Przebieg synchronizacji"
        verbose_name_plural = "Przebiegi synchronizacji"
        indexes = [
            models.Index(fields=["marketplace", "-started_at"], name="marketplace_sync_run_idx"),
        ]

    def __str__(self):
        return f"{self.marketplace.name} · {self.get_kind_display()} · {self.get_status_display()}"

    @property
    def duration_seconds(self):
        if not self.finished_at:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def finish(self, status, message=""):
        self.status = status
        self.message = message
        self.finished_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "message",
                "finished_at",
                "events_seen",
                "orders_imported",
                "orders_skipped",
                "updated_at",
            ]
        )
