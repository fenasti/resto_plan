from collections import OrderedDict
from django.db.models import Count, Q
from menu.models import Component
from .models import PrepPlan, PrepTask, PlanDish

def get_plan_list_queryset(team):
    return annotate_plan_progress(PrepPlan.objects.filter(team=team)).order_by("-service_date")

def get_eligible_standalone_components(team):
    """Recurring prep items that aren't tied to any dish — these show up on
    every plan automatically via build_placeholders_hard_reset, and can be
    toggled off from the Builder or the Prep Items catalog."""
    return Component.objects.filter(
        team=team, standalone_active=True, dish_components__isnull=True
    ).order_by("name")

def annotate_plan_progress(queryset):
    return queryset.annotate(
        task_total_count=Count("tasks", distinct=True),
        task_done_count=Count("tasks", filter=Q(tasks__status=PrepTask.TaskStatus.DONE), distinct=True),
    )

def get_extra_tasks(plan: PrepPlan):
    """Ad hoc/standalone tasks: not tied to any dish, shown in their own group."""
    return (
        PrepTask.objects.filter(plan=plan, dish_component__isnull=True)
        .select_related("component", "recipe", "assignee", "assignee__cookprofile")
        .order_by("id")
    )

def get_sheet_groups(plan: PrepPlan):
    tasks = (
        PrepTask.objects.filter(plan=plan, dish_component__isnull=False)
        .select_related(
            "dish_component__dish", "dish_component__component", "assignee", "assignee__cookprofile"
        )
        .order_by("dish_component__dish__name", "dish_component__order", "id")
    )

    plan_dishes = list(
        PlanDish.objects.filter(plan=plan)
        .select_related("dish")
        .order_by("order", "dish__name")
    )

    grouped = OrderedDict()
    for plan_dish in plan_dishes:
        grouped[plan_dish.dish_id] = {"dish": plan_dish.dish, "tasks": []}

    for t in tasks:
        dish = t.dish_component.dish
        if dish.id not in grouped:
            grouped[dish.id] = {"dish": dish, "tasks": []}
        grouped[dish.id]["tasks"].append(t)

    return list(grouped.values())
