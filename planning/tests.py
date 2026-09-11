import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Team, TeamMembership
from menu.models import Component, Dish, DishComponent
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
        self.component_a = Component.objects.create(team=self.team, name="Broth", type=Component.ComponentType.SIMPLE_PREP)
        self.component_b = Component.objects.create(team=self.team, name="Noodles", type=Component.ComponentType.SIMPLE_PREP)
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
        component_c = Component.objects.create(team=self.team, name="Egg", type=Component.ComponentType.SIMPLE_PREP)
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
        self.component = Component.objects.create(team=self.team, name="Broth", type=Component.ComponentType.SIMPLE_PREP)
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
    Covers the "Complete Prep List" flow end to end: warns (but still allows)
    completing an unfinished list, and locks the sheet's HTMX controls once
    the plan is COMPLETE.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000006", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component = Component.objects.create(team=self.team, name="Broth", type=Component.ComponentType.SIMPLE_PREP)
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
        self.assertContains(response, "Complete Anyway")

    def test_sheet_shows_ready_to_complete_when_fully_done(self):
        task = PrepTask.objects.get(plan=self.plan, dish_component__component=self.component)
        task.status = PrepTask.TaskStatus.DONE
        task.save()

        response = self.client.get(reverse("planning:plan_sheet", args=[self.plan.service_date]))
        self.assertContains(response, "All 1 tasks are done")
        self.assertNotContains(response, "Complete Anyway")

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
