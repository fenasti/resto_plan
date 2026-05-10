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
    dishes = Dish.objects.filter(team=plan.team, on_use=True).order_by("name")
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
    if plan.state != PrepPlan.PlanState.DRAFT:
        raise ValueError("Cannot refresh placeholders in PRODUCTION.")

    plan.tasks.all().delete()

    plandishes = plan.plan_dishes.select_related("dish").order_by("order", "id")
    tasks = []
    for pd in plandishes:
        # dish must belong to same team
        if pd.dish.team_id != plan.team_id:
            continue
        dishcomponents = DishComponent.objects.filter(dish=pd.dish).select_related("dish", "component").order_by("order", "id")
        for dc in dishcomponents:
            # Ensure component is also in team (should be if dish is)
            tasks.append(PrepTask(plan=plan, dish_component=dc, status=PrepTask.TaskStatus.NONE))
    PrepTask.objects.bulk_create(tasks)

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

def reopen_plan(plan: PrepPlan) -> None:
    if plan.state != PrepPlan.PlanState.PRODUCTION:
        return
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

    task.daily_note = note
    task.save(update_fields=["daily_note"])
    return task
