from collections import OrderedDict
from .models import PrepPlan, PrepTask, PlanDish

def get_plan_list_queryset(team):
    return PrepPlan.objects.filter(team=team).order_by("-service_date")

def get_sheet_groups(plan: PrepPlan):
    tasks = (
        PrepTask.objects.filter(plan=plan)
        .select_related("dish_component__dish", "dish_component__component", "assignee")
        .order_by("dish_component__dish__name", "dish_component__order", "id")
    )

    dish_order = list(
        PlanDish.objects.filter(plan=plan)
        .select_related("dish")
        .order_by("order", "dish__name")
        .values_list("dish_id", flat=True)
    )

    grouped = OrderedDict()
    for dish_id in dish_order:
        grouped[dish_id] = {"dish": None, "tasks": []}

    for t in tasks:
        dish = t.dish_component.dish
        if dish.id not in grouped:
            grouped[dish.id] = {"dish": dish, "tasks": []}
        if grouped[dish.id]["dish"] is None:
            grouped[dish.id]["dish"] = dish
        grouped[dish.id]["tasks"].append(t)

    return [v for v in grouped.values() if v["dish"] is not None]