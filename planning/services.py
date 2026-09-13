from __future__ import annotations

import datetime
from django.db import transaction
from django.utils import timezone

from accounts.models import TeamMembership
from menu.models import Dish, DishComponent
from .models import PrepPlan, PlanDish, PrepTask

def _assert_team_member(user, team) -> None:
    if not TeamMembership.objects.filter(user=user, team=team).exists():
        raise PermissionError("User is not a member of this team.")

def get_or_create_draft_plan(team, service_date, user) -> PrepPlan:
    _assert_team_member(user, team)
    plan, created = PrepPlan.objects.get_or_create(
        team=team,
        service_date=service_date,
        defaults={"created_by": user, "state": PrepPlan.PlanState.DRAFT},
    )
    if created:
        ensure_default_plandishes(plan)
        build_placeholders_hard_reset(plan)
    return plan

def ensure_default_plandishes(plan: PrepPlan) -> None:
    if plan.plan_dishes.exists():
        return
    dishes = Dish.objects.filter(team=plan.team, is_active=True).order_by("name")
    bulk = [PlanDish(plan=plan, dish=d, order=i+1) for i, d in enumerate(dishes)]
    PlanDish.objects.bulk_create(bulk, ignore_conflicts=True)

def set_plandishes(plan: PrepPlan, dish_ids: list[int]) -> None:
    if plan.state != PrepPlan.PlanState.DRAFT:
        raise ValueError("Cannot edit dishes in PRODUCTION.")

    dishes = list(Dish.objects.filter(team=plan.team, id__in=dish_ids).order_by("name"))
    selected_ids = {d.id for d in dishes}

    # Hard reset PlanDish list deterministically
    plan.plan_dishes.all().delete()
    PlanDish.objects.bulk_create(
        [PlanDish(plan=plan, dish=d, order=i+1) for i, d in enumerate(dishes)]
    )

    if dish_ids and len(selected_ids) != len(set(dish_ids)):
        # duplicates submitted; safe ignore
        pass

def build_placeholders_hard_reset(plan: PrepPlan) -> None:
    """Syncs PrepTasks to the plan's current dishes/components.

    Only adds tasks for dish_components that don't have one yet and removes
    tasks whose dish_component is no longer part of the plan. Existing tasks
    are left untouched, preserving status/assignee/daily_note.
    """
    if plan.state != PrepPlan.PlanState.DRAFT:
        raise ValueError("Cannot refresh placeholders in PRODUCTION.")

    dish_ids = [
        pd.dish_id for pd in plan.plan_dishes.select_related("dish")
        if pd.dish.team_id == plan.team_id
    ]
    target_dc_ids = set(
        DishComponent.objects.filter(dish_id__in=dish_ids).values_list("id", flat=True)
    )
    existing_dc_ids = set(plan.tasks.values_list("dish_component_id", flat=True))

    stale_dc_ids = existing_dc_ids - target_dc_ids
    if stale_dc_ids:
        plan.tasks.filter(dish_component_id__in=stale_dc_ids).delete()

    new_dc_ids = target_dc_ids - existing_dc_ids
    if new_dc_ids:
        PrepTask.objects.bulk_create(
            PrepTask(plan=plan, dish_component_id=dc_id, status=PrepTask.TaskStatus.NONE)
            for dc_id in new_dc_ids
        )

def finalize_plan(plan: PrepPlan, user) -> None:
    if plan.state != PrepPlan.PlanState.DRAFT:
        return
    plan.state = PrepPlan.PlanState.PRODUCTION
    plan.finalized_by = user
    plan.finalized_at = timezone.now()
    plan.save(update_fields=["state", "finalized_by", "finalized_at"])

def erase_plan(plan: PrepPlan) -> None:
    if plan.state != PrepPlan.PlanState.DRAFT:
        raise ValueError("Cannot erase a plan in PRODUCTION.")
    plan.delete()

def complete_plan(plan: PrepPlan, user) -> None:
    if plan.state != PrepPlan.PlanState.PRODUCTION:
        return
    plan.state = PrepPlan.PlanState.COMPLETE
    plan.completed_by = user
    plan.completed_at = timezone.now()
    plan.save(update_fields=["state", "completed_by", "completed_at"])

def reopen_plan(plan: PrepPlan) -> None:
    """Steps the plan back one stage: COMPLETE -> PRODUCTION, PRODUCTION -> DRAFT."""
    if plan.state == PrepPlan.PlanState.COMPLETE:
        plan.state = PrepPlan.PlanState.PRODUCTION
        plan.completed_by = None
        plan.completed_at = None
        plan.save(update_fields=["state", "completed_by", "completed_at"])
    elif plan.state == PrepPlan.PlanState.PRODUCTION:
        plan.state = PrepPlan.PlanState.DRAFT
        plan.finalized_by = None
        plan.finalized_at = None
        plan.save(update_fields=["state", "finalized_by", "finalized_at"])

@transaction.atomic
def task_tap(task_id: int, user) -> PrepTask:
    task = PrepTask.objects.select_for_update().select_related(
        "plan", "dish_component__dish", "dish_component__component", "assignee"
    ).get(id=task_id)

    # Enforce membership
    if not TeamMembership.objects.filter(user=user, team=task.plan.team).exists():
        raise PermissionError("Not a member of this team.")

    if task.plan.state == PrepPlan.PlanState.DRAFT:
        # DRAFT: NONE<->PLANNED (no claim)
        if task.status == PrepTask.TaskStatus.NONE:
            task.status = PrepTask.TaskStatus.PLANNED
        elif task.status == PrepTask.TaskStatus.PLANNED:
            task.status = PrepTask.TaskStatus.NONE
        task.save(update_fields=["status"])
        return task

    if task.plan.state != PrepPlan.PlanState.PRODUCTION:
        # COMPLETE (or any other non-editable state): read-only, no-op.
        return task

    # PRODUCTION: row tap claims if needed, then toggles planned/done.
    if task.assignee_id is None:
        task.assignee = user

    if task.status == PrepTask.TaskStatus.NONE:
        task.status = PrepTask.TaskStatus.PLANNED
    elif task.status == PrepTask.TaskStatus.PLANNED:
        task.status = PrepTask.TaskStatus.DONE
    elif task.status == PrepTask.TaskStatus.DONE:
        task.status = PrepTask.TaskStatus.PLANNED

    task.save(update_fields=["assignee", "status"])
    return task

@transaction.atomic
def task_claim(task_id: int, user) -> PrepTask:
    task = PrepTask.objects.select_for_update().select_related(
        "plan", "dish_component__dish", "dish_component__component", "assignee"
    ).get(id=task_id)

    if not TeamMembership.objects.filter(user=user, team=task.plan.team).exists():
        raise PermissionError("Not a member of this team.")

    if task.plan.state != PrepPlan.PlanState.PRODUCTION:
        return task

    if task.assignee_id:
        task.assignee = None
        task.status = PrepTask.TaskStatus.NONE
    else:
        task.assignee = user
        task.status = PrepTask.TaskStatus.PLANNED

    task.save(update_fields=["assignee", "status"])
    return task

@transaction.atomic
def set_task_note(task_id: int, note: str, user) -> PrepTask:
    task = PrepTask.objects.select_for_update().select_related(
        "plan", "dish_component__dish", "dish_component__component", "assignee"
    ).get(id=task_id)

    if not TeamMembership.objects.filter(user=user, team=task.plan.team).exists():
        raise PermissionError("Not a member of this team.")

    if task.plan.state == PrepPlan.PlanState.COMPLETE:
        return task

    task.daily_note = note
    task.save(update_fields=["daily_note"])
    return task
