from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import UpdateView, TemplateView, FormView

from .forms import (
    CookProfileForm,
    TeamCreateForm,
    TeamJoinForm,
    TeamSelectForm,
    MembershipUpdateForm,
    PlatformStaffToggleForm,
)
from .mixins import TeamMemberRequiredMixin, ActiveTeamRequiredMixin, PlatformAdminRequiredMixin, TeamPermissionRequiredMixin
from .models import CookProfile, Team, TeamMembership

User = get_user_model()


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = CookProfile
    form_class = CookProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user.cookprofile


class TeamSelectView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/team_select.html"

    def dispatch(self, request, *args, **kwargs):
        # ✅ Let LoginRequiredMixin redirect anonymous users first
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        # If a team is already active, go home
        if request.team:
            return redirect("home:index")

        memberships = TeamMembership.objects.filter(user=request.user).select_related("team")

        # If user has exactly 1 team, auto-select it (less friction)
        if memberships.count() == 1:
            request.session["active_team_id"] = memberships.first().team_id
            messages.success(request, "Workspace selected.")
            return redirect("home:index")

        # If user has none:
        if not memberships.exists():
            # Staff users should be able to create the first team
            if request.user.is_staff:
                return super().dispatch(request, *args, **kwargs)
            return redirect("accounts:team_join")

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        memberships = TeamMembership.objects.filter(user=request.user).select_related("team")
        teams = [m.team for m in memberships]
        form = TeamSelectForm(teams=teams)
        return render(request, self.template_name, {"form": form, "teams": teams})

    def post(self, request, *args, **kwargs):
        memberships = TeamMembership.objects.filter(user=request.user).select_related("team")
        teams = [m.team for m in memberships]
        form = TeamSelectForm(request.POST, teams=teams)
        if form.is_valid():
            team_id = int(form.cleaned_data["team_id"])
            request.session["active_team_id"] = team_id
            messages.success(request, "Workspace selected.")
            return redirect("home:index")
        return render(request, self.template_name, {"form": form, "teams": teams})


class TeamJoinView(LoginRequiredMixin, FormView):
    template_name = "accounts/team_join.html"
    form_class = TeamJoinForm
    success_url = reverse_lazy("home:index")

    def form_valid(self, form):
        code = form.cleaned_data["join_code"].strip()
        team = Team.objects.filter(join_code=code).first()
        if not team:
            messages.error(self.request, "Invalid join code.")
            return redirect("accounts:team_join")

        membership, created = TeamMembership.objects.get_or_create(user=self.request.user, team=team)
        if created:
            # Default member perms: none
            messages.success(self.request, f"Joined team: {team.name}")
        else:
            messages.info(self.request, f"Already in team: {team.name}")

        self.request.session["active_team_id"] = team.id
        return super().form_valid(form)


class TeamCreateView(PlatformAdminRequiredMixin, FormView):
    """
    Only platform admins (is_staff) can create teams.
    """
    template_name = "accounts/team_create.html"
    form_class = TeamCreateForm
    success_url = reverse_lazy("home:index")

    def form_valid(self, form):
        team: Team = form.save(commit=False)
        team.created_by = self.request.user
        team.join_code = Team.generate_join_code()
        # Ensure join_code uniqueness (rare collision)
        while Team.objects.filter(join_code=team.join_code).exists():
            team.join_code = Team.generate_join_code()
        team.save()

        # Creator becomes OWNER with full perms
        TeamMembership.objects.create(
            user=self.request.user,
            team=team,
            role=TeamMembership.Role.OWNER,
            can_manage_menu=True,
            can_manage_recipes=True,
            can_manage_team=True,
        )

        self.request.session["active_team_id"] = team.id
        messages.success(self.request, f"Team created: {team.name}")
        return super().form_valid(form)


class TeamManageView(TeamPermissionRequiredMixin, TemplateView):
    """
    Manage membership roles/permissions & rotate join code.
    Requires membership.can_manage_team OR OWNER/ADMIN role.
    """
    required_flag = "can_manage_team"
    template_name = "accounts/team_manage.html"

    def get(self, request, *args, **kwargs):
        team = request.team
        memberships = TeamMembership.objects.filter(team=team).select_related("user").order_by("user__username")
        return render(request, self.template_name, {"team": team, "memberships": memberships})

    def post(self, request, *args, **kwargs):
        team = request.team
        action = request.POST.get("action")

        if action == "rotate_code":
            team.rotate_join_code()
            messages.success(request, "Join code rotated.")
            return redirect("accounts:team_manage")

        if action == "update_member":
            membership_id = int(request.POST.get("membership_id"))
            membership = get_object_or_404(TeamMembership, id=membership_id, team=team)
            form = MembershipUpdateForm(request.POST, instance=membership)
            if form.is_valid():
                updated = form.save()
                # Owners/Admins should always have manage_team to avoid lockout
                if updated.role in (TeamMembership.Role.OWNER, TeamMembership.Role.ADMIN):
                    if not updated.can_manage_team:
                        updated.can_manage_team = True
                    if not updated.can_manage_menu:
                        updated.can_manage_menu = True
                    if not updated.can_manage_recipes:
                        updated.can_manage_recipes = True
                    updated.save(update_fields=["can_manage_team", "can_manage_menu", "can_manage_recipes"])
                messages.success(request, "Member updated.")
            else:
                messages.error(request, "Invalid member update.")
            return redirect("accounts:team_manage")

        return redirect("accounts:team_manage")


class PlatformAdminUsersView(PlatformAdminRequiredMixin, TemplateView):
    """
    In-app platform admin screen to grant is_staff to cooks.
    Replaces the need to use Django admin.
    """
    template_name = "accounts/platform_users.html"

    def get(self, request, *args, **kwargs):
        users = User.objects.all().order_by("username")
        return render(request, self.template_name, {"users": users})

    def post(self, request, *args, **kwargs):
        form = PlatformStaffToggleForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid request.")
            return redirect("accounts:platform_users")

        user = get_object_or_404(User, id=form.cleaned_data["user_id"])
        make_staff = bool(request.POST.get("make_staff"))

        user.is_staff = make_staff
        user.save(update_fields=["is_staff"])

        messages.success(request, f"Updated staff status for {user.username}: {user.is_staff}")
        return redirect("accounts:platform_users")