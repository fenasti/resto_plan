from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views.generic import TemplateView

class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "home/index.html"

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request, "team", None):
            return redirect("accounts:team_select")
        if not getattr(request, "membership", None):
            return redirect("accounts:team_join")
        return super().dispatch(request, *args, **kwargs)