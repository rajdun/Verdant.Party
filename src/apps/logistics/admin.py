from django.contrib import admin

from apps.logistics.models import FulfillmentBatch, FulfillmentOrder


class FulfillmentOrderInline(admin.TabularInline):
    model = FulfillmentOrder
    extra = 0
    fields = ("position", "order", "is_packed", "packed_at")
    readonly_fields = ("packed_at",)
    autocomplete_fields = ()


@admin.register(FulfillmentBatch)
class FulfillmentBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "created_by", "created_at", "finished_at")
    list_filter = ("status",)
    search_fields = ("note", "items__order__external_order_id")
    readonly_fields = ("created_at", "updated_at", "finished_at")
    inlines = [FulfillmentOrderInline]
