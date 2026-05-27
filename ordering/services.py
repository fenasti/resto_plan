from __future__ import annotations

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from accounts.models import TeamMembership

from .models import OrderList, OrderListItem, PurchaseItem


def _assert_team_member(user, team) -> None:
    if not TeamMembership.objects.filter(user=user, team=team).exists():
        raise PermissionError("User is not a member of this team.")


def _next_order_item_sort(order: OrderList) -> int:
    max_sort = order.items.aggregate(max_sort=Max("sort_order"))["max_sort"] or 0
    return max_sort + 1


def _next_purchase_item_sort(team) -> int:
    max_sort = team.purchase_items.aggregate(max_sort=Max("sort_order"))["max_sort"] or 0
    return max_sort + 1


def get_most_recent_order(team, exclude_date=None):
    queryset = OrderList.objects.filter(team=team)
    if exclude_date is not None:
        queryset = queryset.exclude(order_date=exclude_date)
    return queryset.order_by("-order_date", "-created_at").first()


def clone_order_items(source: OrderList, target: OrderList) -> None:
    source_items = source.items.select_related("purchase_item").order_by("sort_order", "id")
    clones = [
        OrderListItem(
            order_list=target,
            purchase_item=item.purchase_item,
            quantity_text=item.quantity_text,
            note=item.note,
            sort_order=item.sort_order,
        )
        for item in source_items
    ]
    OrderListItem.objects.bulk_create(clones)


@transaction.atomic
def get_or_create_order(team, order_date, user, *, blank=False, source_order=None):
    _assert_team_member(user, team)
    order, created = OrderList.objects.get_or_create(
        team=team,
        order_date=order_date,
        defaults={"created_by": user, "state": OrderList.OrderState.DRAFT},
    )

    if created and not blank:
        source = source_order or get_most_recent_order(team, exclude_date=order_date)
        if source:
            clone_order_items(source, order)

    return order, created


def finalize_order(order: OrderList, user) -> None:
    if order.state != OrderList.OrderState.DRAFT:
        return
    order.state = OrderList.OrderState.FINALIZED
    order.finalized_by = user
    order.finalized_at = timezone.now()
    order.save(update_fields=["state", "finalized_by", "finalized_at"])


def reopen_order(order: OrderList) -> None:
    if order.state != OrderList.OrderState.FINALIZED:
        return
    order.state = OrderList.OrderState.DRAFT
    order.finalized_by = None
    order.finalized_at = None
    order.save(update_fields=["state", "finalized_by", "finalized_at"])


def erase_order(order: OrderList) -> None:
    if order.state != OrderList.OrderState.DRAFT:
        raise ValueError("Cannot erase a finalized order list.")
    order.delete()


@transaction.atomic
def add_purchase_item_to_order(order: OrderList, purchase_item: PurchaseItem, user):
    _assert_team_member(user, order.team)
    if order.state != OrderList.OrderState.DRAFT:
        raise ValueError("Cannot edit a finalized order list.")

    order_item, created = OrderListItem.objects.get_or_create(
        order_list=order,
        purchase_item=purchase_item,
        defaults={"sort_order": _next_order_item_sort(order)},
    )
    return order_item, created


@transaction.atomic
def create_purchase_item_and_add_to_order(
    order: OrderList,
    *,
    name: str,
    category: str,
    default_unit: str,
    user,
):
    _assert_team_member(user, order.team)
    if order.state != OrderList.OrderState.DRAFT:
        raise ValueError("Cannot edit a finalized order list.")

    purchase_item = PurchaseItem.objects.create(
        team=order.team,
        name=name,
        category=category,
        default_unit=default_unit,
        sort_order=_next_purchase_item_sort(order.team),
    )
    order_item, _ = add_purchase_item_to_order(order, purchase_item, user)
    return purchase_item, order_item


@transaction.atomic
def remove_order_item(order_item_id: int, user) -> None:
    order_item = OrderListItem.objects.select_related("order_list__team").get(id=order_item_id)
    _assert_team_member(user, order_item.order_list.team)
    if order_item.order_list.state != OrderList.OrderState.DRAFT:
        raise ValueError("Cannot edit a finalized order list.")
    order_item.delete()

