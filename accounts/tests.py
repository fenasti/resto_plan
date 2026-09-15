from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Team, TeamMembership

User = get_user_model()


class FormErrorsVisibleTests(TestCase):
    """
    Regression tests for PREPPLAN_NOTES.md #3 ("Errores de formulario
    invisibles"): templates rendered `{{ form.field }}` without
    `{{ form.field.errors }}` / non_field_errors, so a rejected submission
    looked like it silently did nothing.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.client.force_login(self.user)

    def test_team_create_duplicate_name_shows_field_error(self):
        Team.objects.create(name="Kitchen", join_code="111111", created_by=self.user)
        response = self.client.post(reverse("accounts:team_create"), {"name": "Kitchen"})
        self.assertContains(response, "already exists")

    def test_team_join_empty_code_shows_field_error(self):
        response = self.client.post(reverse("accounts:team_join"), {"join_code": ""})
        self.assertContains(response, "This field is required")


class AccountsMobileTouchUsabilityTests(TestCase):
    """
    Same mobile-usability pass applied elsewhere: Manage Team and Profile
    are sub-screens reached from the dashboard, so they get a back link
    back to it instead of relying on the hamburger menu.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000210", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_team_manage_has_a_back_link_to_the_dashboard(self):
        resp = self.client.get(reverse("accounts:team_manage"))
        self.assertContains(resp, reverse("home:index"))
        self.assertContains(resp, "btn-back")

    def test_profile_has_a_back_link_to_the_dashboard(self):
        resp = self.client.get(reverse("accounts:profile"))
        self.assertContains(resp, reverse("home:index"))
        self.assertContains(resp, "btn-back")
