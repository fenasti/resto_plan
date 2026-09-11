from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Team

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
