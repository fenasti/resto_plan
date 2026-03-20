from .models import Team, TeamMembership

class ActiveTeamMiddleware:
    """
    Adds request.team and request.membership based on session['active_team_id'].
    Does not redirect (views/mixins handle gating).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.team = None
        request.membership = None

        if request.user.is_authenticated:
            team_id = request.session.get("active_team_id")
            if team_id:
                team = Team.objects.filter(id=team_id).first()
                if team:
                    request.team = team
                    request.membership = TeamMembership.objects.filter(user=request.user, team=team).first()

        return self.get_response(request)