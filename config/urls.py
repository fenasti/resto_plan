from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # You can keep admin enabled but unused; platform admin is in-app.
    path("admin/", admin.site.urls),

    path("accounts/", include("allauth.urls")),
    path("", include("home.urls")),
    path("profile/", include("accounts.urls")),
    path("menu/", include("menu.urls")),
    path("plans/", include("planning.urls")),
]