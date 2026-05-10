from collections import OrderedDict
from django.db.models import Count, Q
from .models import PrepPlan, PrepTask, PlanDish

def get_plan_list_queryset(team):
    return annotate_plan_progress(PrepPlan.objects.filter(team=team)).order_by("-service_date")

def annotate_plan_progress(queryset):
    return queryset.annotate(
        task_total_count=Count("tasks", distinct=True),
        task_done_count=Count("tasks", filter=Q(tasks__status=PrepTask.TaskStatus.DONE), distinct=True),
    )

def get_sheet_groups(plan: PrepPlan):
    tasks = (
        PrepTask.objects.filter(plan=plan)
        .select_related("dish_component__dish", "dish_component__component", "assignee")
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
