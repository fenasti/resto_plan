from django import forms
from django.forms import formset_factory, inlineformset_factory
from .models import Dish, Component, Recipe, DishComponent

class DishForm(forms.ModelForm):
    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    class Meta:
        model = Dish
        fields = ["name", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"]
        if self.team is not None:
            qs = Dish.objects.filter(team=self.team, name=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("A dish with this name already exists.")
        return name

class RecipeForm(forms.ModelForm):
    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    class Meta:
        model = Recipe
        fields = ["name", "ingredients_text", "steps_text"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "ingredients_text": forms.Textarea(attrs={"class": "form-control", "rows": 10, "placeholder": "300 g butter\n2 L soy sauce\n..."}),
            "steps_text": forms.Textarea(attrs={"class": "form-control", "rows": 10, "placeholder": "Step 1...\nStep 2...\n..."}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"]
        if self.team is not None:
            qs = Recipe.objects.filter(team=self.team, name=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("A recipe with this name already exists.")
        return name

class ComponentForm(forms.ModelForm):
    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        if team is not None:
            self.fields["recipe"].queryset = Recipe.objects.filter(team=team).order_by("name")
        self.fields["recipe"].required = False

    class Meta:
        model = Component
        fields = ["name", "recipe", "standalone_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "recipe": forms.Select(attrs={"class": "form-select"}),
            "standalone_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"]
        if self.team is not None:
            qs = Component.objects.filter(team=self.team, name=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("A prep item with this name already exists.")
        return name

class QuickComponentForm(forms.Form):
    """One row of the manual-or-recipe quick-add widget on Edit Prep Items."""

    label = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Chop chives"}),
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
            raise forms.ValidationError("Enter a name OR pick a recipe, not both.")
        return cleaned

    def is_empty(self) -> bool:
        data = getattr(self, "cleaned_data", {}) or {}
        return not (data.get("label") or "").strip() and not data.get("recipe")


QuickComponentFormSet = formset_factory(QuickComponentForm, extra=1, can_delete=False)


DishComponentFormSet = inlineformset_factory(
    parent_model=Dish,
    model=DishComponent,
    fields=["component", "order", "template_note"],
    extra=3,
    can_delete=False,
    widgets={
        "component": forms.Select(attrs={"class": "form-select"}),
        "order": forms.NumberInput(attrs={"class": "form-control", "style": "max-width:120px;"}),
        "template_note": forms.TextInput(attrs={"class": "form-control"}),
    },
)
