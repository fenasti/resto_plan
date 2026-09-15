import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from django.db import IntegrityError, transaction

from accounts.models import Team, TeamMembership
from menu.models import Component, Dish, DishComponent, Recipe
from .models import PrepPlan, PrepTask
from . import services

User = get_user_model()


class BuildPlaceholdersSyncTests(TestCase):
    """
    Regression tests for build_placeholders_hard_reset: it must sync PrepTasks
    to the current dish/component selection without wiping status/assignee/
    daily_note on tasks that are still part of the plan.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000001", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component_a = Component.objects.create(team=self.team, name="Broth")
        self.component_b = Component.objects.create(team=self.team, name="Noodles")
        self.dc_a = DishComponent.objects.create(dish=self.dish, component=self.component_a, order=1)
        self.dc_b = DishComponent.objects.create(dish=self.dish, component=self.component_b, order=2)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 1, 1), self.user)

    def test_preserves_status_assignee_and_note_when_unrelated_component_is_edited(self):
        task_a = PrepTask.objects.get(plan=self.plan, dish_component=self.dc_a)
        task_a.status = PrepTask.TaskStatus.DONE
        task_a.assignee = self.user
        task_a.daily_note = "quedó justo"
        task_a.save()

        # Simulates editing an unrelated field on a different DishComponent
        # (e.g. via edit_dish_components), which triggers a resync.
        self.dc_b.template_note = "cook 2 extra minutes"
        self.dc_b.save()
        services.build_placeholders_hard_reset(self.plan)

        task_a.refresh_from_db()
        self.assertEqual(task_a.status, PrepTask.TaskStatus.DONE)
        self.assertEqual(task_a.assignee, self.user)
        self.assertEqual(task_a.daily_note, "quedó justo")

    def test_adds_task_for_newly_added_component(self):
        component_c = Component.objects.create(team=self.team, name="Egg")
        DishComponent.objects.create(dish=self.dish, component=component_c, order=3)

        services.build_placeholders_hard_reset(self.plan)

        self.assertTrue(
            PrepTask.objects.filter(plan=self.plan, dish_component__component=component_c).exists()
        )
        self.assertEqual(PrepTask.objects.filter(plan=self.plan).count(), 3)

    def test_removes_task_for_component_removed_from_dish_while_preserving_others(self):
        task_a = PrepTask.objects.get(plan=self.plan, dish_component=self.dc_a)
        task_a.status = PrepTask.TaskStatus.DONE
        task_a.save()

        # dish_component -> PrepTask is on_delete=PROTECT, so callers (e.g.
        # menu.views.remove_dish_component) must clear referencing draft
        # tasks before deleting the DishComponent itself.
        PrepTask.objects.filter(dish_component=self.dc_b, plan__state=PrepPlan.PlanState.DRAFT).delete()
        self.dc_b.delete()
        services.build_placeholders_hard_reset(self.plan)

        self.assertFalse(PrepTask.objects.filter(plan=self.plan, dish_component_id=self.dc_b.id).exists())
        task_a.refresh_from_db()
        self.assertEqual(task_a.status, PrepTask.TaskStatus.DONE)

    def test_removes_all_tasks_when_dish_removed_from_plan(self):
        self.plan.plan_dishes.all().delete()
        services.build_placeholders_hard_reset(self.plan)
        self.assertEqual(PrepTask.objects.filter(plan=self.plan).count(), 0)


class CompletePlanTests(TestCase):
    """
    Tests for the PRODUCTION -> COMPLETE lock (read-only prep sheet) and its
    reverse via reopen_plan.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000005", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component = Component.objects.create(team=self.team, name="Broth")
        self.dish_component = DishComponent.objects.create(dish=self.dish, component=self.component, order=1)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 1, 1), self.user)
        services.finalize_plan(self.plan, self.user)
        self.task = PrepTask.objects.get(plan=self.plan, dish_component=self.dish_component)

    def test_complete_plan_is_noop_unless_production(self):
        draft_plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 1, 2), self.user)
        services.complete_plan(draft_plan, self.user)
        self.assertEqual(draft_plan.state, PrepPlan.PlanState.DRAFT)

    def test_complete_plan_sets_state_and_metadata(self):
        services.complete_plan(self.plan, self.user)
        self.assertEqual(self.plan.state, PrepPlan.PlanState.COMPLETE)
        self.assertEqual(self.plan.completed_by, self.user)
        self.assertIsNotNone(self.plan.completed_at)

    def test_reopen_plan_steps_back_from_complete_to_production(self):
        services.complete_plan(self.plan, self.user)
        services.reopen_plan(self.plan)
        self.assertEqual(self.plan.state, PrepPlan.PlanState.PRODUCTION)
        self.assertIsNone(self.plan.completed_by)
        self.assertIsNone(self.plan.completed_at)

    def test_reopen_plan_steps_back_from_production_to_draft(self):
        services.reopen_plan(self.plan)
        self.assertEqual(self.plan.state, PrepPlan.PlanState.DRAFT)

    def test_task_tap_is_noop_when_complete(self):
        self.task.status = PrepTask.TaskStatus.PLANNED
        self.task.save()
        services.complete_plan(self.plan, self.user)

        result = services.task_tap(self.task.id, self.user)
        self.assertEqual(result.status, PrepTask.TaskStatus.PLANNED)
        self.assertIsNone(result.assignee_id)

    def test_task_claim_is_noop_when_complete(self):
        services.complete_plan(self.plan, self.user)
        result = services.task_claim(self.task.id, self.user)
        self.assertIsNone(result.assignee_id)

    def test_set_task_note_is_noop_when_complete(self):
        services.complete_plan(self.plan, self.user)
        result = services.set_task_note(self.task.id, "too late", self.user)
        self.assertEqual(result.daily_note, "")


