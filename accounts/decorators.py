from functools import wraps

from django.shortcuts import redirect

from .models import TeamMembership


def team_permission_required(flag):
    """
    Function-view equivalent of TeamPermissionRequiredMixin: requires
    request.membership to have `flag` set, or be OWNER/ADMIN. Redirects to
    home otherwise.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            membership = getattr(request, "membership", None)
            if not membership or (
                not getattr(membership, flag, False)
                and membership.role not in (TeamMembership.Role.OWNER, TeamMembership.Role.ADMIN)
            ):
                return redirect("home:index")
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator
