from django.contrib import admin

from .models import Component, Dish, DishComponent, Recipe

# Registered for debugging a live tenant's catalog without a Django shell —
# day-to-day CRUD stays in-app.


@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "is_active")
    list_filter = ("team", "is_active")
    search_fields = ("name",)


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ("name", "team")
    list_filter = ("team",)
    search_fields = ("name",)


@admin.register(Component)
class ComponentAdmin(admin.ModelAdmin):
    list_display = ("name", "team", "recipe", "standalone_active")
    list_filter = ("team", "standalone_active")
    search_fields = ("name",)


@admin.register(DishComponent)
class DishComponentAdmin(admin.ModelAdmin):
    list_display = ("dish", "component", "order")
    list_filter = ("dish__team",)
    search_fields = ("dish__name", "component__name")
