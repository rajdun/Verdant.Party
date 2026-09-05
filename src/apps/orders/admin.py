from django.contrib import admin

from apps.orders.models import Order, OrderLine


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0
    autocomplete_fields = ("product",)
    fields = ("external_offer_id", "external_offer_name", "product", "quantity", "unit_price")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "external_order_id",
        "placed_at",
        "marketplace",
        "buyer_full_name",
        "status",
        "total_to_pay",
        "platform_commission",
    )
    list_filter = ("marketplace", "status", "placed_at")
    search_fields = (
        "external_order_id",
        "buyer_full_name",
        "buyer_login",
        "buyer_email",
        "delivery_recipient_name",
    )
    readonly_fields = ("external_order_id", "marketplace", "created_at", "updated_at")
    inlines = [OrderLineInline]
    fieldsets = (
        (None, {"fields": ("external_order_id", "marketplace", "status", "external_status")}),
        (
            "Kupujący",
            {
                "fields": (
                    "buyer_full_name",
                    "buyer_login",
                    "buyer_email",
                    "buyer_phone",
                    "buyer_address",
                    "buyer_city",
                    "buyer_postal_code",
                    "buyer_country",
                )
            },
        ),
        (
            "Dostawa",
            {
                "fields": (
                    "delivery_recipient_name",
                    "delivery_company_name",
                    "delivery_street",
                    "delivery_city",
                    "delivery_postal_code",
                    "delivery_country_code",
                    "delivery_phone",
                    "delivery_method_name",
                    "delivery_pickup_point_id",
                    "delivery_pickup_point_name",
                    "delivery_cost",
                )
            },
        ),
        (
            "Kwoty",
            {
                "fields": (
                    "currency",
                    "total_to_pay",
                    "total_cogs",
                    "platform_commission",
                    "shipping_cost",
                    "shipping_cost_source",
                )
            },
        ),
        ("Pozostałe", {"fields": ("placed_at", "message_to_seller")}),
        ("Znaczniki czasu", {"fields": ("created_at", "updated_at")}),
    )
