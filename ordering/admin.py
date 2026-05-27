from django.contrib import admin

from .models import OrderList, OrderListItem, PurchaseItem


@admin.register(PurchaseItem)
class PurchaseItemAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "category", "default_unit", "is_active")
    list_filter = ("team", "category", "is_active")
    search_fields = ("name", "category")


class OrderListItemInline(admin.TabularInline):
    model = OrderListItem
    extra = 0


@admin.register(OrderList)
class OrderListAdmin(admin.ModelAdmin):
    list_display = ("order_date", "team", "state", "created_by", "finalized_by")
    list_filter = ("team", "state")
    search_fields = ("team__name",)
    inlines = [OrderListItemInline]

