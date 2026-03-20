from django.urls import path
from . import views

app_name = "menu"

urlpatterns = [
    # Team-member visible
    path("recipes/", views.RecipeListView.as_view(), name="recipe_list"),
    path("recipes/<int:pk>/", views.RecipeDetailView.as_view(), name="recipe_detail"),
    path("dishes/", views.DishListView.as_view(), name="dish_list"),
    path("dishes/<int:pk>/", views.DishDetailView.as_view(), name="dish_detail"),

    # Permissioned CRUD (team permission flags)
    path("recipes/create/", views.RecipeCreateView.as_view(), name="recipe_create"),
    path("recipes/<int:pk>/edit/", views.RecipeUpdateView.as_view(), name="recipe_edit"),
    path("recipes/<int:pk>/delete/", views.RecipeDeleteView.as_view(), name="recipe_delete"),

    path("dishes/create/", views.DishCreateView.as_view(), name="dish_create"),
    path("dishes/<int:pk>/edit/", views.DishUpdateView.as_view(), name="dish_edit"),
    path("dishes/<int:pk>/delete/", views.DishDeleteView.as_view(), name="dish_delete"),
    path("dishes/<int:pk>/toggle-on-use/", views.toggle_on_use, name="dish_toggle_on_use"),
    path("dishes/<int:pk>/components/edit/", views.edit_dish_components, name="dish_components_edit"),

    path("components/", views.ComponentListView.as_view(), name="component_list"),
    path("components/create/", views.ComponentCreateView.as_view(), name="component_create"),
    path("components/<int:pk>/edit/", views.ComponentUpdateView.as_view(), name="component_edit"),
    path("components/<int:pk>/delete/", views.ComponentDeleteView.as_view(), name="component_delete"),
]