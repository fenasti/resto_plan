def team_context(request):
    return {
        "active_team": getattr(request, "team", None),
        "active_membership": getattr(request, "membership", None),
    }