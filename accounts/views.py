import cloudinary.exceptions
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.core.paginator import Paginator
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import UpdateView, TemplateView, FormView

from .forms import (
    CookProfileForm,
    TeamCreateForm,
    TeamJoinForm,
    TeamSelectForm,
    TeamAppearanceForm,
    MembershipUpdateForm,
    PlatformStaffToggleForm,
)
from .mixins import PlatformAdminRequiredMixin, TeamPermissionRequiredMixin
from .models import CookProfile, Team, TeamMembership

User = get_user_model()


class ProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = CookProfile
    form_class = CookProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user.cookprofile

    def form_valid(self, form):
        # form.save() uploads the avatar to Cloudinary synchronously — an
        # outage or bad credentials there shouldn't surface as a raw 500.
        try:
            response = super().form_valid(form)
        except cloudinary.exceptions.Error:
            messages.error(self.request, "Could not upload image. Please try again.")
            return self.render_to_response(self.get_context_data(form=form))
        messages.success(self.request, "Profile updated.")
        return response

    def form_invalid(self, form):
        messages.error(self.request, "Could not update profile. Please check the form errors.")
        return super().form_invalid(form)


class TeamSelectView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/team_select.html"

    def dispatch(self, request, *args, **kwargs):
        # Let LoginRequiredMixin redirect anonymous users first
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        memberships = TeamMembership.objects.filter(user=request.user).select_related("team")

        # If user has none, there's nothing to pick between.
        if not memberships.exists():
            return redirect("accounts:team_start")

        # Auto-select only on a genuinely-no-active-team landing (first
        # login, or an active team that no longer applies) — never when a
        # team is already active, since that's exactly when this page is
        # reached deliberately via the navbar's "Switch" button. The old
        # "if request.team: redirect home" check fired on every single
        # Switch click (you always have an active team when clicking it),
        # so the picker could never actually be reached — Switch couldn't
        # switch anything.
        if memberships.count() == 1 and not request.team:
            request.session["active_team_id"] = memberships.first().team_id
            messages.success(request, "Workspace selected.")
            return redirect("home:index")

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


class TeamStartView(LoginRequiredMixin, TemplateView):
    template_name = "accounts/team_start.html"

    def dispatch(self, request, *args, **kwargs):
        if request.team:
            return redirect("home:index")

        memberships = TeamMembership.objects.filter(user=request.user)
        if memberships.exists():
            return redirect("accounts:team_select")

        return super().dispatch(request, *args, **kwargs)


class TeamJoinView(LoginRequiredMixin, FormView):
    """
    Join codes are only 6 digits (1M possibilities) and every team is a
    different operation's private kitchen data, so unlimited guesses would
    let anyone script their way into a workspace they don't belong to.
    Capped at JOIN_RATE_LIMIT_MAX attempts per JOIN_RATE_LIMIT_WINDOW.
    """
    template_name = "accounts/team_join.html"
    form_class = TeamJoinForm
    success_url = reverse_lazy("home:index")

    JOIN_RATE_LIMIT_MAX = 5
    JOIN_RATE_LIMIT_WINDOW = 300  # seconds

    def _rate_limit_key(self):
        return f"team_join_attempts:{self.request.user.id}"

    def form_valid(self, form):
        key = self._rate_limit_key()
        if cache.get(key, 0) >= self.JOIN_RATE_LIMIT_MAX:
            messages.error(self.request, "Too many incorrect join codes. Please wait a few minutes and try again.")
            return redirect("accounts:team_join")

        code = form.cleaned_data["join_code"].strip()
        team = Team.objects.filter(join_code=code).first()
        if not team:
            cache.set(key, cache.get(key, 0) + 1, self.JOIN_RATE_LIMIT_WINDOW)
            messages.error(self.request, "Invalid join code.")
            return redirect("accounts:team_join")

        cache.delete(key)
        membership, created = TeamMembership.objects.get_or_create(user=self.request.user, team=team)
        if created:
            # New members can manage menu/recipes by default; team admin
            # access is granted separately by an OWNER/ADMIN.
            messages.success(self.request, f"Joined team: {team.name}")
        else:
            messages.info(self.request, f"Already in team: {team.name}")

        self.request.session["active_team_id"] = team.id
        return super().form_valid(form)


