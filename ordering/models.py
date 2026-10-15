from django.conf import settings
from django.db import models

from accounts.models import Team


class Supplier(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="suppliers")
    name = models.CharField(max_length=150)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="uniq_team_supplier_name")
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class PurchaseCategory(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="purchase_categories")
    name = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="uniq_team_purchase_category_name")
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class PurchaseItem(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="purchase_items")
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        PurchaseCategory, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_items"
    )
    supplier = models.ForeignKey(
        Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="purchase_items",
        help_text="Who you buy this from — lets an order be split and exported per supplier.",
    )
    default_unit = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="uniq_team_purchase_item_name")
        ]
        indexes = [
            models.Index(fields=["team", "is_active"], name="idx_purchaseitem_team_active"),
        ]
        ordering = ["category", "sort_order", "name", "id"]

    @property
    def display_category(self) -> str:
        return self.category.name if self.category else "Other"

    @property
    def display_supplier(self) -> str:
        return self.supplier.name if self.supplier else "No Supplier Set"

    def __str__(self):
        return f"{self.name} ({self.team.name})"


class OrderList(models.Model):
    class OrderState(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        FINALIZED = "FINALIZED", "Finalized"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="order_lists")
    order_date = models.DateField()
    state = models.CharField(max_length=20, choices=OrderState.choices, default=OrderState.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="order_lists_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="order_lists_finalized",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "order_date"], name="uniq_team_order_date")
        ]
        ordering = ["-order_date"]

    @property
    def item_count(self) -> int:
        if hasattr(self, "item_count_annotated"):
            return self.item_count_annotated
        return self.items.count()

    def __str__(self):
        return f"{self.team.name} {self.order_date} ({self.state})"


class OrderListItem(models.Model):
    order_list = models.ForeignKey(OrderList, on_delete=models.CASCADE, related_name="items")
    purchase_item = models.ForeignKey(PurchaseItem, on_delete=models.PROTECT, related_name="order_items")
    quantity_text = models.CharField(max_length=120, blank=True)
    note = models.CharField(max_length=200, blank=True)
    sort_order = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["order_list", "purchase_item"],
                name="uniq_order_list_purchase_item",
            )
        ]
        ordering = ["sort_order", "id"]

    def __str__(self):
        return f"{self.order_list.order_date}: {self.purchase_item.name}"

