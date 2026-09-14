from django import forms
from django.forms import formset_factory

from menu.models import Component, Dish, Recipe


class PlanBuilderForm(forms.Form):
    dishes = forms.ModelMultipleChoiceField(
        queryset=Dish.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    standalone_components = forms.ModelMultipleChoiceField(
        queryset=Component.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        if team is not None:
            self.fields["dishes"].queryset = Dish.objects.filter(team=team).order_by("name")
            self.fields["standalone_components"].queryset = Component.objects.filter(
                team=team, standalone_active=True, dish_components__isnull=True
            ).order_by("name")


class AdHocTaskForm(forms.Form):
    label = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Clean the fish"}),
    )
    recipe = forms.ModelChoiceField(
        queryset=Recipe.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        if team is not None:
            self.fields["recipe"].queryset = Recipe.objects.filter(team=team).order_by("name")

    def clean(self):
        cleaned = super().clean()
        label = (cleaned.get("label") or "").strip()
        if label and cleaned.get("recipe"):
            raise forms.ValidationError("Enter a label OR pick a recipe, not both.")
        return cleaned

    def is_empty(self) -> bool:
        data = getattr(self, "cleaned_data", {}) or {}
        return not (data.get("label") or "").strip() and not data.get("recipe")


AdHocTaskFormSet = formset_factory(AdHocTaskForm, extra=1, can_delete=False)
