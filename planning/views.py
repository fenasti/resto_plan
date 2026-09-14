import datetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.generic import ListView, TemplateView

from accounts.mixins import TeamMemberRequiredMixin
from menu.models import Component
from .models import PrepPlan, PrepTask
from .forms import AdHocTaskFormSet, PlanBuilderForm
from .selectors import annotate_plan_progress, get_extra_tasks, get_plan_list_queryset, get_sheet_groups
from . import services

def _parse_date(date_str: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(date_str)
    except ValueError:
        raise Http404("Invalid date format. Use YYYY-MM-DD.")

def _hydrate_plan_progress(plan: PrepPlan) -> PrepPlan:
    plan._task_total = plan.tasks.count()
    plan._task_done = plan.tasks.filter(status=PrepTask.TaskStatus.DONE).count()
    return plan

def _require_active_team(request):
    if not request.team or not request.membership:
        return redirect("accounts:team_select")
    return None

@login_required
def create_tomorrow(request):
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response

    tomorrow = timezone.localdate() + datetime.timedelta(days=1)
    plan = services.get_or_create_draft_plan(request.team, tomorrow, request.user)
    return redirect("planning:plan_builder", date_str=str(plan.service_date))

class PlanListView(TeamMemberRequiredMixin, ListView):
    template_name = "planning/plan_list.html"
    context_object_name = "plans"
    paginate_by = 20

    def get_queryset(self):
        return get_plan_list_queryset(self.request.team)

class PlanSheetView(TeamMemberRequiredMixin, TemplateView):
    """Owns PRODUCTION/COMPLETE only — a DRAFT plan has nothing to show here
    that isn't already on the Builder, so it redirects there instead."""
    template_name = "planning/plan_sheet.html"

    def get(self, request, *args, **kwargs):
        service_date = _parse_date(kwargs.get("date_str"))
        plan = annotate_plan_progress(
            PrepPlan.objects.filter(team=request.team, service_date=service_date)
        ).first()
        if not plan:
            plan = services.get_or_create_draft_plan(request.team, service_date, request.user)
            _hydrate_plan_progress(plan)

        if plan.state == PrepPlan.PlanState.DRAFT:
            return redirect("planning:plan_builder", date_str=str(plan.service_date))

        context = self.get_context_data(plan=plan, **kwargs)
        return self.render_to_response(context)

    def get_context_data(self, plan, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plan"] = plan
        ctx["groups"] = get_sheet_groups(plan)
        ctx["extra_tasks"] = get_extra_tasks(plan)
        return ctx

class PlanBuilderView(TeamMemberRequiredMixin, TemplateView):
    """Owns DRAFT only — once sent to the kitchen or closed, editing the
    selection no longer makes sense, so it redirects to the Prep Sheet."""
    template_name = "planning/plan_builder.html"

    def get(self, request, *args, **kwargs):
        service_date = _parse_date(kwargs["date_str"])
        plan = services.get_or_create_draft_plan(request.team, service_date, request.user)

        if plan.state != PrepPlan.PlanState.DRAFT:
            return redirect("planning:plan_sheet", date_str=str(plan.service_date))

        # Every view re-syncs tasks to the current menu, so there's no
        # separate "Rebuild" action needed anymore.
        services.build_placeholders_hard_reset(plan)

        context = self.get_context_data(plan=plan, **kwargs)
        return self.render_to_response(context)

    def get_context_data(self, plan, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["plan"] = plan

        selected_ids = list(plan.plan_dishes.values_list("dish_id", flat=True))
        standalone_ids = list(
            Component.objects.filter(
                team=self.request.team, standalone_active=True, dish_components__isnull=True
            ).values_list("id", flat=True)
        )
        form = PlanBuilderForm(
            initial={"dishes": selected_ids, "standalone_components": standalone_ids},
            team=self.request.team,
        )
        ctx["form"] = form
        ctx["groups"] = get_sheet_groups(plan)
        ctx["extra_tasks"] = get_extra_tasks(plan)
        ctx["adhoc_formset"] = AdHocTaskFormSet(form_kwargs={"team": self.request.team})
        return ctx

    def post(self, request, **kwargs):
        service_date = _parse_date(kwargs["date_str"])
        plan = services.get_or_create_draft_plan(self.request.team, service_date, request.user)
        action = request.POST.get("action", "save")

        if action == "erase":
            try:
                services.erase_plan(plan)
                messages.success(request, "Prep list erased.")
                return redirect("planning:plan_list")
            except (ValueError, PermissionError) as e:
                messages.error(request, str(e))
                return redirect("planning:plan_builder", date_str=str(plan.service_date))

        form = PlanBuilderForm(request.POST, team=self.request.team)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "plan": plan,
                    "form": form,
                    "groups": get_sheet_groups(plan),
                    "extra_tasks": get_extra_tasks(plan),
                    "adhoc_formset": AdHocTaskFormSet(form_kwargs={"team": self.request.team}),
                },
            )

        dish_ids = [d.id for d in form.cleaned_data["dishes"]]

        # Unchecking a recurring item here is a shortcut for the same
        # standalone_active toggle in the Prep Items catalog — it's a
        # can_manage_menu action since it affects every future prep list.
        if request.membership and request.membership.can_edit_menu:
            checked_component_ids = {c.id for c in form.cleaned_data["standalone_components"]}
            current_standalone_ids = set(
                Component.objects.filter(
                    team=request.team, standalone_active=True, dish_components__isnull=True
                ).values_list("id", flat=True)
            )
            turned_off_ids = current_standalone_ids - checked_component_ids
            if turned_off_ids:
                Component.objects.filter(id__in=turned_off_ids).update(standalone_active=False)

        try:
            services.set_plandishes(plan, dish_ids)

            if action == "save":
                services.build_placeholders_hard_reset(plan)
                messages.success(request, "Draft saved and prep sheet updated.")
                return redirect("planning:plan_builder", date_str=str(plan.service_date))

            if action == "finalize":
                services.build_placeholders_hard_reset(plan)
                services.finalize_plan(plan, request.user)
                messages.success(request, "Prep list sent to the kitchen. Cooks can claim tasks and mark them done.")
                return redirect("planning:plan_sheet", date_str=str(plan.service_date))

        except (ValueError, PermissionError) as e:
            messages.error(request, str(e))

        return redirect("planning:plan_builder", date_str=str(plan.service_date))


@login_required
def complete_plan_view(request, date_str: str):
    if request.method != "POST":
        return HttpResponse(status=405)
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response
    service_date = _parse_date(date_str)
    plan = PrepPlan.objects.filter(team=request.team, service_date=service_date).first()
    if not plan:
        raise Http404("Plan not found.")
    services.complete_plan(plan, request.user)
    messages.success(request, "Prep list closed and locked for editing.")
    return redirect("planning:plan_sheet", date_str=str(plan.service_date))

@login_required
def erase_plan_view(request, date_str: str):
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response
    service_date = _parse_date(date_str)
    plan = PrepPlan.objects.filter(team=request.team, service_date=service_date).first()
    if not plan:
        raise Http404("Plan not found.")
    services.erase_plan(plan)
    messages.success(request, "Prep list erased.")
    return redirect("planning:plan_list")

@login_required
def reopen_plan_view(request, date_str: str):
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response
    service_date = _parse_date(date_str)
    plan = PrepPlan.objects.filter(team=request.team, service_date=service_date).first()
    if not plan:
        raise Http404("Plan not found.")
    services.reopen_plan(plan)
    if plan.state == PrepPlan.PlanState.DRAFT:
        messages.success(request, "Prep list reopened for editing. You can edit or erase it now.")
        return redirect("planning:plan_builder", date_str=str(plan.service_date))
    messages.success(request, "Prep list reopened. Cooks can claim tasks and mark them done again.")
    return redirect("planning:plan_sheet", date_str=str(plan.service_date))


@login_required
def task_tap_view(request, pk: int):
    if request.method != "POST":
        return HttpResponse(status=405)
    task = services.task_tap(pk, request.user)
    _hydrate_plan_progress(task.plan)
    return render(
        request,
        "planning/partials/task_row_response.html",
        {"task": task, "groups": get_sheet_groups(task.plan), "extra_tasks": get_extra_tasks(task.plan)},
    )

@login_required
def task_claim_view(request, pk: int):
    if request.method != "POST":
        return HttpResponse(status=405)
    task = services.task_claim(pk, request.user)
    _hydrate_plan_progress(task.plan)
    return render(
        request,
        "planning/partials/task_row_response.html",
        {"task": task, "groups": get_sheet_groups(task.plan), "extra_tasks": get_extra_tasks(task.plan)},
    )

@login_required
def task_note_view(request, pk: int):
    task = PrepTask.objects.select_related(
        "plan", "dish_component__dish", "dish_component__component", "assignee"
    ).get(pk=pk)

    if request.method == "GET":
        note_edit = task.plan.state != PrepPlan.PlanState.COMPLETE
        return render(request, "planning/partials/task_row.html", {"task": task, "note_edit": note_edit})

    note = request.POST.get("daily_note", "")
    task = services.set_task_note(pk, note, request.user)
    _hydrate_plan_progress(task.plan)
    return render(
        request,
        "planning/partials/task_row_response.html",
        {"task": task, "groups": get_sheet_groups(task.plan), "extra_tasks": get_extra_tasks(task.plan)},
    )


def _adhoc_redirect(service_date):
    """Ad hoc tasks only exist in DRAFT, and the Builder is DRAFT's only
    screen now — always land back there."""
    return redirect("planning:plan_builder", date_str=str(service_date))


@login_required
def add_adhoc_tasks_view(request, date_str: str):
    if request.method != "POST":
        return HttpResponse(status=405)
    redirect_response = _require_active_team(request)
    if redirect_response:
        return redirect_response

    service_date = _parse_date(date_str)
    plan = PrepPlan.objects.filter(team=request.team, service_date=service_date).first()
    if not plan:
        raise Http404("Plan not found.")

    formset = AdHocTaskFormSet(request.POST, form_kwargs={"team": request.team})
    if not formset.is_valid():
        errors = "; ".join(
            error for form in formset.forms for error in form.errors.get("__all__", [])
        )
        messages.error(request, errors or "Could not add tasks.")
        return _adhoc_redirect(plan.service_date)

    added = 0
    try:
        with transaction.atomic():
            for form in formset.forms:
                if form.is_empty():
                    continue
                recipe = form.cleaned_data.get("recipe")
                if recipe:
                    services.add_recipe_task(plan, recipe, request.user)
                else:
                    services.add_manual_task(plan, form.cleaned_data["label"], request.user)
                added += 1
    except (ValueError, PermissionError) as e:
        messages.error(request, str(e))
        return _adhoc_redirect(plan.service_date)

    if added:
        messages.success(request, f"Added {added} task{'s' if added != 1 else ''}.")
    else:
        messages.info(request, "No tasks entered.")
    return _adhoc_redirect(plan.service_date)


@login_required
def remove_adhoc_task_view(request, pk: int):
    if request.method != "POST":
        return HttpResponse(status=405)
    task = PrepTask.objects.select_related("plan").filter(pk=pk).first()
    if not task:
        raise Http404("Task not found.")
    service_date = task.plan.service_date

    try:
        services.remove_adhoc_task(pk, request.user)
        messages.success(request, "Task removed.")
    except (ValueError, PermissionError) as e:
        messages.error(request, str(e))
    return _adhoc_redirect(service_date)
