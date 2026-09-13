import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Team, TeamMembership
from planning import services as planning_services
from planning.models import PrepPlan, PrepTask
from .models import Component, Dish, DishComponent, Recipe

User = get_user_model()


class DuplicateNameFormValidationTests(TestCase):
    """
    Dish/Recipe/Component are unique per (team, name), but `team` isn't a
    form field (it's set server-side from request.team). Since the forms
    didn't validate that constraint themselves, a duplicate name used to
    reach obj.save() and crash with an unhandled IntegrityError (500)
    instead of showing a form error.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000011", created_by=self.user)
        TeamMembership.objects.create(
            user=self.user, team=self.team, role=TeamMembership.Role.OWNER,
            can_manage_menu=True, can_manage_recipes=True,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_dish_create_duplicate_name_shows_error_instead_of_crashing(self):
        Dish.objects.create(team=self.team, name="Ramen")
        response = self.client.post(reverse("menu:dish_create"), {"name": "Ramen", "is_active": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
        self.assertEqual(Dish.objects.filter(team=self.team, name="Ramen").count(), 1)

    def test_dish_update_keeping_its_own_name_is_allowed(self):
        dish = Dish.objects.create(team=self.team, name="Ramen")
        response = self.client.post(
            reverse("menu:dish_edit", args=[dish.pk]), {"name": "Ramen", "is_active": "on"}
        )
        self.assertRedirects(response, reverse("menu:dish_list"))

    def test_recipe_create_duplicate_name_shows_error_instead_of_crashing(self):
        Recipe.objects.create(team=self.team, name="Base Broth", ingredients_text="water")
        response = self.client.post(
            reverse("menu:recipe_create"),
            {"name": "Base Broth", "ingredients_text": "salt", "steps_text": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")

    def test_component_create_duplicate_name_shows_error_instead_of_crashing(self):
        Component.objects.create(team=self.team, name="Broth", type=Component.ComponentType.SIMPLE_PREP)
        response = self.client.post(
            reverse("menu:component_create"),
            {"name": "Broth", "type": Component.ComponentType.SIMPLE_PREP, "spec_text": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")


class DishListSearchAndPaginationTests(TestCase):
    """
    dish_list (and recipe_list/component_list, which share
    SearchablePaginatedListMixin) used to list everything with no search or
    paging (PREPPLAN_NOTES.md #3).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000010", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        for i in range(25):
            Dish.objects.create(team=self.team, name=f"Dish {i:02d}")
        Dish.objects.create(team=self.team, name="Ramen Bowl")

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_list_is_paginated(self):
        response = self.client.get(reverse("menu:dish_list"))
        self.assertEqual(len(response.context["dishes"]), 20)
        self.assertTrue(response.context["is_paginated"])

        response = self.client.get(reverse("menu:dish_list") + "?page=2")
        self.assertEqual(len(response.context["dishes"]), 6)

    def test_search_filters_by_name(self):
        response = self.client.get(reverse("menu:dish_list") + "?q=ramen")
        names = [d.name for d in response.context["dishes"]]
        self.assertEqual(names, ["Ramen Bowl"])


class TeamPermissionRequiredDecoratorTests(TestCase):
    """
    toggle_dish_active / edit_dish_components / remove_dish_component share
    @team_permission_required("can_manage_menu") instead of each repeating
    the membership/role check inline.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000007", created_by=self.user)
        TeamMembership.objects.create(
            user=self.user, team=self.team, role=TeamMembership.Role.MEMBER, can_manage_menu=False
        )
        self.dish = Dish.objects.create(team=self.team, name="Ramen")

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_member_without_flag_is_redirected_away(self):
        response = self.client.post(reverse("menu:dish_toggle_active", args=[self.dish.pk]))
        self.assertRedirects(response, reverse("home:index"))
        self.dish.refresh_from_db()
        self.assertTrue(self.dish.is_active)

    def test_member_with_flag_is_allowed(self):
        membership = TeamMembership.objects.get(user=self.user, team=self.team)
        membership.can_manage_menu = True
        membership.save()

        response = self.client.post(reverse("menu:dish_toggle_active", args=[self.dish.pk]))
        self.assertRedirects(response, reverse("menu:dish_list"))
        self.dish.refresh_from_db()
        self.assertFalse(self.dish.is_active)


class MenuFormErrorsVisibleTests(TestCase):
    """
    Regression test for PREPPLAN_NOTES.md #3 ("Errores de formulario
    invisibles"): dish_form.html rendered `{{ form.name }}` with no
    `{{ form.name.errors }}`, so a rejected submission looked like nothing
    happened.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000009", created_by=self.user)
        TeamMembership.objects.create(
            user=self.user, team=self.team, role=TeamMembership.Role.OWNER, can_manage_menu=True
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_dish_create_missing_name_shows_field_error(self):
        response = self.client.post(reverse("menu:dish_create"), {"is_active": "on"})
        self.assertContains(response, "This field is required")


class EditDishComponentsPreservesTaskStateTests(TestCase):
    """
    Regression test for the bug where editing a dish's components silently
    wiped status/assignee/daily_note for every task in every draft plan that
    used that dish, with no warning to the user (see PREPPLAN_NOTES.md #1).
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000002", created_by=self.user)
        TeamMembership.objects.create(
            user=self.user, team=self.team, role=TeamMembership.Role.OWNER, can_manage_menu=True
        )

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component_a = Component.objects.create(team=self.team, name="Broth", type=Component.ComponentType.SIMPLE_PREP)
        self.component_b = Component.objects.create(team=self.team, name="Noodles", type=Component.ComponentType.SIMPLE_PREP)
        self.dc_a = DishComponent.objects.create(dish=self.dish, component=self.component_a, order=1)
        self.dc_b = DishComponent.objects.create(dish=self.dish, component=self.component_b, order=2)

        self.plan = planning_services.get_or_create_draft_plan(
            self.team, datetime.date(2026, 1, 1), self.user
        )

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_editing_one_component_keeps_other_tasks_status_and_notes(self):
        task_a = PrepTask.objects.get(plan=self.plan, dish_component=self.dc_a)
        task_a.status = PrepTask.TaskStatus.DONE
        task_a.assignee = self.user
        task_a.daily_note = "quedó justo"
        task_a.save()

        url = reverse("menu:dish_components_edit", args=[self.dish.pk])
        response = self.client.post(url, {
            "dish_components-TOTAL_FORMS": "2",
            "dish_components-INITIAL_FORMS": "2",
            "dish_components-MIN_NUM_FORMS": "0",
            "dish_components-MAX_NUM_FORMS": "1000",
            "dish_components-0-id": self.dc_a.id,
            "dish_components-0-component": self.component_a.id,
            "dish_components-0-order": 1,
            "dish_components-0-template_note": "",
            "dish_components-1-id": self.dc_b.id,
            "dish_components-1-component": self.component_b.id,
            "dish_components-1-order": 2,
            "dish_components-1-template_note": "cook 2 extra minutes",
        })
        self.assertEqual(response.status_code, 302)

        task_a.refresh_from_db()
        self.assertEqual(task_a.status, PrepTask.TaskStatus.DONE)
        self.assertEqual(task_a.assignee, self.user)
        self.assertEqual(task_a.daily_note, "quedó justo")


class ComponentDeleteViewTests(TestCase):
    """
    Regression tests for ComponentDeleteView (see PREPPLAN_NOTES.md #1,
    "pendiente de verificar"): unlike DishDeleteView, it used to be a bare
    generic DeleteView with no production-history check, so deleting a
    Component still referenced by a PRODUCTION PrepTask (dish_component's
    on_delete=PROTECT) crashed with an unhandled 500 instead of a friendly
    message.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook3", password="x")
        self.team = Team.objects.create(name="Kitchen3", join_code="000004", created_by=self.user)
        TeamMembership.objects.create(
            user=self.user, team=self.team, role=TeamMembership.Role.OWNER, can_manage_menu=True
        )

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component = Component.objects.create(team=self.team, name="Broth", type=Component.ComponentType.SIMPLE_PREP)
        self.dish_component = DishComponent.objects.create(dish=self.dish, component=self.component, order=1)

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_blocks_deletion_with_message_when_used_in_production(self):
        plan = planning_services.get_or_create_draft_plan(self.team, datetime.date(2026, 1, 1), self.user)
        planning_services.finalize_plan(plan, self.user)
        self.assertEqual(PrepPlan.objects.get(pk=plan.pk).state, PrepPlan.PlanState.PRODUCTION)

        url = reverse("menu:component_delete", args=[self.component.pk])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Component.objects.filter(pk=self.component.pk).exists())

    def test_deletes_component_and_clears_only_its_draft_tasks(self):
        other_component = Component.objects.create(team=self.team, name="Noodles", type=Component.ComponentType.SIMPLE_PREP)
        DishComponent.objects.create(dish=self.dish, component=other_component, order=2)

        plan = planning_services.get_or_create_draft_plan(self.team, datetime.date(2026, 1, 2), self.user)
        other_task = PrepTask.objects.get(plan=plan, dish_component__component=other_component)
        other_task.status = PrepTask.TaskStatus.DONE
        other_task.daily_note = "ok"
        other_task.save()

        url = reverse("menu:component_delete", args=[self.component.pk])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Component.objects.filter(pk=self.component.pk).exists())
        self.assertFalse(PrepTask.objects.filter(dish_component__component=self.component).exists())

        other_task.refresh_from_db()
        self.assertEqual(other_task.status, PrepTask.TaskStatus.DONE)
        self.assertEqual(other_task.daily_note, "ok")
