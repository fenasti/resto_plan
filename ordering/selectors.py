from collections import OrderedDict

from django.db.models import Count

from .models import OrderList, OrderListItem


def get_order_list_queryset(team):
    return (
        OrderList.objects.filter(team=team)
        .select_related("created_by", "finalized_by")
        .annotate(item_count_annotated=Count("items", distinct=True))
        .order_by("-order_date")
    )


def get_order_item_queryset(order):
    return (
        OrderListItem.objects.filter(order_list=order)
        .select_related("purchase_item")
        .order_by("purchase_item__category", "sort_order", "purchase_item__name", "id")
    )


def build_grouped_order_rows(formset):
    grouped = OrderedDict()

    for form in formset.forms:
        item = form.instance
        category = item.purchase_item.display_category
        grouped.setdefault(category, [])
        grouped[category].append({"item": item, "form": form})

    return [{"category": category, "rows": rows} for category, rows in grouped.items()]

