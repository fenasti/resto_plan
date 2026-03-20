from django import forms
from django.forms import inlineformset_factory
from .models import Dish, Component, Recipe, DishComponent

class DishForm(forms.ModelForm):
    class Meta:
        model = Dish
        fields = ["name", "on_use"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "on_use": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

class RecipeForm(forms.ModelForm):
    class Meta:
        model = Recipe
        fields = ["name", "ingredients_text", "steps_text"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "ingredients_text": forms.Textarea(attrs={"class": "form-control", "rows": 10, "placeholder": "300 g butter\n2 L soy sauce\n..."}),
            "steps_text": forms.Textarea(attrs={"class": "form-control", "rows": 10, "placeholder": "Step 1...\nStep 2...\n..."}),
        }

class ComponentForm(forms.ModelForm):
    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        if team is not None:
            self.fields["recipe"].queryset = Recipe.objects.filter(team=team).order_by("name")

    class Meta:
        model = Component
        fields = ["name", "type", "spec_text", "recipe"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.Select(attrs={"class": "form-select"}),
            "spec_text": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "recipe": forms.Select(attrs={"class": "form-select"}),
        }

DishComponentFormSet = inlineformset_factory(
    parent_model=Dish,
    model=DishComponent,
    fields=["component", "order", "template_note"],
    extra=1,
    can_delete=True,
    widgets={
        "component": forms.Select(attrs={"class": "form-select"}),
        "order": forms.NumberInput(attrs={"class": "form-control", "style": "max-width:120px;"}),
        "template_note": forms.TextInput(attrs={"class": "form-control"}),
    },
)