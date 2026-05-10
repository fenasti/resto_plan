from django import forms
from menu.models import Dish

class PlanBuilderForm(forms.Form):
    dishes = forms.ModelMultipleChoiceField(
        queryset=Dish.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        if team is not None:
            self.fields["dishes"].queryset = Dish.objects.filter(team=team).order_by("name")