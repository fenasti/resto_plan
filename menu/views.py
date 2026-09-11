from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView

from accounts.decorators import team_permission_required
from accounts.mixins import SearchablePaginatedListMixin, TeamMemberRequiredMixin, TeamPermissionRequiredMixin
from planning import services as planning_services
from planning.models import PlanDish, PrepPlan, PrepTask
from .models import Dish, Component, Recipe, DishComponent
from .forms import DishForm, ComponentForm, RecipeForm, DishComponentFormSet


# ===== Team-member visible =====
class RecipeListView(TeamMemberRequiredMixin, SearchablePaginatedListMixin, ListView):
    model = Recipe
    template_name = "menu/recipe_list.html"
    context_object_name = "recipes"
    search_fields = ["name"]

    def get_base_queryset(self):
        return Recipe.objects.filter(team=self.request.team).order_by("name")

class RecipeDetailView(TeamMemberRequiredMixin, DetailView):
    model = Recipe
    template_name = "menu/recipe_detail.html"
    context_object_name = "recipe"

    def get_queryset(self):
        return Recipe.objects.filter(team=self.request.team)

class DishListView(TeamMemberRequiredMixin, SearchablePaginatedListMixin, ListView):
    model = Dish
    template_name = "menu/dish_list.html"
    context_object_name = "dishes"
    search_fields = ["name"]

    def get_base_queryset(self):
        return Dish.objects.filter(team=self.request.team).order_by("name")

class DishDetailView(TeamMemberRequiredMixin, DetailView):
    model = Dish
    template_name = "menu/dish_detail.html"
    context_object_name = "dish"

    def get_queryset(self):
        return Dish.objects.filter(team=self.request.team)


