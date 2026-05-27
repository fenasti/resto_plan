from django import forms
from django.contrib.auth import get_user_model
from .models import CookProfile, Team, TeamMembership

User = get_user_model()

class CookProfileForm(forms.ModelForm):
    class Meta:
        model = CookProfile
        fields = ["display_name", "avatar"]
        widgets = {
            "display_name": forms.TextInput(attrs={"class": "form-control"}),
            "avatar": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }


class TeamCreateForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-control"})}


class TeamJoinForm(forms.Form):
    join_code = forms.CharField(
        max_length=12,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Enter join code"}),
    )


class TeamSelectForm(forms.Form):
    team_id = forms.ChoiceField(widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, teams=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["team_id"].choices = [(t.id, t.name) for t in (teams or [])]


class MembershipUpdateForm(forms.ModelForm):
    class Meta:
        model = TeamMembership
        fields = ["role", "can_manage_menu", "can_manage_recipes", "can_manage_team"]
        widgets = {
            "role": forms.Select(attrs={"class": "form-select"}),
            "can_manage_menu": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_recipes": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "can_manage_team": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class PlatformStaffToggleForm(forms.Form):
    user_id = forms.IntegerField(widget=forms.HiddenInput())
    make_staff = forms.BooleanField(required=False)
