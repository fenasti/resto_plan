from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import TemplateView

from ordering.models import OrderList
from ordering.selectors import get_order_list_queryset
from planning.models import PrepPlan
from planning.selectors import annotate_plan_progress


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "home/index.html"

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request, "team", None):
            return redirect("accounts:team_select")
        if not getattr(request, "membership", None):
            return redirect("accounts:team_join")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        team = self.request.team
        today = timezone.localdate()

        prep_queryset = annotate_plan_progress(PrepPlan.objects.filter(team=team))
        active_prep = (
            prep_queryset.filter(
                state=PrepPlan.PlanState.DRAFT,
                service_date__gte=today,
            )
            .order_by("service_date")
            .first()
        )
        if not active_prep:
            active_prep = prep_queryset.filter(service_date__gte=today).order_by("service_date").first()
        if not active_prep:
            active_prep = prep_queryset.first()

        order_queryset = get_order_list_queryset(team)
        active_order = (
            order_queryset.filter(state=OrderList.OrderState.DRAFT)
            .order_by("-order_date")
            .first()
        )
        if not active_order:
            active_order = order_queryset.first()

        ctx.update(
            {
                "today": today,
                "active_prep": active_prep,
                "active_order": active_order,
            }
        )
        return ctx
