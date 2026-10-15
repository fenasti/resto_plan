from unittest.mock import patch

import cloudinary.exceptions
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .models import PlatformBootstrap, Team, TeamMembership
from .views import TeamJoinView

User = get_user_model()


class TeamJoinRateLimitTests(TestCase):
    """
    Regression/coverage for brute-force protection on join codes: a code is
    just 6 digits (1M possibilities) and every team is a different
    operation's private data, so unlimited guesses must not be possible.
    """

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="guesser", password="x")
        self.client.force_login(self.user)
        self.owner = User.objects.create_user(username="owner", password="x")
        self.team = Team.objects.create(name="Real Kitchen", join_code="123456", created_by=self.owner)

    def test_wrong_codes_under_the_limit_just_show_invalid(self):
        for _ in range(TeamJoinView.JOIN_RATE_LIMIT_MAX - 1):
            # Plain status check, not assertRedirects — it auto-follows the
            # redirect to verify the target, and that extra GET would
            # consume (and clear) this iteration's message before the
            # assertion below gets to see it.
            resp = self.client.post(reverse("accounts:team_join"), {"join_code": "000000"})
            self.assertEqual(resp.status_code, 302)
        resp = self.client.get(reverse("accounts:team_join"))
        self.assertContains(resp, "Invalid join code.")

    def test_exceeding_the_limit_blocks_further_attempts_even_with_the_right_code(self):
        for _ in range(TeamJoinView.JOIN_RATE_LIMIT_MAX):
            self.client.post(reverse("accounts:team_join"), {"join_code": "000000"})

        resp = self.client.post(reverse("accounts:team_join"), {"join_code": "123456"})
        resp = self.client.get(reverse("accounts:team_join"))
        self.assertContains(resp, "Too many incorrect join codes")
        self.assertFalse(TeamMembership.objects.filter(user=self.user, team=self.team).exists())

    def test_a_successful_join_resets_the_attempt_counter(self):
        for _ in range(TeamJoinView.JOIN_RATE_LIMIT_MAX - 1):
            self.client.post(reverse("accounts:team_join"), {"join_code": "000000"})

        self.client.post(reverse("accounts:team_join"), {"join_code": "123456"})
        self.assertTrue(TeamMembership.objects.filter(user=self.user, team=self.team).exists())

        # The counter should be cleared, so a fresh wrong guess right after
        # a success doesn't inherit the near-exhausted count.
        resp = self.client.post(reverse("accounts:team_join"), {"join_code": "000000"})
        resp = self.client.get(reverse("accounts:team_join"))
        self.assertContains(resp, "Invalid join code.")
        self.assertNotContains(resp, "Too many incorrect join codes")

    def test_rate_limit_is_scoped_per_user(self):
        for _ in range(TeamJoinView.JOIN_RATE_LIMIT_MAX):
            self.client.post(reverse("accounts:team_join"), {"join_code": "000000"})

        other_user = User.objects.create_user(username="another_cook", password="x")
        self.client.force_login(other_user)
        self.client.post(reverse("accounts:team_join"), {"join_code": "123456"})
        self.assertTrue(TeamMembership.objects.filter(user=other_user, team=self.team).exists())


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


