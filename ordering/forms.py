from django import forms
from django.forms import modelformset_factory

from .models import OrderListItem, PurchaseItem


class OrderItemEditForm(forms.ModelForm):
    class Meta:
        model = OrderListItem
        fields = ["quantity_text", "note"]
        widgets = {
            "quantity_text": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. 2 boxes / 5 kg"}
            ),
            "note": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Optional note"}
            ),
        }


OrderItemFormSet = modelformset_factory(
    OrderListItem,
    form=OrderItemEditForm,
    extra=0,
)


class AddExistingOrderItemForm(forms.Form):
    purchase_item = forms.ModelChoiceField(
        queryset=PurchaseItem.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Choose an existing item",
    )

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        if team is not None:
            self.fields["purchase_item"].queryset = PurchaseItem.objects.filter(
                team=team, is_active=True
            ).order_by("category", "sort_order", "name")


class QuickCreatePurchaseItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseItem
        fields = ["name", "category", "default_unit"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. Dish soap"}
            ),
            "category": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. Cleaning"}
            ),
            "default_unit": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. bottle / box / kg"}
            ),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.team and PurchaseItem.objects.filter(team=self.team, name__iexact=name).exists():
            raise forms.ValidationError("An item with this name already exists in your catalog.")
        return name

    def clean_category(self):
        return self.cleaned_data["category"].strip()

    def clean_default_unit(self):
        return self.cleaned_data["default_unit"].strip()

