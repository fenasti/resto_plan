from django.contrib import admin

from .models import OrderList, OrderListItem, PurchaseCategory, PurchaseItem, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "team")
    list_filter = ("team",)
    search_fields = ("name",)


@admin.register(PurchaseCategory)
class PurchaseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "team")
    list_filter = ("team",)
    search_fields = ("name",)


@admin.register(PurchaseItem)
class PurchaseItemAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "category", "supplier", "default_unit", "is_active")
    list_filter = ("team", "category", "supplier", "is_active")
    search_fields = ("name", "category__name", "supplier__name")


class OrderListItemInline(admin.TabularInline):
    model = OrderListItem
    extra = 0


@admin.register(OrderList)
class OrderListAdmin(admin.ModelAdmin):
    list_display = ("order_date", "team", "state", "created_by", "finalized_by")
    list_filter = ("team", "state")
    search_fields = ("team__name",)
    inlines = [OrderListItemInline]

