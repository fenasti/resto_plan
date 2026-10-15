from django.contrib import admin

from .models import PlanDish, PrepPlan, PrepTask

# Registered for debugging a live tenant's prep lists without a Django
# shell (a stuck task, a bad plan state) — day-to-day use stays in-app.


@admin.register(PrepPlan)
class PrepPlanAdmin(admin.ModelAdmin):
    list_display = ("team", "service_date", "state", "created_by", "finalized_by", "completed_by")
    list_filter = ("team", "state")
    search_fields = ("team__name",)


@admin.register(PlanDish)
class PlanDishAdmin(admin.ModelAdmin):
    list_display = ("plan", "dish", "order")
    list_filter = ("plan__team",)
    search_fields = ("dish__name",)


@admin.register(PrepTask)
class PrepTaskAdmin(admin.ModelAdmin):
    list_display = ("plan", "status", "assignee", "dish_component", "component", "recipe", "manual_label")
    list_filter = ("plan__team", "status")
    search_fields = ("manual_label", "dish_component__component__name", "component__name")
