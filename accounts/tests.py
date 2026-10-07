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


class TeamAppearanceTests(TestCase):
    """
    display_name/accent_color are purely cosmetic: a fun name and a color
    shown around the app, independent of Team.name (which stays the real,
    unique identifier used for login/registration) and the join code.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen Alpha", join_code="000211", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_shown_name_falls_back_to_the_real_name(self):
        self.assertEqual(self.team.shown_name, "Kitchen Alpha")
        self.team.display_name = "The Night Shift"
        self.team.save()
        self.assertEqual(self.team.shown_name, "The Night Shift")

    def test_navbar_shows_the_display_name_when_set(self):
        self.team.display_name = "The Night Shift"
        self.team.save()
        resp = self.client.get(reverse("home:index"))
        self.assertContains(resp, "The Night Shift")

    def test_navbar_falls_back_to_real_name_without_a_display_name(self):
        resp = self.client.get(reverse("home:index"))
        self.assertContains(resp, "Kitchen Alpha")

    def test_can_update_display_name_and_accent_color(self):
        resp = self.client.post(reverse("accounts:team_manage"), {
            "action": "update_appearance",
            "display_name": "The Night Shift",
            "accent_color": "forest",
        })
        self.assertRedirects(resp, reverse("accounts:team_manage"))
        self.team.refresh_from_db()
        self.assertEqual(self.team.display_name, "The Night Shift")
        self.assertEqual(self.team.accent_color, "forest")

    def test_real_team_name_and_join_code_are_unaffected(self):
        self.client.post(reverse("accounts:team_manage"), {
            "action": "update_appearance",
            "display_name": "The Night Shift",
            "accent_color": "forest",
        })
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, "Kitchen Alpha")
        self.assertEqual(self.team.join_code, "000211")

    def test_non_manager_cannot_update_appearance(self):
        member = User.objects.create_user(username="member", password="x")
        membership = TeamMembership.objects.create(
            user=member, team=self.team, role=TeamMembership.Role.MEMBER
        )
        membership.can_manage_team = False
        membership.save()

        self.client.force_login(member)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

        resp = self.client.post(reverse("accounts:team_manage"), {
            "action": "update_appearance",
            "display_name": "Hijacked Name",
            "accent_color": "amber",
        })
        self.assertRedirects(resp, reverse("home:index"))
        self.team.refresh_from_db()
        self.assertEqual(self.team.display_name, "")

    def test_html_root_carries_the_accent_attribute(self):
        self.team.accent_color = "plum"
        self.team.save()
        resp = self.client.get(reverse("home:index"))
        self.assertContains(resp, 'data-accent="plum"')

    def test_default_accent_is_blue(self):
        resp = self.client.get(reverse("home:index"))
        self.assertContains(resp, 'data-accent="blue"')


class DarkModeToggleTests(TestCase):
    def test_theme_toggle_button_present_for_logged_out_visitors(self):
        # The toggle lives outside the auth-gated part of the navbar, so it
        # should show up even on the login page.
        resp = self.client.get(reverse("account_login"))
        self.assertContains(resp, "data-theme-toggle")

    def test_theme_toggle_button_present_for_a_team_member(self):
        user = User.objects.create_user(username="cook", password="x")
        team = Team.objects.create(name="Kitchen", join_code="000212", created_by=user)
        TeamMembership.objects.create(user=user, team=team, role=TeamMembership.Role.OWNER)

        self.client.force_login(user)
        session = self.client.session
        session["active_team_id"] = team.id
        session.save()

        resp = self.client.get(reverse("home:index"))
        self.assertContains(resp, "data-theme-toggle")


class StaticCacheBustTests(TestCase):
    """
    static_v appends ?v=<mtime> in DEBUG so a browser never serves a stale
    cached style.css/app.js after an edit on the dev server. In production
    WhiteNoise's manifest storage already content-hashes the filename
    itself, so this is deliberately a no-op there.
    """

    def test_debug_mode_appends_a_version_query_string(self):
        from django.template import Context, Template
        from django.test import override_settings

        with override_settings(DEBUG=True):
            rendered = Template("{% load static_extras %}{% static_v 'js/app.js' %}").render(Context({}))
        self.assertRegex(rendered, r"^/static/js/app\.js\?v=\d+$")

    def test_production_mode_does_not_append_a_version_query_string(self):
        from django.template import Context, Template
        from django.test import override_settings

        with override_settings(DEBUG=False):
            rendered = Template("{% load static_extras %}{% static_v 'js/app.js' %}").render(Context({}))
        self.assertNotIn("?v=", rendered)
