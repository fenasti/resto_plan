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
        .select_related("purchase_item", "purchase_item__supplier", "purchase_item__category")
        .order_by(
            "purchase_item__supplier", "purchase_item__category", "sort_order", "purchase_item__name", "id"
        )
    )


def build_grouped_order_rows(formset):
    """Supplier first, category within each supplier section — mirrors
    export_order_excel's per-supplier-sheet structure exactly, so what you
    see while building the list matches what each vendor gets sent."""
    grouped = OrderedDict()

    for form in formset.forms:
        item = form.instance
        supplier = item.purchase_item.display_supplier
        category = item.purchase_item.display_category
        supplier_group = grouped.setdefault(supplier, OrderedDict())
        supplier_group.setdefault(category, []).append({"item": item, "form": form})

    return [
        {
            "supplier": supplier,
            "categories": [
                {"category": category, "rows": rows} for category, rows in categories.items()
            ],
        }
        for supplier, categories in grouped.items()
    ]

