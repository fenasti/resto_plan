from django.contrib import admin

from .models import CookProfile, Team, TeamMembership

# Registered for debugging a live tenant's data (a stuck membership, a bad
# team row) without a Django shell — day-to-day management stays in-app.
# Reachable only by a true superuser: is_staff alone (the in-app "platform
# admin" toggle) grants no object permissions on its own.


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "display_name", "join_code", "created_by", "created_at")
    search_fields = ("name", "display_name")


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "team", "role", "can_manage_menu", "can_manage_recipes", "can_manage_team")
    list_filter = ("team", "role")
    search_fields = ("user__username", "team__name")


@admin.register(CookProfile)
class CookProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name")
    search_fields = ("user__username", "display_name")
