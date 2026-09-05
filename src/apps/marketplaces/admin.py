from django.contrib import admin

from apps.marketplaces.models import Marketplace, MarketplaceListing, SyncRun


@admin.register(Marketplace)
class MarketplaceAdmin(admin.ModelAdmin):
    # Kolumna `credentials` świadomie nie jest pokazywana — zawiera sekrety.
    list_display = (
        "name",
        "type",
        "environment",
        "is_active",
        "has_credentials",
        "is_connected",
        "last_synced_at",
    )
    list_filter = ("type", "environment", "is_active")
    search_fields = ("name", "notification_email")
    readonly_fields = ("last_event_id", "last_synced_at", "created_at", "updated_at")
    exclude = ("credentials", "oauth_state", "oauth_state_expires_at")
    fieldsets = (
        (None, {"fields": ("name", "type", "environment", "is_active")}),
        ("Powiadomienia", {"fields": ("notification_email",)}),
        (
            "Stan synchronizacji",
            {
                "fields": ("last_event_id", "last_synced_at"),
                "description": "Dane dostępowe ustawia się w aplikacji, nie w panelu admina.",
            },
        ),
        ("Znaczniki czasu", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(MarketplaceListing)
class MarketplaceListingAdmin(admin.ModelAdmin):
    list_display = ("external_id", "title", "product", "marketplace", "current_price", "status")
    list_filter = ("marketplace", "status")
    search_fields = ("external_id", "title", "product__sku", "product__name")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("product",)
    fieldsets = (
        (None, {"fields": ("marketplace", "external_id", "product")}),
        ("Dane oferty", {"fields": ("title", "picture_url", "current_price", "currency", "status")}),
        ("Znaczniki czasu", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = (
        "started_at",
        "marketplace",
        "kind",
        "status",
        "events_seen",
        "orders_imported",
        "orders_skipped",
    )
    list_filter = ("marketplace", "kind", "status")
    search_fields = ("message",)
    readonly_fields = (
        "marketplace",
        "kind",
        "status",
        "started_at",
        "finished_at",
        "events_seen",
        "orders_imported",
        "orders_skipped",
        "message",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        # Wpisy powstają wyłącznie w trakcie synchronizacji.
        return False
