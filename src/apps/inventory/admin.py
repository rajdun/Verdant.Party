from django.contrib import admin

from apps.inventory.models import Location, StockBatch


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "description")
    readonly_fields = ("created_at", "updated_at")


@admin.register(StockBatch)
class StockBatchAdmin(admin.ModelAdmin):
    list_display = (
        "received_at",
        "product",
        "location",
        "quantity_received",
        "quantity_remaining",
        "unit_cost",
    )
    list_filter = ("location", "received_at")
    search_fields = ("product__sku", "product__name", "document_reference", "supplier_name", "note")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("product", "location", "received_at")}),
        ("Ilość i koszt", {"fields": ("quantity_received", "quantity_remaining", "unit_cost")}),
        ("Źródło", {"fields": ("supplier_name", "document_reference", "note")}),
        ("Znaczniki czasu", {"fields": ("created_at", "updated_at")}),
    )