class PlanCompleteViewTests(TestCase):
    """
    Covers the "Close Prep List" flow end to end: warns (but still allows)
    closing an unfinished list, and locks the sheet's HTMX controls once
    the plan is COMPLETE.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000006", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component = Component.objects.create(team=self.team, name="Broth")
        DishComponent.objects.create(dish=self.dish, component=self.component, order=1)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 1, 1), self.user)
        services.finalize_plan(self.plan, self.user)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_sheet_shows_pending_tasks_when_not_fully_done(self):
        response = self.client.get(reverse("planning:plan_sheet", args=[self.plan.service_date]))
        self.assertContains(response, "Prep list isn't finished yet")
        self.assertContains(response, "Broth")
        self.assertContains(response, "Close Anyway")

    def test_sheet_shows_ready_to_complete_when_fully_done(self):
        task = PrepTask.objects.get(plan=self.plan, dish_component__component=self.component)
        task.status = PrepTask.TaskStatus.DONE
        task.save()

        response = self.client.get(reverse("planning:plan_sheet", args=[self.plan.service_date]))
        self.assertContains(response, "All 1 tasks are done")
        self.assertNotContains(response, "Close Anyway")

    def test_completing_unfinished_plan_is_allowed(self):
        url = reverse("planning:plan_complete", args=[self.plan.service_date])
        response = self.client.post(url)
        self.assertRedirects(response, reverse("planning:plan_sheet", args=[self.plan.service_date]))

        self.plan.refresh_from_db()
        self.assertEqual(self.plan.state, PrepPlan.PlanState.COMPLETE)

    def test_completed_sheet_hides_interactive_controls(self):
        task = PrepTask.objects.get(plan=self.plan, dish_component__component=self.component)
        self.client.post(reverse("planning:plan_complete", args=[self.plan.service_date]))

        response = self.client.get(reverse("planning:plan_sheet", args=[self.plan.service_date]))
        content = response.content.decode()

        self.assertIn("task-main-locked", content)
        self.assertNotIn(reverse("planning:task_tap", args=[task.id]), content)
        self.assertNotIn(reverse("planning:task_claim", args=[task.id]), content)
        self.assertNotContains(response, "id=\"completeModal\"")

    def test_tapping_a_task_refreshes_the_stale_complete_modal_via_oob_swap(self):
        # Regression: the completeModal is rendered once with the full page.
        # Tapping a task only re-renders that row + progress section via
        # HTMX; the modal must be refreshed the same way (out-of-band) or it
        # keeps showing the pending-tasks list after everything is done.
        task = PrepTask.objects.get(plan=self.plan, dish_component__component=self.component)

        response = self.client.post(reverse("planning:task_tap", args=[task.id]))
        self.assertContains(response, "Prep list isn't finished yet")

        response = self.client.post(reverse("planning:task_tap", args=[task.id]))
        content = response.content.decode()
        self.assertIn("All 1 tasks are done", content)
        self.assertNotIn("Still pending", content)


class PlanBuilderSheetRoutingTests(TestCase):
    """
    Builder owns DRAFT exclusively, Sheet owns PRODUCTION/COMPLETE
    exclusively — each redirects to the other when it doesn't own the
    plan's current state. Also covers Builder's auto-resync on every GET,
    which replaced the standalone "Rebuild" action entirely.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000007", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component = Component.objects.create(team=self.team, name="Broth")
        DishComponent.objects.create(dish=self.dish, component=self.component, order=1)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 1, 1), self.user)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_sheet_redirects_to_builder_while_draft(self):
        response = self.client.get(reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))
        self.assertRedirects(response, reverse("planning:plan_builder", args=[str(self.plan.service_date)]))

    def test_builder_redirects_to_sheet_once_in_production(self):
        services.finalize_plan(self.plan, self.user)
        response = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertRedirects(response, reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))

    def test_builder_redirects_to_sheet_once_complete(self):
        services.finalize_plan(self.plan, self.user)
        services.complete_plan(self.plan, self.user)
        response = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertRedirects(response, reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))

    def test_builder_auto_resyncs_on_get_with_no_explicit_rebuild(self):
        new_component = Component.objects.create(team=self.team, name="Egg")
        DishComponent.objects.create(dish=self.dish, component=new_component, order=2)

        response = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertContains(response, "Egg")
        self.assertTrue(
            PrepTask.objects.filter(plan=self.plan, dish_component__component=new_component).exists()
        )

    def test_plan_refresh_url_no_longer_exists(self):
        with self.assertRaises(NoReverseMatch):
            reverse("planning:plan_refresh", args=[str(self.plan.service_date)])


