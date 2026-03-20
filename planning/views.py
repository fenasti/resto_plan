import datetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.generic import ListView, TemplateView

from accounts.mixins import TeamMemberRequiredMixin
from .models import PrepPlan, PrepTask
from .forms import PlanBuilderForm
from .selectors import get_plan_list_queryset, get_sheet_groups
from . import services

def _parse_date(date_str: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError:
        raise Http404("Invalid date format. Use YYYY-MM-DD.")

@login_required
def create_tomorrow(request):
    if not request.team or not request.membership:
        return redirect("accounts:team_select")

    tomorrow = timezone.localdate() + datetime.timedelta(days=1)
    plan = services.get_or_create_draft_plan(request.team, tomorrow, request.user)
    return redirect("planning:plan_builder", date_str=str(plan.service_date))

class PlanListView(TeamMemberRequiredMixin, ListView):
    template_name = "planning/plan_list.html"
    context_object_name = "plans"

    def get_queryset(self):
        return get_plan_list_queryset(self.request.team)

class PlanSheetView(TeamMemberRequiredMixin, TemplateView):
    template_name = "planning/plan_sheet.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        service_date = _parse_date(kwargs.get("date_str"))
        plan = PrepPlan.objects.filter(team=self.request.team, service_date=service_date).first()
        if not plan:
            plan = services.get_or_create_draft_plan(self.request.team, service_date, self.request.user)

        ctx["plan"] = plan
        ctx["groups"] = get_sheet_groups(plan)
        return ctx

class PlanBuilderView(TeamMemberRequiredMixin, TemplateView):
    template_name = "planning/plan_builder.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        service_date = _parse_date(kwargs["date_str"])
        plan = services.get_or_create_draft_plan(self.request.team, service_date, self.request.user)
        ctx["plan"] = plan

        selected_ids = list(plan.plan_dishes.values_list("dish_id", flat=True))
        form = PlanBuilderForm(initial={"dishes": selected_ids}, team=self.request.team)
        ctx["form"] = form
        return ctx

    def post(self, request, **kwargs):
        service_date = _parse_date(kwargs["date_str"])
        plan = services.get_or_create_draft_plan(self.request.team, service_date, request.user)

        form = PlanBuilderForm(request.POST, team=self.request.team)
        if not form.is_valid():
            return render(request, self.template_name, {"plan": plan, "form": form})

        dish_ids = [d.id for d in form.cleaned_data["dishes"]]
        action = request.POST.get("action", "save")

        try:
            services.set_plandishes(plan, dish_ids)

            if action == "save":
                messages.success(request, "Draft saved.")
                return redirect("planning:plan_builder", date_str=str(plan.service_date))

            if action == "refresh":
                services.build_placeholders_hard_reset(plan)
                messages.success(request, "Placeholders refreshed (hard reset).")
                return redirect("planning:plan_sheet", date_str=str(plan.service_date))

            if action == "finalize":
                services.build_placeholders_hard_reset(plan)
                services.finalize_plan(plan, request.user)
                messages.success(request, "Plan finalized. Production mode enabled.")
                return redirect("planning:plan_sheet", date_str=str(plan.service_date))

            if action == "erase":
                services.erase_plan(plan)
                messages.success(request, "Plan erased.")
                return redirect("planning:plan_list")

        except Exception as e:
            messages.error(request, str(e))

        return redirect("planning:plan_builder", date_str=str(plan.service_date))


@login_required
def finalize_plan_view(request, date_str: str):
    if not request.team or not request.membership:
        return redirect("accounts:team_select")
    service_date = _parse_date(date_str)
    plan = PrepPlan.objects.filter(team=request.team, service_date=service_date).first()
    if not plan:
        raise Http404("Plan not found.")
    services.finalize_plan(plan, request.user)
    messages.success(request, "Plan finalized.")
    return redirect("planning:plan_sheet", date_str=str(plan.service_date))

@login_required
def refresh_plan_view(request, date_str: str):
    if not request.team or not request.membership:
        return redirect("accounts:team_select")
    service_date = _parse_date(date_str)
    plan = PrepPlan.objects.filter(team=request.team, service_date=service_date).first()
    if not plan:
        raise Http404("Plan not found.")
    services.build_placeholders_hard_reset(plan)
    messages.success(request, "Placeholders refreshed (hard reset).")
    return redirect("planning:plan_sheet", date_str=str(plan.service_date))

@login_required
def erase_plan_view(request, date_str: str):
    if not request.team or not request.membership:
        return redirect("accounts:team_select")
    service_date = _parse_date(date_str)
    plan = PrepPlan.objects.filter(team=request.team, service_date=service_date).first()
    if not plan:
        raise Http404("Plan not found.")
    services.erase_plan(plan)
    messages.success(request, "Plan erased.")
    return redirect("planning:plan_list")


@login_required
def task_tap_view(request, pk: int):
    if request.method != "POST":
        return HttpResponse(status=405)
    task = services.task_tap(pk, request.user)
    return render(request, "planning/partials/task_row.html", {"task": task})

@login_required
def task_claim_view(request, pk: int):
    if request.method != "POST":
        return HttpResponse(status=405)
    task = services.task_claim(pk, request.user)
    return render(request, "planning/partials/task_row.html", {"task": task})

@login_required
def task_note_view(request, pk: int):
    task = PrepTask.objects.select_related(
        "plan", "dish_component__dish", "dish_component__component", "assignee"
    ).get(pk=pk)

    if request.method == "GET":
        return render(request, "planning/partials/task_row.html", {"task": task, "note_edit": True})

    note = request.POST.get("daily_note", "")
    task = services.set_task_note(pk, note, request.user)
    return render(request, "planning/partials/task_row.html", {"task": task})