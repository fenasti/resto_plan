from django.urls import path
from .views import (
    ProfileUpdateView,
    TeamSelectView,
    TeamJoinView,
    TeamCreateView,
    TeamManageView,
    PlatformAdminUsersView,
)

app_name = "accounts"

urlpatterns = [
    path("", ProfileUpdateView.as_view(), name="profile"),

    path("teams/select/", TeamSelectView.as_view(), name="team_select"),
    path("teams/join/", TeamJoinView.as_view(), name="team_join"),
    path("teams/create/", TeamCreateView.as_view(), name="team_create"),
    path("teams/manage/", TeamManageView.as_view(), name="team_manage"),

    path("platform/users/", PlatformAdminUsersView.as_view(), name="platform_users"),
]