class PrepTaskOriginConstraintTests(TestCase):
    """
    A PrepTask must have exactly one origin (dish_component, component,
    recipe, or manual_label) — enforced at the DB level so a bug can't
    silently create an ambiguous or blank task.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000020", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)
        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 2, 1), self.user)

    def test_zero_origins_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PrepTask.objects.create(plan=self.plan)

    def test_multiple_origins_rejected(self):
        dish = Dish.objects.create(team=self.team, name="Ramen")
        component = Component.objects.create(team=self.team, name="Broth")
        dc = DishComponent.objects.create(dish=dish, component=component, order=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PrepTask.objects.create(plan=self.plan, dish_component=dc, manual_label="also manual")

    def test_exactly_one_origin_allowed(self):
        task = PrepTask.objects.create(plan=self.plan, manual_label="Clean the fish")
        self.assertEqual(task.origin, "adhoc_manual")
        self.assertEqual(task.display_name, "Clean the fish")


class AdHocTaskServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000021", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)
        self.other_team = Team.objects.create(name="Other Kitchen", join_code="000022", created_by=self.user)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 2, 1), self.user)
        self.recipe = Recipe.objects.create(team=self.team, name="Base Broth", ingredients_text="water")

    def test_add_manual_task(self):
        task = services.add_manual_task(self.plan, "  Clean the fish  ", self.user)
        self.assertEqual(task.manual_label, "Clean the fish")
        self.assertEqual(task.origin, "adhoc_manual")

    def test_add_manual_task_requires_a_label(self):
        with self.assertRaises(ValueError):
            services.add_manual_task(self.plan, "   ", self.user)

    def test_add_recipe_task(self):
        task = services.add_recipe_task(self.plan, self.recipe, self.user)
        self.assertEqual(task.recipe_id, self.recipe.id)
        self.assertEqual(task.origin, "adhoc_recipe")
        self.assertEqual(task.linked_recipe_id, self.recipe.id)

    def test_add_recipe_task_rejects_recipe_from_another_team(self):
        other_recipe = Recipe.objects.create(team=self.other_team, name="Foreign", ingredients_text="x")
        with self.assertRaises(PermissionError):
            services.add_recipe_task(self.plan, other_recipe, self.user)

    def test_cannot_add_tasks_outside_draft(self):
        services.finalize_plan(self.plan, self.user)
        with self.assertRaises(ValueError):
            services.add_manual_task(self.plan, "Too late", self.user)

    def test_remove_adhoc_task(self):
        task = services.add_manual_task(self.plan, "Clean the fish", self.user)
        services.remove_adhoc_task(task.id, self.user)
        self.assertFalse(PrepTask.objects.filter(pk=task.pk).exists())

    def test_remove_adhoc_task_rejects_dish_sourced_task(self):
        dish = Dish.objects.create(team=self.team, name="Ramen")
        component = Component.objects.create(team=self.team, name="Broth")
        DishComponent.objects.create(dish=dish, component=component, order=1)
        self.plan.plan_dishes.create(dish=dish, order=1)
        services.build_placeholders_hard_reset(self.plan)
        dish_task = PrepTask.objects.get(plan=self.plan, dish_component__component=component)

        with self.assertRaises(ValueError):
            services.remove_adhoc_task(dish_task.id, self.user)


class BuildPlaceholdersAdHocAndStandaloneTests(TestCase):
    """
    build_placeholders_hard_reset must sync standalone-active components the
    same incremental way as dish components (preserving state), matching
    what BuildPlaceholdersSyncTests already verifies for dish-driven tasks —
    and must never touch ad hoc tasks at all (no "Rebuild" action exists
    anymore; only the user's own "Remove" click deletes those).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000023", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)
        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 2, 1), self.user)

    def test_sync_never_touches_manual_and_recipe_adhoc_tasks(self):
        recipe = Recipe.objects.create(team=self.team, name="Base Broth", ingredients_text="water")
        services.add_manual_task(self.plan, "Clean the fish", self.user)
        services.add_recipe_task(self.plan, recipe, self.user)
        self.assertEqual(PrepTask.objects.filter(plan=self.plan).count(), 2)

        services.build_placeholders_hard_reset(self.plan)
        self.assertEqual(PrepTask.objects.filter(plan=self.plan).count(), 2)

    def test_standalone_component_gets_a_task_without_any_dish_selection(self):
        standalone = Component.objects.create(team=self.team, name="Deep Clean", standalone_active=True)
        services.build_placeholders_hard_reset(self.plan)

        task = PrepTask.objects.get(plan=self.plan, component=standalone)
        self.assertEqual(task.origin, "standalone")
        self.assertEqual(task.display_name, "Deep Clean")

    def test_standalone_task_state_survives_rebuild(self):
        standalone = Component.objects.create(team=self.team, name="Deep Clean", standalone_active=True)
        services.build_placeholders_hard_reset(self.plan)
        task = PrepTask.objects.get(plan=self.plan, component=standalone)
        task.status = PrepTask.TaskStatus.DONE
        task.daily_note = "done at noon"
        task.save()

        services.build_placeholders_hard_reset(self.plan)

        task.refresh_from_db()
        self.assertEqual(task.status, PrepTask.TaskStatus.DONE)
        self.assertEqual(task.daily_note, "done at noon")

    def test_turning_standalone_off_removes_its_task_on_next_rebuild(self):
        standalone = Component.objects.create(team=self.team, name="Deep Clean", standalone_active=True)
        services.build_placeholders_hard_reset(self.plan)
        self.assertTrue(PrepTask.objects.filter(plan=self.plan, component=standalone).exists())

        standalone.standalone_active = False
        standalone.save()
        services.build_placeholders_hard_reset(self.plan)

        self.assertFalse(PrepTask.objects.filter(plan=self.plan, component=standalone).exists())

    def test_standalone_component_already_attached_to_a_dish_is_not_duplicated(self):
        dish = Dish.objects.create(team=self.team, name="Ramen")
        component = Component.objects.create(team=self.team, name="Broth", standalone_active=True)
        DishComponent.objects.create(dish=dish, component=component, order=1)
        self.plan.plan_dishes.create(dish=dish, order=1)

        services.build_placeholders_hard_reset(self.plan)

        # Only the dish-driven task should exist, not a second standalone one.
        self.assertEqual(PrepTask.objects.filter(plan=self.plan, component=component).count(), 0)
        self.assertEqual(
            PrepTask.objects.filter(plan=self.plan, dish_component__component=component).count(), 1
        )


class AdHocTaskViewTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000024", created_by=self.owner)
        TeamMembership.objects.create(user=self.owner, team=self.team, role=TeamMembership.Role.OWNER)

        self.member = User.objects.create_user(username="member", password="x")
        TeamMembership.objects.create(user=self.member, team=self.team, role=TeamMembership.Role.MEMBER)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 2, 1), self.owner)
        self.recipe = Recipe.objects.create(team=self.team, name="Base Broth", ingredients_text="water")

        self.client.force_login(self.member)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def _formset_payload(self, rows):
        data = {
            "form-TOTAL_FORMS": str(len(rows)),
            "form-INITIAL_FORMS": "0",
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
        }
        for i, row in enumerate(rows):
            data[f"form-{i}-label"] = row.get("label", "")
            data[f"form-{i}-recipe"] = row.get("recipe", "")
        return data

    def test_plain_member_can_add_multiple_adhoc_rows_in_one_submit(self):
        payload = self._formset_payload([
            {"label": "Clean the fish"},
            {"recipe": self.recipe.id},
            {},  # blank row from clicking "+" without filling it in
        ])
        response = self.client.post(
            reverse("planning:task_add_adhoc", args=[str(self.plan.service_date)]), payload
        )
        self.assertRedirects(response, reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertEqual(PrepTask.objects.filter(plan=self.plan).count(), 2)

    def test_plain_member_can_remove_own_adhoc_task(self):
        task = services.add_manual_task(self.plan, "Clean the fish", self.member)
        response = self.client.post(reverse("planning:task_remove_adhoc", args=[task.id]))
        self.assertRedirects(response, reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertFalse(PrepTask.objects.filter(pk=task.pk).exists())

    def test_row_with_both_label_and_recipe_is_rejected(self):
        payload = self._formset_payload([{"label": "Clean the fish", "recipe": self.recipe.id}])
        response = self.client.post(
            reverse("planning:task_add_adhoc", args=[str(self.plan.service_date)]), payload
        )
        self.assertRedirects(response, reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertEqual(PrepTask.objects.filter(plan=self.plan).count(), 0)


class BuilderAdHocWidgetTests(TestCase):
    """
    The Builder screen ("Build Prep List") is DRAFT's only screen now: it
    shows the manual-or-recipe widget plus the generated task groups, and
    add/remove always lands back on the Builder (there's nowhere else for a
    DRAFT plan to go).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000098", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)
        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

        self.plan = services.get_or_create_draft_plan(
            self.team, datetime.date(2026, 3, 1), self.user
        )

    def test_builder_renders_adhoc_widget(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("Add a one-off prep task", content)
        self.assertIn("data-formset-add=\"builder-adhoc-rows\"", content)

    def test_add_task_lands_back_on_builder_and_shows_up_there(self):
        resp = self.client.post(
            reverse("planning:task_add_adhoc", args=[str(self.plan.service_date)]),
            {
                "form-TOTAL_FORMS": "1",
                "form-INITIAL_FORMS": "0",
                "form-MIN_NUM_FORMS": "0",
                "form-MAX_NUM_FORMS": "1000",
                "form-0-label": "Clean the fish",
                "form-0-recipe": "",
            },
        )
        self.assertRedirects(resp, reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertTrue(PrepTask.objects.filter(plan=self.plan, manual_label="Clean the fish").exists())

        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertContains(resp, "Clean the fish")

    def test_remove_task_lands_back_on_builder(self):
        task = services.add_manual_task(self.plan, "Clean the fish", self.user)
        resp = self.client.post(reverse("planning:task_remove_adhoc", args=[task.id]))
        self.assertRedirects(resp, reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertFalse(PrepTask.objects.filter(pk=task.pk).exists())


class BuilderTaskRowIsASelectionCheckboxTests(TestCase):
    """
    The Builder's task row is a decision ("do I need to prep this today?"),
    not a mockup of the production sheet's done-tracking row. Tapping in
    DRAFT only ever moves NONE<->PLANNED (never DONE), so the row must show
    a distinct selected/unselected glyph for that instead of always showing
    the empty box — and DRAFT has no business showing the "daily note"
    editor, which is a PRODUCTION/kitchen-floor concern.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000099", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component = Component.objects.create(team=self.team, name="Lemon grass")
        DishComponent.objects.create(dish=self.dish, component=self.component, order=1)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 3, 1), self.user)
        self.task = PrepTask.objects.get(plan=self.plan, dish_component__component=self.component)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_new_task_defaults_to_checked_and_needed(self):
        # Most components need prep every day, so the Builder starts
        # everything selected — the cook unchecks the exceptions instead of
        # re-checking the whole list from scratch each day.
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertEqual(self.task.status, PrepTask.TaskStatus.PLANNED)
        self.assertContains(resp, "☑")
        self.assertNotContains(resp, "☐")

    def test_tapping_a_checked_task_excludes_it_showing_empty_box(self):
        resp = self.client.post(reverse("planning:task_tap", args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, PrepTask.TaskStatus.NONE)
        content = resp.content.decode()
        self.assertIn("☐", content)
        self.assertNotIn("☑", content)
        self.assertNotIn("✅", content)

    def test_stale_done_status_from_a_reopened_plan_shows_checked_not_stuck(self):
        # Regression: reopen_plan() steps PRODUCTION -> DRAFT without
        # touching task status, so a task finished during a prior
        # PRODUCTION run can arrive in DRAFT still marked DONE. The
        # checkbox must show it as checked (not the empty box a stuck
        # NONE<->PLANNED toggle would show), and tapping it must actually
        # do something instead of silently no-op'ing on the unexpected value.
        self.task.status = PrepTask.TaskStatus.DONE
        self.task.save(update_fields=["status"])

        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        content = resp.content.decode()
        self.assertIn("☑", content)
        self.assertNotIn("text-decoration-line-through", content)

        self.client.post(reverse("planning:task_tap", args=[self.task.id]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, PrepTask.TaskStatus.NONE)

    def test_note_editor_is_absent_from_draft_rows(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertNotContains(resp, "task-note-row")
        self.assertNotContains(resp, "Daily note (temporary)")

    def test_note_editor_appears_once_sent_to_kitchen(self):
        services.finalize_plan(self.plan, self.user)
        resp = self.client.get(reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))
        self.assertContains(resp, "task-note-row")


class UncheckedTasksAreExcludedFromTheKitchenTests(TestCase):
    """
    The whole point of the Builder's checkbox: unchecking a component
    ("already have it, don't need to prep it today") must actually keep it
    off the finished PRODUCTION sheet — not just look unchecked and still
    show up for the cooks like every other pending task.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000100", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.lime = Component.objects.create(team=self.team, name="Lime Wedges")
        self.lemongrass = Component.objects.create(team=self.team, name="Lemongrass")
        DishComponent.objects.create(dish=self.dish, component=self.lime, order=1)
        DishComponent.objects.create(dish=self.dish, component=self.lemongrass, order=2)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 3, 1), self.user)
        self.lime_task = PrepTask.objects.get(plan=self.plan, dish_component__component=self.lime)
        self.lemongrass_task = PrepTask.objects.get(plan=self.plan, dish_component__component=self.lemongrass)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_unchecked_component_is_dropped_on_finalize_checked_one_survives(self):
        # Both start PLANNED (checked) by default; uncheck lemongrass only.
        self.client.post(reverse("planning:task_tap", args=[self.lemongrass_task.id]))

        services.finalize_plan(self.plan, self.user)

        self.assertTrue(PrepTask.objects.filter(pk=self.lime_task.pk).exists())
        self.assertFalse(PrepTask.objects.filter(pk=self.lemongrass_task.pk).exists())

    def test_surviving_task_resets_to_none_for_clean_production_claim_flow(self):
        services.finalize_plan(self.plan, self.user)
        self.lime_task.refresh_from_db()
        self.assertEqual(self.lime_task.status, PrepTask.TaskStatus.NONE)

        # First tap in PRODUCTION should claim + move to PLANNED, not
        # jump straight to DONE.
        self.client.post(reverse("planning:task_claim", args=[self.lime_task.id]))
        self.lime_task.refresh_from_db()
        self.assertEqual(self.lime_task.status, PrepTask.TaskStatus.PLANNED)

    def test_unchecked_component_never_appears_on_the_kitchen_sheet(self):
        self.client.post(reverse("planning:task_tap", args=[self.lemongrass_task.id]))
        services.finalize_plan(self.plan, self.user)

        resp = self.client.get(reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))
        self.assertContains(resp, "Lime Wedges")
        self.assertNotContains(resp, "Lemongrass")

    def test_unchecked_ad_hoc_task_is_also_dropped_on_finalize(self):
        task = services.add_manual_task(self.plan, "Chop extra scallions", self.user)
        self.client.post(reverse("planning:task_tap", args=[task.id]))

        services.finalize_plan(self.plan, self.user)

        self.assertFalse(PrepTask.objects.filter(pk=task.pk).exists())

    def test_leaving_everything_checked_carries_the_whole_list_through(self):
        services.finalize_plan(self.plan, self.user)
        self.assertEqual(PrepTask.objects.filter(plan=self.plan).count(), 2)


class PrepItemsNavigationMovedTests(TestCase):
    """Prep Items lives under Prep Lists now, not Menu Setup."""

    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000097", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)
        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_prep_items_link_on_plan_list_not_dish_list(self):
        prep_items_url = reverse("menu:component_list")

        resp = self.client.get(reverse("planning:plan_list"))
        self.assertContains(resp, prep_items_url)

        resp = self.client.get(reverse("menu:dish_list"))
        self.assertNotContains(resp, prep_items_url)


class AdHocTasksSurviveSaveAndFinalizeTests(TestCase):
    """
    Regression: build_placeholders_hard_reset is also called by "Save Draft",
    "Send to Kitchen", every GET of the Builder, and by editing a dish's
    prep items from Menu Setup (to sync any DRAFT plan using that dish) —
    none of those should ever wipe one-off tasks; only the user's own
    "Remove" click does.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000040", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)
        self.dish = Dish.objects.create(team=self.team, name="Ramen")

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 3, 10), self.user)
        services.add_manual_task(self.plan, "Clean the fish", self.user)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def _adhoc_count(self):
        return PrepTask.objects.filter(plan=self.plan, dish_component__isnull=True, component__isnull=True).count()

    def test_save_draft_preserves_adhoc_tasks(self):
        self.assertEqual(self._adhoc_count(), 1)
        response = self.client.post(
            reverse("planning:plan_builder", args=[str(self.plan.service_date)]),
            {"action": "save", "dishes": [self.dish.id]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._adhoc_count(), 1)

    def test_finalize_preserves_adhoc_tasks(self):
        response = self.client.post(
            reverse("planning:plan_builder", args=[str(self.plan.service_date)]),
            {"action": "finalize", "dishes": [self.dish.id]},
        )
        self.assertEqual(response.status_code, 302)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.state, PrepPlan.PlanState.PRODUCTION)
        self.assertEqual(self._adhoc_count(), 1)

    def test_editing_dish_prep_items_from_menu_preserves_adhoc_tasks(self):
        # get_or_create_draft_plan already auto-selected this dish (it's
        # active) via ensure_default_plandishes, so no need to add it again.
        component = Component.objects.create(team=self.team, name="Broth")

        self.client.post(reverse("menu:dish_components_edit", args=[self.dish.pk]), {
            "dish_components-TOTAL_FORMS": "1",
            "dish_components-INITIAL_FORMS": "0",
            "dish_components-MIN_NUM_FORMS": "0",
            "dish_components-MAX_NUM_FORMS": "1000",
            "dish_components-0-component": component.id,
            "dish_components-0-order": 1,
            "dish_components-0-template_note": "",
        })
        self.assertEqual(self._adhoc_count(), 1)


class RecurringItemsInBuilderTests(TestCase):
    """
    Recurring (standalone_active) prep items show alongside the dish
    checkboxes in the Builder, so they're not invisible until they show up
    already-generated on the sheet. Unchecking one there is a shortcut for
    the same can_manage_menu-gated toggle in the Prep Items catalog: it
    turns standalone_active off globally, not just for this one plan.
    """

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000050", created_by=self.owner)
        TeamMembership.objects.create(user=self.owner, team=self.team, role=TeamMembership.Role.OWNER)

        self.member = User.objects.create_user(username="member", password="x")
        TeamMembership.objects.create(user=self.member, team=self.team, role=TeamMembership.Role.MEMBER)

        self.standalone = Component.objects.create(team=self.team, name="Deep Clean", standalone_active=True)
        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 3, 15), self.owner)

        self.client.force_login(self.owner)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_builder_shows_recurring_item_as_checked_by_default(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertContains(resp, "Recurring prep items")
        self.assertContains(resp, "Deep Clean")
        # ModelMultipleChoiceField renders selected options with `checked`.
        self.assertContains(resp, f'id="id_standalone_components_0" checked')

    def test_unchecking_recurring_item_turns_it_off_globally(self):
        response = self.client.post(
            reverse("planning:plan_builder", args=[str(self.plan.service_date)]),
            {"action": "save", "dishes": []},  # standalone_components omitted = unchecked
        )
        self.assertEqual(response.status_code, 302)
        self.standalone.refresh_from_db()
        self.assertFalse(self.standalone.standalone_active)

    def test_leaving_it_checked_keeps_it_recurring(self):
        response = self.client.post(
            reverse("planning:plan_builder", args=[str(self.plan.service_date)]),
            {"action": "save", "dishes": [], "standalone_components": [self.standalone.id]},
        )
        self.assertEqual(response.status_code, 302)
        self.standalone.refresh_from_db()
        self.assertTrue(self.standalone.standalone_active)

    def test_member_without_menu_permission_cannot_turn_it_off(self):
        membership = TeamMembership.objects.get(user=self.member, team=self.team)
        membership.can_manage_menu = False
        membership.save()

        self.client.force_login(self.member)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

        # Sees it as a read-only list, not a checkbox, when lacking permission.
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertContains(resp, "Deep Clean")
        self.assertNotContains(resp, 'name="standalone_components"')

        # And the server ignores any attempt to turn it off anyway.
        self.client.post(
            reverse("planning:plan_builder", args=[str(self.plan.service_date)]),
            {"action": "save", "dishes": []},
        )
        self.standalone.refresh_from_db()
        self.assertTrue(self.standalone.standalone_active)


class MobileTouchUsabilityTests(TestCase):
    """
    Regression coverage for the mobile/tablet touch pass: a back link off
    the Builder/Sheet, primary actions reachable in a bottom bar without
    depending on DOM nesting inside the dish-selection form, the list/cards
    view toggle markup, and the task-control fix that stops a near-miss tap
    on Claim/Remove from instead firing the row's own tap-to-toggle.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000101", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component = Component.objects.create(team=self.team, name="Broth")
        DishComponent.objects.create(dish=self.dish, component=self.component, order=1)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 3, 1), self.user)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_builder_has_a_back_link_to_the_plan_list(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertContains(resp, reverse("planning:plan_list"))
        self.assertContains(resp, "btn-back")

    def test_sheet_has_a_back_link_to_the_plan_list(self):
        services.finalize_plan(self.plan, self.user)
        resp = self.client.get(reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))
        self.assertContains(resp, reverse("planning:plan_list"))
        self.assertContains(resp, "btn-back")

    def test_builder_primary_actions_live_in_the_sticky_bar_outside_the_form(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        content = resp.content.decode()
        self.assertIn('class="prep-sticky-actions"', content)
        # Save Draft is a native submit button placed outside <form
        # id="builder-form">, so it must reference it via form=.
        self.assertIn('form="builder-form"', content)
        sticky_html = content.split('class="prep-sticky-actions"')[1]
        self.assertIn("Save Draft", sticky_html)
        self.assertIn("Send to Kitchen", sticky_html)

    def test_sheet_primary_actions_live_in_the_sticky_bar(self):
        services.finalize_plan(self.plan, self.user)
        resp = self.client.get(reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))
        content = resp.content.decode()
        sticky_html = content.split('class="prep-sticky-actions"')[1]
        self.assertIn("Close Prep List", sticky_html)
        self.assertIn("Reopen for Editing", sticky_html)

    def test_save_draft_still_works_from_outside_the_form_via_form_attribute(self):
        # End-to-end proof the form= association actually submits correctly
        # now that the button lives outside <form id="builder-form">.
        resp = self.client.post(
            reverse("planning:plan_builder", args=[str(self.plan.service_date)]),
            {"action": "save", "dishes": [self.dish.id]},
        )
        self.assertRedirects(resp, reverse("planning:plan_builder", args=[str(self.plan.service_date)]))

    def test_erase_action_moved_below_the_task_list_away_from_send_to_kitchen(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        content = resp.content.decode()
        # Regression: Erase used to sit directly under Send to Kitchen in
        # the same card, one fat-fingered tap away from a destructive
        # action. It now lives in its own danger-zone section, outside the
        # sticky bar entirely.
        sticky_html = content.split('class="prep-sticky-actions"')[1]
        self.assertNotIn("Erase Prep List", sticky_html)
        self.assertIn("Erase Prep List", content)

    def test_task_main_right_stays_part_of_the_row_tap_zone(self):
        # Regression: an earlier attempt at this fix excluded the whole
        # task-main-right band (Claim/Unclaim, Remove, assignee badge) from
        # the row's tap-to-toggle, not just the button inside it. That
        # turned most of the row into a dead zone on mobile — tapping
        # anywhere near the button but not exactly on it did nothing, which
        # read as "the toggle doesn't respond". task-main-right must NOT
        # carry task-control itself; only the individual interactive
        # control (the button/form) inside it should be excluded, so
        # tapping the surrounding blank space still advances the task.
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertNotContains(resp, 'class="task-main-right task-control"')
        self.assertContains(resp, '<div class="task-main-right">')

    def test_task_groups_render_the_list_cards_view_toggle(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        content = resp.content.decode()
        self.assertIn('data-view-btn="list"', content)
        self.assertIn('data-view-btn="cards"', content)
        self.assertIn("data-task-view-container", content)

    def test_sheet_also_renders_the_view_toggle(self):
        services.finalize_plan(self.plan, self.user)
        resp = self.client.get(reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))
        self.assertContains(resp, "data-task-view-container")


class CompactCardsAndJumpNavTests(TestCase):
    """
    The Builder's cards are checkbox+name only (no note/claim), so they can
    pack tighter for a "whole day at a glance" overview; the Sheet's cards
    carry more per item and stay less dense. A jump nav of dish-name pills
    lets you skip straight to a section on a long prep list instead of
    scrolling through everything in order.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000102", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish_a = Dish.objects.create(team=self.team, name="Ramen")
        self.dish_b = Dish.objects.create(team=self.team, name="Pad Thai")
        self.component = Component.objects.create(team=self.team, name="Broth")
        DishComponent.objects.create(dish=self.dish_a, component=self.component, order=1)
        DishComponent.objects.create(dish=self.dish_b, component=self.component, order=1)

        self.plan = services.get_or_create_draft_plan(self.team, datetime.date(2026, 3, 1), self.user)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_builder_cards_are_scoped_as_the_builder_screen(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertContains(resp, 'data-screen="builder"')

    def test_sheet_cards_are_scoped_as_the_sheet_screen(self):
        services.finalize_plan(self.plan, self.user)
        resp = self.client.get(reverse("planning:plan_sheet", args=[str(self.plan.service_date)]))
        self.assertContains(resp, 'data-screen="sheet"')

    def test_jump_nav_appears_with_multiple_dish_groups(self):
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        content = resp.content.decode()
        self.assertIn("dish-jump-nav", content)
        self.assertIn(f'href="#dish-{self.dish_a.id}"', content)
        self.assertIn(f'href="#dish-{self.dish_b.id}"', content)
        self.assertIn(f'id="dish-{self.dish_a.id}"', content)
        self.assertIn(f'id="dish-{self.dish_b.id}"', content)

    def test_jump_nav_is_absent_with_a_single_dish_and_no_extras(self):
        services.set_plandishes(self.plan, [self.dish_a.id])
        services.build_placeholders_hard_reset(self.plan)
        resp = self.client.get(reverse("planning:plan_builder", args=[str(self.plan.service_date)]))
        self.assertNotContains(resp, "dish-jump-nav")
