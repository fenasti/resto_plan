from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse

from .models import TeamMembership

class ActiveTeamRequiredMixin(LoginRequiredMixin):
    """
    Requires authenticated user + active team in session.
    """
    def dispatch(self, request, *args, **kwargs):
        if not getattr(request, "team", None):
            return redirect(reverse("accounts:team_select"))
        return super().dispatch(request, *args, **kwargs)


class TeamMemberRequiredMixin(ActiveTeamRequiredMixin):
    """
    Requires membership in active team.
    """
    def dispatch(self, request, *args, **kwargs):
        if not getattr(request, "membership", None):
            if TeamMembership.objects.filter(user=request.user).exists():
                return redirect(reverse("accounts:team_select"))
            return redirect(reverse("accounts:team_start"))
        return super().dispatch(request, *args, **kwargs)


class TeamPermissionRequiredMixin(TeamMemberRequiredMixin):
    """
    Requires membership + a permission flag on membership.
    Set required_flag in subclasses.
    """
    required_flag: str = ""

    def dispatch(self, request, *args, **kwargs):
        membership = getattr(request, "membership", None)
        if not membership:
            if TeamMembership.objects.filter(user=request.user).exists():
                return redirect(reverse("accounts:team_select"))
            return redirect(reverse("accounts:team_start"))
        if self.required_flag and not getattr(membership, self.required_flag, False):
            # Fallback: owners/admins can do everything unless you want stricter.
            if membership.role not in (TeamMembership.Role.OWNER, TeamMembership.Role.ADMIN):
                return redirect(reverse("home:index"))
        return super().dispatch(request, *args, **kwargs)


class SearchablePaginatedListMixin:
    """
    Adds `?q=` search (icontains over `search_fields`) and pagination to a
    ListView. Subclasses provide the team-scoped base queryset via
    get_base_queryset() instead of overriding get_queryset() directly.
    """
    paginate_by = 20
    search_fields: list[str] = []

    def get_base_queryset(self):
        raise NotImplementedError

    def get_queryset(self):
        qs = self.get_base_queryset()
        query = self.request.GET.get("q", "").strip()
        if query and self.search_fields:
            q_filter = Q()
            for field in self.search_fields:
                q_filter |= Q(**{f"{field}__icontains": query})
            qs = qs.filter(q_filter)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class PlatformAdminRequiredMixin(LoginRequiredMixin):
    """
    Platform admin = user.is_staff. Used to create teams and grant staff to others.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect(reverse("home:index"))
        return super().dispatch(request, *args, **kwargs)