class PlatformBootstrapIsPermanentTests(TestCase):
    """
    The first-user-becomes-staff bootstrap used to re-fire any time the
    current is_staff count hit zero — including via an admin account being
    deleted outright, not just demoted. Once public signup is open to
    outside users (the product's stated SaaS direction), that's a real
    backdoor: delete (or lose access to) the one admin account, and the
    very next stranger to sign up silently becomes a platform admin.

    The fix makes the bootstrap a true one-time event via a permanent
    PlatformBootstrap marker row that is never deleted, so it can't be
    re-armed by any later change in the staff count.
    """

    def test_first_user_ever_becomes_staff(self):
        user = User.objects.create_user(username="first", password="x")
        self.assertTrue(user.is_staff)
        self.assertTrue(PlatformBootstrap.objects.filter(pk=1).exists())

    def test_second_user_does_not_become_staff(self):
        User.objects.create_user(username="first", password="x")
        second = User.objects.create_user(username="second", password="x")
        self.assertFalse(second.is_staff)

    def test_deleting_the_bootstrapped_admin_does_not_rearm_bootstrap(self):
        first = User.objects.create_user(username="first", password="x")
        first.delete()
        self.assertFalse(User.objects.filter(is_staff=True).exists(), "staff count is genuinely zero now")

        next_signup = User.objects.create_user(username="next_signup", password="x")
        self.assertFalse(
            next_signup.is_staff,
            "a later public signup must not become staff just because the admin count dropped to zero",
        )

    def test_demoting_the_only_admin_to_zero_also_does_not_rearm_bootstrap(self):
        # The in-app "can't remove the last admin" guard (PlatformAdminUsersView)
        # already blocks this specific path, but the bootstrap logic itself
        # must not depend on that guard existing — belt and suspenders.
        first = User.objects.create_user(username="first", password="x")
        first.is_staff = False
        first.save(update_fields=["is_staff"])

        next_signup = User.objects.create_user(username="next_signup", password="x")
        self.assertFalse(next_signup.is_staff)


class SelfServiceTeamCreationTests(TestCase):
    """
    Regression: TeamCreateView used to require request.user.is_staff, which
    made sense for a single-restaurant internal tool but broke the SaaS
    signup path — only the very first account ever created on a deployment
    gets auto-promoted to is_staff (see accounts.signals), so every
    subsequent new restaurant owner hit a dead end with no way to create
    their own workspace and become its OWNER. Any signed-in user must be
    able to create a team now.
    """

    def setUp(self):
        # A pre-existing staff user so the bootstrap-first-user-as-staff
        # signal doesn't make our test user staff by accident, which would
        # mask the bug this test guards against.
        User.objects.create_user(username="existing_admin", password="x", is_staff=True)
        self.user = User.objects.create_user(username="new_owner", password="x")
        self.assertFalse(self.user.is_staff)
        self.client.force_login(self.user)

    def test_non_staff_user_can_reach_the_create_team_form(self):
        resp = self.client.get(reverse("accounts:team_create"))
        self.assertEqual(resp.status_code, 200)

    def test_non_staff_user_creating_a_team_becomes_its_owner(self):
        resp = self.client.post(reverse("accounts:team_create"), {"name": "New Restaurant"})
        self.assertRedirects(resp, reverse("home:index"))

        team = Team.objects.get(name="New Restaurant")
        membership = TeamMembership.objects.get(user=self.user, team=team)
        self.assertEqual(membership.role, TeamMembership.Role.OWNER)
        self.assertTrue(membership.can_manage_team)
        self.assertTrue(membership.can_manage_menu)
        self.assertTrue(membership.can_manage_recipes)

    def test_team_start_offers_create_to_non_staff_users(self):
        resp = self.client.get(reverse("accounts:team_start"))
        self.assertContains(resp, reverse("accounts:team_create"))
        self.assertContains(resp, "Create a New Team")

    def test_dashboard_offers_create_workspace_to_non_staff_users(self):
        team = Team.objects.create(name="Existing", join_code="222222", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=team, role=TeamMembership.Role.OWNER)
        session = self.client.session
        session["active_team_id"] = team.id
        session.save()

        resp = self.client.get(reverse("home:index"))
        self.assertContains(resp, reverse("accounts:team_create"))


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