# ===== Permissioned CRUD =====
class RecipeCreateView(TeamPermissionRequiredMixin, CreateView):
    required_flag = "can_manage_recipes"
    model = Recipe
    form_class = RecipeForm
    template_name = "menu/recipe_form.html"
    success_url = reverse_lazy("menu:recipe_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        return kwargs

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.team = self.request.team
        obj.save()
        return redirect(self.success_url)

class RecipeUpdateView(TeamPermissionRequiredMixin, UpdateView):
    required_flag = "can_manage_recipes"
    model = Recipe
    form_class = RecipeForm
    template_name = "menu/recipe_form.html"
    success_url = reverse_lazy("menu:recipe_list")

    def get_queryset(self):
        return Recipe.objects.filter(team=self.request.team)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        return kwargs

class RecipeDeleteView(TeamPermissionRequiredMixin, DeleteView):
    required_flag = "can_manage_recipes"
    model = Recipe
    template_name = "menu/confirm_delete.html"
    success_url = reverse_lazy("menu:recipe_list")

    def get_queryset(self):
        return Recipe.objects.filter(team=self.request.team)


class DishCreateView(TeamPermissionRequiredMixin, CreateView):
    required_flag = "can_manage_menu"
    model = Dish
    form_class = DishForm
    template_name = "menu/dish_form.html"
    success_url = reverse_lazy("menu:dish_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        return kwargs

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.team = self.request.team
        obj.save()
        return redirect(self.success_url)

class DishUpdateView(TeamPermissionRequiredMixin, UpdateView):
    required_flag = "can_manage_menu"
    model = Dish
    form_class = DishForm
    template_name = "menu/dish_form.html"
    success_url = reverse_lazy("menu:dish_list")

    def get_queryset(self):
        return Dish.objects.filter(team=self.request.team)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["team"] = self.request.team
        return kwargs

class DishDeleteView(TeamPermissionRequiredMixin, DeleteView):
    required_flag = "can_manage_menu"
    model = Dish
    template_name = "menu/confirm_delete.html"
    success_url = reverse_lazy("menu:dish_list")

    def get_queryset(self):
        return Dish.objects.filter(team=self.request.team)

    def post(self, request, *args, **kwargs):
        dish = self.get_object()
        dish_name = dish.name

        has_production_history = (
            PlanDish.objects.filter(dish=dish, plan__state=PrepPlan.PlanState.PRODUCTION).exists()
            or PrepTask.objects.filter(
                dish_component__dish=dish,
                plan__state=PrepPlan.PlanState.PRODUCTION,
            ).exists()
        )

        if has_production_history:
            dish.on_use = False
            dish.save(update_fields=["on_use"])
            messages.warning(
                request,
                f"'{dish_name}' is used in a production plan, so it was turned off instead of deleted.",
            )
            return redirect(self.success_url)

        try:
            with transaction.atomic():
                PrepTask.objects.filter(
                    dish_component__dish=dish,
                    plan__state=PrepPlan.PlanState.DRAFT,
                ).delete()
                PlanDish.objects.filter(
                    dish=dish,
                    plan__state=PrepPlan.PlanState.DRAFT,
                ).delete()
                dish.delete()
        except ProtectedError:
            dish.on_use = False
            dish.save(update_fields=["on_use"])
            messages.warning(
                request,
                f"'{dish_name}' still has protected references, so it was turned off instead of deleted.",
            )
            return redirect(self.success_url)

        messages.success(request, f"Dish '{dish_name}' deleted.")
        return redirect(self.success_url)


def _refresh_draft_plans_for_dish(dish: Dish) -> int:
    draft_plans = (
        PrepPlan.objects.filter(
            team=dish.team,
            state=PrepPlan.PlanState.DRAFT,
            plan_dishes__dish=dish,
        )
        .distinct()
    )
    for plan in draft_plans:
        planning_services.build_placeholders_hard_reset(plan)
    return draft_plans.count()


class ComponentListView(TeamPermissionRequiredMixin, SearchablePaginatedListMixin, ListView):
    required_flag = "can_manage_menu"
    model = Component
    template_name = "menu/component_list.html"
    context_object_name = "components"
    search_fields = ["name"]

    def get_base_queryset(self):
        return Component.objects.filter(team=self.request.team).order_by("name")

class ComponentCreateView(TeamPermissionRequiredMixin, CreateView):
    required_flag = "can_manage_menu"
    model = Component
    template_name = "menu/component_form.html"
    success_url = reverse_lazy("menu:component_list")

    def get_form(self, form_class=None):
        return ComponentForm(self.request.POST or None, team=self.request.team)

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.team = self.request.team
        obj.save()
        return redirect(self.success_url)

class ComponentUpdateView(TeamPermissionRequiredMixin, UpdateView):
    required_flag = "can_manage_menu"
    model = Component
    template_name = "menu/component_form.html"
    success_url = reverse_lazy("menu:component_list")

    def get_queryset(self):
        return Component.objects.filter(team=self.request.team)

    def get_form(self, form_class=None):
        return ComponentForm(self.request.POST or None, instance=self.get_object(), team=self.request.team)

class ComponentDeleteView(TeamPermissionRequiredMixin, DeleteView):
    required_flag = "can_manage_menu"
    model = Component
    template_name = "menu/confirm_delete.html"
    success_url = reverse_lazy("menu:component_list")

    def get_queryset(self):
        return Component.objects.filter(team=self.request.team)

    def post(self, request, *args, **kwargs):
        component = self.get_object()
        component_name = component.name

        has_production_history = PrepTask.objects.filter(
            dish_component__component=component,
            plan__state=PrepPlan.PlanState.PRODUCTION,
        ).exists()

        if has_production_history:
            messages.warning(
                request,
                f"'{component_name}' is used in a production prep sheet, so it cannot be deleted.",
            )
            return redirect(self.success_url)

        affected_dishes = list(Dish.objects.filter(dish_components__component=component).distinct())

        try:
            with transaction.atomic():
                PrepTask.objects.filter(
                    dish_component__component=component,
                    plan__state=PrepPlan.PlanState.DRAFT,
                ).delete()
                component.delete()
        except ProtectedError:
            messages.warning(
                request,
                f"'{component_name}' still has protected references, so it could not be deleted.",
            )
            return redirect(self.success_url)

        refreshed_count = sum(_refresh_draft_plans_for_dish(dish) for dish in affected_dishes)
        message = f"Component '{component_name}' deleted."
        if refreshed_count:
            message += f" Updated {refreshed_count} draft prep sheet(s)."
        messages.success(request, message)
        return redirect(self.success_url)


@login_required
@team_permission_required("can_manage_menu")
def toggle_on_use(request, pk: int):
    dish = get_object_or_404(Dish, pk=pk, team=request.team)
    dish.on_use = not dish.on_use
    dish.save(update_fields=["on_use"])
    messages.success(request, f"Dish '{dish.name}' on_use set to {dish.on_use}")
    return redirect("menu:dish_list")


@login_required
@team_permission_required("can_manage_menu")
def edit_dish_components(request, pk: int):
    dish = get_object_or_404(Dish, pk=pk, team=request.team)
    formset = DishComponentFormSet(request.POST or None, instance=dish)

    # Filter component choices by team
    for form in formset.forms:
        if "component" in form.fields:
            form.fields["component"].queryset = Component.objects.filter(team=request.team).order_by("name")

    if request.method == "POST" and formset.is_valid():
        formset.save()
        refreshed_count = _refresh_draft_plans_for_dish(dish)
        message = f"Prep items updated for '{dish.name}'."
        if refreshed_count:
            message += f" Updated {refreshed_count} draft prep sheet(s)."
        messages.success(request, message)
        return redirect("menu:dish_detail", pk=dish.pk)

    return render(request, "menu/dish_components_edit.html", {"dish": dish, "formset": formset})


@login_required
@team_permission_required("can_manage_menu")
def remove_dish_component(request, pk: int):
    if request.method != "POST":
        return HttpResponse(status=405)

    dish_component = get_object_or_404(
        DishComponent.objects.select_related("dish", "component"),
        pk=pk,
        dish__team=request.team,
    )
    dish = dish_component.dish
    component_name = dish_component.component.name

    has_production_history = PrepTask.objects.filter(
        dish_component=dish_component,
        plan__state=PrepPlan.PlanState.PRODUCTION,
    ).exists()

    if has_production_history:
        messages.warning(
            request,
            f"'{component_name}' is already used in a production prep sheet, so it cannot be removed from '{dish.name}'.",
        )
        return redirect("menu:dish_detail", pk=dish.pk)

    try:
        with transaction.atomic():
            PrepTask.objects.filter(
                dish_component=dish_component,
                plan__state=PrepPlan.PlanState.DRAFT,
            ).delete()
            dish_component.delete()
    except ProtectedError:
        messages.warning(
            request,
            f"'{component_name}' still has protected references, so it could not be removed.",
        )
        return redirect("menu:dish_detail", pk=dish.pk)

    refreshed_count = _refresh_draft_plans_for_dish(dish)
    message = f"Removed '{component_name}' from '{dish.name}'."
    if refreshed_count:
        message += f" Updated {refreshed_count} draft prep sheet(s)."
    messages.success(request, message)
    return redirect("menu:dish_detail", pk=dish.pk)