class TeamCreateView(LoginRequiredMixin, FormView):
    """
    Any signed-in user can create a new workspace and becomes its OWNER —
    this is the self-service signup path for a new restaurant, not a
    platform-admin action. (is_staff is a separate, unrelated concern: it
    only controls Django admin / the platform-admin screens below.)
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
        appearance_form = TeamAppearanceForm(instance=team)
        return render(
            request,
            self.template_name,
            {"team": team, "memberships": memberships, "appearance_form": appearance_form},
        )

    def post(self, request, *args, **kwargs):
        team = request.team
        action = request.POST.get("action")

        if action == "rotate_code":
            team.rotate_join_code()
            messages.success(request, "Join code rotated.")
            return redirect("accounts:team_manage")

        if action == "update_appearance":
            appearance_form = TeamAppearanceForm(request.POST, instance=team)
            if appearance_form.is_valid():
                appearance_form.save()
                messages.success(request, "Appearance updated.")
            else:
                messages.error(request, "Could not update appearance.")
            return redirect("accounts:team_manage")

        if action in ("update_member", "remove_member"):
            try:
                membership_id = int(request.POST.get("membership_id", ""))
            except (TypeError, ValueError):
                messages.error(request, "Invalid member.")
                return redirect("accounts:team_manage")
            membership = get_object_or_404(TeamMembership, id=membership_id, team=team)

            # The workspace owner is fixed: no one can demote or remove them
            # here, so an admin can never lock the real owner out.
            if membership.role == TeamMembership.Role.OWNER:
                messages.error(request, "The workspace owner can't be changed or removed here.")
                return redirect("accounts:team_manage")

            if action == "remove_member":
                removed_username = membership.user.username
                membership.delete()
                messages.success(request, f"Removed {removed_username} from the team.")
                return redirect("accounts:team_manage")

            form = MembershipUpdateForm(request.POST, instance=membership)
            if form.is_valid():
                updated = form.save()
                # Admins should always have full perms, same as the owner
                if updated.role == TeamMembership.Role.ADMIN:
                    fields_to_set = [
                        f for f in ("can_manage_team", "can_manage_menu", "can_manage_recipes")
                        if not getattr(updated, f)
                    ]
                    if fields_to_set:
                        for f in fields_to_set:
                            setattr(updated, f, True)
                        updated.save(update_fields=fields_to_set)
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
        page_obj = Paginator(User.objects.all().order_by("username"), 25).get_page(request.GET.get("page"))
        return render(
            request,
            self.template_name,
            {"users": page_obj, "page_obj": page_obj, "is_paginated": page_obj.has_other_pages()},
        )

    def post(self, request, *args, **kwargs):
        form = PlatformStaffToggleForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Invalid request.")
            return redirect("accounts:platform_users")

        user = get_object_or_404(User, id=form.cleaned_data["user_id"])
        make_staff = bool(request.POST.get("make_staff"))

        # Without this, the last platform admin could remove their own (or
        # anyone's) final is_staff flag, leaving nobody able to grant it back
        # in-app — the only recovery would be a direct DB/shell fix.
        if not make_staff and user.is_staff and not User.objects.filter(is_staff=True).exclude(id=user.id).exists():
            messages.error(request, "Can't remove the last platform admin.")
            return redirect("accounts:platform_users")

        user.is_staff = make_staff
        user.save(update_fields=["is_staff"])

        messages.success(request, f"Updated staff status for {user.username}: {user.is_staff}")
        return redirect("accounts:platform_users")