class ProfileAvatarUploadFailureTests(TransactionTestCase):
    """
    CookProfile.avatar saves go straight to Cloudinary (MediaCloudinaryStorage)
    with no retry/catch — an outage or bad credentials previously surfaced as
    a raw 500 instead of a friendly "try again" message.

    Uses TransactionTestCase, not TestCase: Model.save_base() wraps the
    actual write in transaction.atomic(savepoint=False), so deliberately
    raising mid-save inside plain TestCase's own outer atomic wrapper
    poisons that transaction (a Django testing nuance, not a production
    behavior) and makes the subsequent session save fail with an unrelated
    SessionInterrupted. TransactionTestCase doesn't wrap tests in an outer
    atomic, so this doesn't arise.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.client.force_login(self.user)

    def _tiny_png(self):
        # A real 1x1 PNG generated via Pillow, so Django's ImageField
        # validation (which opens and verifies it) accepts it.
        import io
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (1, 1)).save(buf, format="PNG")
        return SimpleUploadedFile("avatar.png", buf.getvalue(), content_type="image/png")

    @patch("cloudinary_storage.storage.MediaCloudinaryStorage._save")
    def test_cloudinary_failure_shows_a_friendly_message_instead_of_500(self, mock_save):
        mock_save.side_effect = cloudinary.exceptions.Error("simulated outage")
        resp = self.client.post(
            reverse("accounts:profile"),
            {"display_name": "Cook", "avatar": self._tiny_png()},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Could not upload image")

    @patch("cloudinary_storage.storage.MediaCloudinaryStorage._save")
    def test_successful_upload_still_works(self, mock_save):
        mock_save.return_value = "avatars/avatar.png"
        resp = self.client.post(
            reverse("accounts:profile"),
            {"display_name": "Cook", "avatar": self._tiny_png()},
        )
        self.assertRedirects(resp, reverse("accounts:profile"))
        self.user.cookprofile.refresh_from_db()
        self.assertTrue(self.user.cookprofile.avatar)


class TeamManageMemberMutationTests(TestCase):
    """
    update_member/remove_member were previously entirely untested — the
    most permission-sensitive mutation in the app (role/flag changes,
    removal) had zero coverage. Also covers the malformed-membership_id
    fix (was a raw int() with no try/except -> 500 on a bad value).
    """

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000311", created_by=self.owner)
        TeamMembership.objects.create(
            user=self.owner, team=self.team, role=TeamMembership.Role.OWNER,
            can_manage_team=True, can_manage_menu=True, can_manage_recipes=True,
        )
        self.member_user = User.objects.create_user(username="cook", password="x")
        self.member = TeamMembership.objects.create(
            user=self.member_user, team=self.team, role=TeamMembership.Role.MEMBER,
        )

        self.client.force_login(self.owner)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_update_member_role_to_admin_grants_full_perms(self):
        resp = self.client.post(reverse("accounts:team_manage"), {
            "action": "update_member",
            "membership_id": self.member.id,
            "role": TeamMembership.Role.ADMIN,
        })
        self.assertRedirects(resp, reverse("accounts:team_manage"))
        self.member.refresh_from_db()
        self.assertEqual(self.member.role, TeamMembership.Role.ADMIN)
        self.assertTrue(self.member.can_manage_team)
        self.assertTrue(self.member.can_manage_menu)
        self.assertTrue(self.member.can_manage_recipes)

    def test_remove_member_deletes_the_membership(self):
        resp = self.client.post(reverse("accounts:team_manage"), {
            "action": "remove_member",
            "membership_id": self.member.id,
        })
        self.assertRedirects(resp, reverse("accounts:team_manage"))
        self.assertFalse(TeamMembership.objects.filter(id=self.member.id).exists())

    def test_cannot_remove_the_owner(self):
        owner_membership = TeamMembership.objects.get(user=self.owner, team=self.team)
        resp = self.client.post(reverse("accounts:team_manage"), {
            "action": "remove_member",
            "membership_id": owner_membership.id,
        })
        self.assertRedirects(resp, reverse("accounts:team_manage"))
        self.assertTrue(TeamMembership.objects.filter(id=owner_membership.id).exists())

    def test_cannot_act_on_a_membership_from_another_team(self):
        other_owner = User.objects.create_user(username="other_owner", password="x")
        other_team = Team.objects.create(name="Other Kitchen", join_code="000312", created_by=other_owner)
        other_membership = TeamMembership.objects.create(
            user=other_owner, team=other_team, role=TeamMembership.Role.MEMBER,
        )
        resp = self.client.post(reverse("accounts:team_manage"), {
            "action": "remove_member",
            "membership_id": other_membership.id,
        })
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(TeamMembership.objects.filter(id=other_membership.id).exists())

    def test_malformed_membership_id_does_not_crash(self):
        resp = self.client.post(reverse("accounts:team_manage"), {
            "action": "remove_member",
            "membership_id": "not-a-number",
        })
        self.assertRedirects(resp, reverse("accounts:team_manage"))

    def test_missing_membership_id_does_not_crash(self):
        resp = self.client.post(reverse("accounts:team_manage"), {"action": "remove_member"})
        self.assertRedirects(resp, reverse("accounts:team_manage"))


class PlatformAdminUsersViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="x", is_staff=True)
        self.client.force_login(self.admin)

    def test_can_grant_staff_to_another_user(self):
        other = User.objects.create_user(username="other", password="x")
        resp = self.client.post(reverse("accounts:platform_users"), {
            "user_id": other.id,
            "make_staff": "on",
        })
        self.assertRedirects(resp, reverse("accounts:platform_users"))
        other.refresh_from_db()
        self.assertTrue(other.is_staff)

    def test_cannot_remove_the_last_platform_admin(self):
        resp = self.client.post(reverse("accounts:platform_users"), {"user_id": self.admin.id})
        self.assertRedirects(resp, reverse("accounts:platform_users"))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_staff, "the only admin should not have been demoted")

    def test_can_remove_staff_when_another_admin_remains(self):
        other_admin = User.objects.create_user(username="other_admin", password="x", is_staff=True)
        resp = self.client.post(reverse("accounts:platform_users"), {"user_id": other_admin.id})
        self.assertRedirects(resp, reverse("accounts:platform_users"))
        other_admin.refresh_from_db()
        self.assertFalse(other_admin.is_staff)

    def test_user_list_is_paginated(self):
        for i in range(30):
            User.objects.create_user(username=f"bulk_user_{i}", password="x")
        resp = self.client.get(reverse("accounts:platform_users"))
        self.assertTrue(resp.context["is_paginated"])
        self.assertEqual(len(resp.context["page_obj"]), 25)


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


class AnonymousAccessToTeamGatedViewsTests(TestCase):
    """
    TeamMemberRequiredMixin/TeamPermissionRequiredMixin used to query
    TeamMembership.objects.filter(user=request.user) before checking
    whether request.user was even authenticated. For an anonymous visitor,
    request.user is an AnonymousUser, which isn't a valid FK filter value —
    Django raised a TypeError (uncaught -> 500) instead of redirecting to
    login. Found by live-testing the app as an anonymous human would
    (bookmarked link, shared URL, expired session), not by reading the
    mixin in isolation. Covers one view from each of the three affected
    apps plus the permission-flag variant.
    """

    def test_anonymous_visit_to_a_team_member_gated_view_redirects_to_login(self):
        resp = self.client.get(reverse("planning:plan_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("account_login"), resp.url)

    def test_anonymous_visit_to_a_permission_gated_view_redirects_to_login(self):
        resp = self.client.get(reverse("accounts:team_manage"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("account_login"), resp.url)

    def test_anonymous_visit_preserves_next_param_back_to_the_original_page(self):
        target = reverse("menu:recipe_list")
        resp = self.client.get(target)
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("account_login"), resp.url)
        self.assertIn(f"next={target}", resp.url)

    def test_logged_in_user_with_no_active_team_still_redirects_to_team_select(self):
        # Make sure the authenticated path wasn't broken by the new check.
        user = User.objects.create_user(username="loner", password="x")
        self.client.force_login(user)
        resp = self.client.get(reverse("planning:plan_list"))
        self.assertRedirects(resp, reverse("accounts:team_start"))


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
