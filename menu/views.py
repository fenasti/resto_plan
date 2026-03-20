from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView

from accounts.mixins import TeamMemberRequiredMixin, TeamPermissionRequiredMixin
from accounts.models import TeamMembership
from .models import Dish, Component, Recipe
from .forms import DishForm, ComponentForm, RecipeForm, DishComponentFormSet


# ===== Team-member visible =====
class RecipeListView(TeamMemberRequiredMixin, ListView):
    model = Recipe
    template_name = "menu/recipe_list.html"
    context_object_name = "recipes"

    def get_queryset(self):
        return Recipe.objects.filter(team=self.request.team).order_by("name")

class RecipeDetailView(TeamMemberRequiredMixin, DetailView):
    model = Recipe
    template_name = "menu/recipe_detail.html"
    context_object_name = "recipe"

    def get_queryset(self):
        return Recipe.objects.filter(team=self.request.team)

class DishListView(TeamMemberRequiredMixin, ListView):
    model = Dish
    template_name = "menu/dish_list.html"
    context_object_name = "dishes"

    def get_queryset(self):
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

class DishDeleteView(TeamPermissionRequiredMixin, DeleteView):
    required_flag = "can_manage_menu"
    model = Dish
    template_name = "menu/confirm_delete.html"
    success_url = reverse_lazy("menu:dish_list")

    def get_queryset(self):
        return Dish.objects.filter(team=self.request.team)


class ComponentListView(TeamPermissionRequiredMixin, ListView):
    required_flag = "can_manage_menu"
    model = Component
    template_name = "menu/component_list.html"
    context_object_name = "components"

    def get_queryset(self):
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


@login_required
def toggle_on_use(request, pk: int):
    """
    Requires can_manage_menu (or OWNER/ADMIN).
    """
    membership = request.membership
    if not membership or (not membership.can_manage_menu and membership.role not in (TeamMembership.Role.OWNER, TeamMembership.Role.ADMIN)):
        return redirect("home:index")

    dish = get_object_or_404(Dish, pk=pk, team=request.team)
    dish.on_use = not dish.on_use
    dish.save(update_fields=["on_use"])
    messages.success(request, f"Dish '{dish.name}' on_use set to {dish.on_use}")
    return redirect("menu:dish_list")


@login_required
def edit_dish_components(request, pk: int):
    membership = request.membership
    if not membership or (not membership.can_manage_menu and membership.role not in (TeamMembership.Role.OWNER, TeamMembership.Role.ADMIN)):
        return redirect("home:index")

    dish = get_object_or_404(Dish, pk=pk, team=request.team)
    formset = DishComponentFormSet(request.POST or None, instance=dish)

    # Filter component choices by team
    for form in formset.forms:
        if "component" in form.fields:
            form.fields["component"].queryset = Component.objects.filter(team=request.team).order_by("name")

    if request.method == "POST" and formset.is_valid():
        formset.save()
        messages.success(request, f"Components updated for '{dish.name}'.")
        return redirect("menu:dish_detail", pk=dish.pk)

    return render(request, "menu/dish_components_edit.html", {"dish": dish, "formset": formset})