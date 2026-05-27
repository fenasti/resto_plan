import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import ListView, TemplateView

from accounts.mixins import TeamMemberRequiredMixin

from .forms import AddExistingOrderItemForm, OrderItemFormSet, QuickCreatePurchaseItemForm
from .models import OrderList
from .selectors import build_grouped_order_rows, get_order_item_queryset, get_order_list_queryset
from . import services


def _parse_date(date_str: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError:
        raise Http404("Invalid date format. Use YYYY-MM-DD.")


def _require_active_team(request):
    if not request.team or not request.membership:
        return redirect("accounts:team_select")
    return None


@login_required
def create_today_order(request):
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response

    order_date = timezone.localdate()
    order, created = services.get_or_create_order(request.team, order_date, request.user)
    if created:
        if order.item_count:
            messages.success(request, "Today's order list created from the latest order.")
        else:
            messages.success(request, "Started a new blank order list for today.")
    else:
        messages.info(request, "Opened today's existing order list.")
    return redirect("ordering:order_detail", date_str=str(order.order_date))


@login_required
def create_blank_today_order(request):
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response

    order_date = timezone.localdate()
    order, created = services.get_or_create_order(
        request.team,
        order_date,
        request.user,
        blank=True,
    )
    if created:
        messages.success(request, "Started a blank order list for today.")
    else:
        messages.info(request, "Opened today's existing order list.")
    return redirect("ordering:order_detail", date_str=str(order.order_date))


@login_required
def clone_order_to_today_view(request, date_str: str):
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response

    source_date = _parse_date(date_str)
    source_order = get_object_or_404(OrderList, team=request.team, order_date=source_date)
    order, created = services.get_or_create_order(
        request.team,
        timezone.localdate(),
        request.user,
        source_order=source_order,
    )
    if created:
        messages.success(request, f"Today's order list created from {source_order.order_date}.")
    else:
        messages.info(request, "Opened today's existing order list.")
    return redirect("ordering:order_detail", date_str=str(order.order_date))


class OrderListView(TeamMemberRequiredMixin, ListView):
    template_name = "ordering/order_list.html"
    context_object_name = "orders"

    def get_queryset(self):
        return get_order_list_queryset(self.request.team)


class OrderDetailView(TeamMemberRequiredMixin, TemplateView):
    template_name = "ordering/order_detail.html"

    def _get_order(self):
        return get_object_or_404(
            OrderList.objects.select_related("created_by", "finalized_by"),
            team=self.request.team,
            order_date=_parse_date(self.kwargs["date_str"]),
        )

    def _get_formset(self, order, data=None):
        return OrderItemFormSet(
            data=data,
            queryset=get_order_item_queryset(order),
        )

    def _build_context(
        self,
        *,
        order,
        formset=None,
        add_existing_form=None,
        create_item_form=None,
    ):
        formset = formset or self._get_formset(order)
        add_existing_form = add_existing_form or AddExistingOrderItemForm(team=self.request.team)
        create_item_form = create_item_form or QuickCreatePurchaseItemForm(team=self.request.team)

        return {
            "order": order,
            "formset": formset,
            "groups": build_grouped_order_rows(formset),
            "add_existing_form": add_existing_form,
            "create_item_form": create_item_form,
        }

    def get(self, request, *args, **kwargs):
        order = self._get_order()
        return render(request, self.template_name, self._build_context(order=order))

    def post(self, request, *args, **kwargs):
        order = self._get_order()
        action = request.POST.get("action", "save")

        if action == "reopen":
            services.reopen_order(order)
            messages.success(request, "Order list reopened for editing.")
            return redirect("ordering:order_detail", date_str=str(order.order_date))

        if action == "erase":
            try:
                services.erase_order(order)
                messages.success(request, "Order list erased.")
                return redirect("ordering:order_list")
            except Exception as exc:
                messages.error(request, str(exc))
                return redirect("ordering:order_detail", date_str=str(order.order_date))

        if action == "remove_item":
            item_id = int(request.POST.get("item_id", "0"))
            try:
                services.remove_order_item(item_id, request.user)
                messages.success(request, "Item removed from the order list.")
            except Exception as exc:
                messages.error(request, str(exc))
            return redirect("ordering:order_detail", date_str=str(order.order_date))

        if action == "add_existing":
            add_existing_form = AddExistingOrderItemForm(request.POST, team=request.team)
            if add_existing_form.is_valid():
                purchase_item = add_existing_form.cleaned_data["purchase_item"]
                try:
                    _, created = services.add_purchase_item_to_order(order, purchase_item, request.user)
                    if created:
                        messages.success(request, f"Added {purchase_item.name} to the order list.")
                    else:
                        messages.info(request, f"{purchase_item.name} is already on this order list.")
                    return redirect("ordering:order_detail", date_str=str(order.order_date))
                except Exception as exc:
                    messages.error(request, str(exc))
            create_item_form = QuickCreatePurchaseItemForm(team=request.team)
            return render(
                request,
                self.template_name,
                self._build_context(
                    order=order,
                    add_existing_form=add_existing_form,
                    create_item_form=create_item_form,
                ),
            )

        if action == "add_new":
            create_item_form = QuickCreatePurchaseItemForm(request.POST, team=request.team)
            if create_item_form.is_valid():
                try:
                    purchase_item, _ = services.create_purchase_item_and_add_to_order(
                        order,
                        name=create_item_form.cleaned_data["name"],
                        category=create_item_form.cleaned_data["category"],
                        default_unit=create_item_form.cleaned_data["default_unit"],
                        user=request.user,
                    )
                    messages.success(request, f"Created and added {purchase_item.name}.")
                    return redirect("ordering:order_detail", date_str=str(order.order_date))
                except Exception as exc:
                    messages.error(request, str(exc))
            add_existing_form = AddExistingOrderItemForm(team=request.team)
            return render(
                request,
                self.template_name,
                self._build_context(
                    order=order,
                    add_existing_form=add_existing_form,
                    create_item_form=create_item_form,
                ),
            )

        if action in {"save", "finalize"} and order.state != OrderList.OrderState.DRAFT:
            messages.error(request, "Cannot edit a finalized order list until it is reopened.")
            return redirect("ordering:order_detail", date_str=str(order.order_date))

        formset = self._get_formset(order, data=request.POST)
        if not formset.is_valid():
            messages.error(request, "Could not save the order list. Please check the highlighted fields.")
            return render(
                request,
                self.template_name,
                self._build_context(order=order, formset=formset),
            )

        formset.save()

        if action == "finalize":
            services.finalize_order(order, request.user)
            messages.success(request, "Order list finalized.")
        else:
            messages.success(request, "Order list draft saved.")

        return redirect("ordering:order_detail", date_str=str(order.order_date))


@login_required
def export_order_excel(request, date_str: str):
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response

    order = get_object_or_404(OrderList, team=request.team, order_date=_parse_date(date_str))

    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Order List"

    bold = Font(bold=True)
    ws["A1"] = f"Order List - {order.order_date}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"State: {order.get_state_display()}"

    row = 4
    grouped_items = {}
    for item in get_order_item_queryset(order):
        grouped_items.setdefault(item.purchase_item.display_category, [])
        grouped_items[item.purchase_item.display_category].append(item)

    for category, items in grouped_items.items():
        ws.cell(row=row, column=1, value=category).font = bold
        row += 1
        ws.cell(row=row, column=1, value="Item").font = bold
        ws.cell(row=row, column=2, value="Quantity").font = bold
        ws.cell(row=row, column=3, value="Note").font = bold
        row += 1

        for item in items:
            ws.cell(row=row, column=1, value=item.purchase_item.name)
            ws.cell(row=row, column=2, value=item.quantity_text)
            ws.cell(row=row, column=3, value=item.note)
            row += 1

        row += 1

    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 32

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="order_list_{order.order_date.isoformat()}.xlsx"'
    )
    wb.save(response)
    return response
