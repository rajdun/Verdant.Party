from django.contrib import admin
from django.utils.html import format_html

from apps.catalog.models import Product, ProductImage


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    fields = ("image_preview", "image", "alt_text", "order", "is_primary")
    readonly_fields = ("image_preview",)

    def image_preview(self, obj):
        if obj.pk and obj.thumbnail:
            return format_html('<img src="{}" style="max-height:80px;">', obj.thumbnail.url)
        return "—"

    image_preview.short_description = "Podgląd"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductImageInline]
    list_display = ("sku", "name", "item_type", "is_active", "price", "updated_at")
    list_filter = ("item_type", "is_active", "dimension_unit", "material_unit")
    search_fields = ("sku", "name", "latin_name", "genus", "variety", "pot_size")
    readonly_fields = ("slug", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("sku", "name", "slug", "item_type", "is_active", "price")}),
        (
            "Szczegóły rośliny",
            {"fields": ("species", "latin_name", "genus", "variety", "pot_size", "low_stock_threshold")},
        ),
        ("Szczegóły materiału", {"fields": ("length", "width", "height", "dimension_unit", "material_unit")}),
        ("Znaczniki czasu", {"fields": ("created_at", "updated_at")}),
    )
