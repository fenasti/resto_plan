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
        Component.objects.create(team=self.team, name="Broth")
        response = self.client.post(
            reverse("menu:component_create"),
            {"name": "Broth"},
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
        self.component_a = Component.objects.create(team=self.team, name="Broth")
        self.component_b = Component.objects.create(team=self.team, name="Noodles")
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
        self.component = Component.objects.create(team=self.team, name="Broth")
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
        other_component = Component.objects.create(team=self.team, name="Noodles")
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


class ComponentQuickCreateTests(TestCase):
    """
    Creating a prep item inline from Edit Prep Items (instead of the generic
    catalog) — one row per manual label or recipe pick, multiple in one
    submit, with dedup on the recipe path.
    """

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000030", created_by=self.owner)
        TeamMembership.objects.create(user=self.owner, team=self.team, role=TeamMembership.Role.OWNER)

        self.member = User.objects.create_user(username="member", password="x")
        TeamMembership.objects.create(user=self.member, team=self.team, role=TeamMembership.Role.MEMBER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.recipe = Recipe.objects.create(team=self.team, name="Base Broth", ingredients_text="water")

        self.client.force_login(self.owner)
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

    def test_creates_manual_and_recipe_components_in_one_submit(self):
        payload = self._formset_payload([
            {"label": "Chop chives"},
            {"recipe": self.recipe.id},
        ])
        response = self.client.post(
            reverse("menu:component_quick_create", args=[self.dish.pk]), payload
        )
        self.assertRedirects(response, reverse("menu:dish_detail", args=[self.dish.pk]))
        self.assertTrue(Component.objects.filter(team=self.team, name="Chop chives").exists())
        broth = Component.objects.get(team=self.team, name="Base Broth")
        self.assertEqual(broth.recipe_id, self.recipe.id)
        self.assertEqual(DishComponent.objects.filter(dish=self.dish).count(), 2)

    def test_picking_the_same_recipe_twice_does_not_duplicate_the_component(self):
        other_dish = Dish.objects.create(team=self.team, name="Pho")
        self.client.post(
            reverse("menu:component_quick_create", args=[self.dish.pk]),
            self._formset_payload([{"recipe": self.recipe.id}]),
        )
        self.client.post(
            reverse("menu:component_quick_create", args=[other_dish.pk]),
            self._formset_payload([{"recipe": self.recipe.id}]),
        )
        self.assertEqual(Component.objects.filter(team=self.team, recipe=self.recipe).count(), 1)
        self.assertEqual(DishComponent.objects.filter(component__recipe=self.recipe).count(), 2)

    def test_row_with_both_label_and_recipe_rejects_the_whole_batch(self):
        payload = self._formset_payload([{"label": "Chop chives", "recipe": self.recipe.id}])
        response = self.client.post(
            reverse("menu:component_quick_create", args=[self.dish.pk]), payload
        )
        self.assertRedirects(response, reverse("menu:dish_components_edit", args=[self.dish.pk]))
        self.assertFalse(Component.objects.filter(team=self.team, name="Chop chives").exists())

    def test_member_restricted_from_menu_cannot_quick_create(self):
        # can_manage_menu defaults to True (horizontal by default); this
        # simulates an owner having restricted this specific person.
        membership = TeamMembership.objects.get(user=self.member, team=self.team)
        membership.can_manage_menu = False
        membership.save()

        self.client.force_login(self.member)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

        payload = self._formset_payload([{"label": "Chop chives"}])
        response = self.client.post(
            reverse("menu:component_quick_create", args=[self.dish.pk]), payload
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Component.objects.filter(team=self.team, name="Chop chives").exists())


class ToggleStandaloneActiveTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000031", created_by=self.owner)
        TeamMembership.objects.create(user=self.owner, team=self.team, role=TeamMembership.Role.OWNER)

        self.member = User.objects.create_user(username="member", password="x")
        TeamMembership.objects.create(user=self.member, team=self.team, role=TeamMembership.Role.MEMBER)

        self.component = Component.objects.create(team=self.team, name="Deep Clean")

    def test_owner_can_toggle(self):
        self.client.force_login(self.owner)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

        response = self.client.post(reverse("menu:component_toggle_standalone", args=[self.component.pk]))
        self.assertRedirects(response, reverse("menu:component_list"))
        self.component.refresh_from_db()
        self.assertTrue(self.component.standalone_active)

    def test_member_restricted_from_menu_cannot_toggle(self):
        # can_manage_menu defaults to True; simulate an owner restriction.
        membership = TeamMembership.objects.get(user=self.member, team=self.team)
        membership.can_manage_menu = False
        membership.save()

        self.client.force_login(self.member)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

        response = self.client.post(reverse("menu:component_toggle_standalone", args=[self.component.pk]))
        self.assertEqual(response.status_code, 302)
        self.component.refresh_from_db()
        self.assertFalse(self.component.standalone_active)


class MenuMobileTouchUsabilityTests(TestCase):
    """
    Same mobile-usability pass applied to the prep list and order screens,
    extended across Menu Setup: a back link off every sub-screen instead of
    relying on the hamburger menu, and per-row catalog actions (Toggle/
    Edit/Delete, the dish's prep-item Remove button) tagged so the shared
    touch-target CSS bump in style.css applies to them.
    """

    def setUp(self):
        self.user = User.objects.create_user(username="cook", password="x")
        self.team = Team.objects.create(name="Kitchen", join_code="000020", created_by=self.user)
        TeamMembership.objects.create(user=self.user, team=self.team, role=TeamMembership.Role.OWNER)

        self.dish = Dish.objects.create(team=self.team, name="Ramen")
        self.component = Component.objects.create(team=self.team, name="Broth")
        DishComponent.objects.create(dish=self.dish, component=self.component, order=1)
        self.recipe = Recipe.objects.create(team=self.team, name="Broth Recipe", ingredients_text="water")

        self.client.force_login(self.user)
        session = self.client.session
        session["active_team_id"] = self.team.id
        session.save()

    def test_dish_detail_has_a_back_link_to_dish_list(self):
        resp = self.client.get(reverse("menu:dish_detail", args=[self.dish.pk]))
        self.assertContains(resp, reverse("menu:dish_list"))
        self.assertContains(resp, "btn-back")
        self.assertContains(resp, "dish-component-row")

    def test_recipe_detail_has_a_back_link_to_recipe_list(self):
        resp = self.client.get(reverse("menu:recipe_detail", args=[self.recipe.pk]))
        self.assertContains(resp, reverse("menu:recipe_list"))
        self.assertContains(resp, "btn-back")

    def test_dish_components_edit_back_link_goes_to_dish_detail(self):
        resp = self.client.get(reverse("menu:dish_components_edit", args=[self.dish.pk]))
        self.assertContains(resp, reverse("menu:dish_detail", args=[self.dish.pk]))
        self.assertContains(resp, "btn-back")

    def test_dish_create_form_back_link_goes_to_dish_list(self):
        resp = self.client.get(reverse("menu:dish_create"))
        self.assertContains(resp, reverse("menu:dish_list"))
        self.assertContains(resp, "btn-back")

    def test_dish_edit_form_back_link_goes_to_dish_detail(self):
        resp = self.client.get(reverse("menu:dish_edit", args=[self.dish.pk]))
        self.assertContains(resp, reverse("menu:dish_detail", args=[self.dish.pk]))

    def test_recipe_edit_form_back_link_goes_to_recipe_detail(self):
        resp = self.client.get(reverse("menu:recipe_edit", args=[self.recipe.pk]))
        self.assertContains(resp, reverse("menu:recipe_detail", args=[self.recipe.pk]))

    def test_component_form_back_link_goes_to_component_list(self):
        resp = self.client.get(reverse("menu:component_create"))
        self.assertContains(resp, reverse("menu:component_list"))
        self.assertContains(resp, "btn-back")

    def test_index_rows_tag_their_actions_for_the_touch_target_css(self):
        for url_name in ["menu:dish_list", "menu:component_list", "menu:recipe_list"]:
            resp = self.client.get(reverse(url_name))
            self.assertContains(resp, "catalog-row-actions")
        self.assertFalse(self.component.standalone_active)
