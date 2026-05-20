from django.contrib.auth.mixins import LoginRequiredMixin
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


class PlatformAdminRequiredMixin(LoginRequiredMixin):
    """
    Platform admin = user.is_staff. Used to create teams and grant staff to others.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect(reverse("home:index"))
        return super().dispatch(request, *args, **kwargs)
