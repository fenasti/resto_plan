from django import forms
from django.forms import modelformset_factory

from .models import OrderListItem, PurchaseCategory, PurchaseItem, Supplier


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
    """Scoped to a single supplier — you pick the supplier first (see
    OrderDetailView's `?supplier=` step), so this dropdown only ever shows
    that supplier's own items instead of the whole team catalog mixed
    together."""

    purchase_item = forms.ModelChoiceField(
        queryset=PurchaseItem.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        empty_label="Choose an existing item",
    )

    def __init__(self, *args, team=None, supplier=None, **kwargs):
        super().__init__(*args, **kwargs)
        if team is not None and supplier is not None:
            self.fields["purchase_item"].queryset = PurchaseItem.objects.filter(
                team=team, supplier=supplier, is_active=True
            ).order_by("category", "sort_order", "name")


class QuickCreatePurchaseItemForm(forms.ModelForm):
    """Supplier is deliberately NOT a field here — you only ever reach this
    form after picking a supplier in Step 1 of Add Item, and the view
    attaches that supplier directly rather than asking again."""

    class Meta:
        model = PurchaseItem
        fields = ["name", "category", "default_unit"]
        widgets = {
            "name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. Dish soap"}
            ),
            "category": forms.Select(attrs={"class": "form-select"}),
            "default_unit": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g. bottle / box / kg"}
            ),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.fields["category"].queryset = (
            PurchaseCategory.objects.filter(team=team) if team else PurchaseCategory.objects.none()
        )
        self.fields["category"].empty_label = "No category"

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.team and PurchaseItem.objects.filter(team=self.team, name__iexact=name).exists():
            raise forms.ValidationError("An item with this name already exists in your catalog.")
        return name

    def clean_default_unit(self):
        return self.cleaned_data["default_unit"].strip()


class PurchaseItemEditForm(forms.ModelForm):
    """Full edit form for the Purchase Item catalog page — unlike the
    quick-create form above, this is the only place to change an existing
    item's supplier/category after creation."""

    class Meta:
        model = PurchaseItem
        fields = ["name", "category", "supplier", "default_unit", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "supplier": forms.Select(attrs={"class": "form-select"}),
            "default_unit": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        self.fields["category"].queryset = (
            PurchaseCategory.objects.filter(team=team) if team else PurchaseCategory.objects.none()
        )
        self.fields["category"].empty_label = "No category"
        self.fields["supplier"].queryset = (
            Supplier.objects.filter(team=team) if team else Supplier.objects.none()
        )
        self.fields["supplier"].empty_label = "No supplier"

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.team:
            qs = PurchaseItem.objects.filter(team=self.team, name__iexact=name)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("An item with this name already exists in your catalog.")
        return name


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Jim's Produce"}),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.team and Supplier.objects.filter(team=self.team, name__iexact=name).exists():
            raise forms.ValidationError("A supplier with this name already exists.")
        return name


class PurchaseCategoryForm(forms.ModelForm):
    class Meta:
        model = PurchaseCategory
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Produce"}),
        }

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.team and PurchaseCategory.objects.filter(team=self.team, name__iexact=name).exists():
            raise forms.ValidationError("A category with this name already exists.")
        return name
