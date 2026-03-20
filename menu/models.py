from django.db import models
from accounts.models import Team

class Dish(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="dishes")
    name = models.CharField(max_length=200)
    on_use = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="uniq_team_dish_name")
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.team.name})"


class Recipe(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="recipes")
    name = models.CharField(max_length=200)
    ingredients_text = models.TextField()
    steps_text = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="uniq_team_recipe_name")
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.team.name})"


class Component(models.Model):
    class ComponentType(models.TextChoices):
        RECIPE = "RECIPE", "Recipe"
        SIMPLE_PREP = "SIMPLE_PREP", "Simple prep"
        PROCESS_STATE = "PROCESS_STATE", "Process/state"
        CHECK = "CHECK", "Check"

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="components")
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=ComponentType.choices)
    spec_text = models.TextField(blank=True)
    recipe = models.ForeignKey(Recipe, null=True, blank=True, on_delete=models.SET_NULL, related_name="components")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "name"], name="uniq_team_component_name")
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.team.name})"


class DishComponent(models.Model):
    dish = models.ForeignKey(Dish, on_delete=models.CASCADE, related_name="dish_components")
    component = models.ForeignKey(Component, on_delete=models.CASCADE, related_name="dish_components")
    order = models.PositiveIntegerField(default=1)
    template_note = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dish", "component"], name="uniq_dish_component")
        ]
        ordering = ["dish", "order", "id"]

    def __str__(self):
        return f"{self.dish.name} -> {self.component.name}"