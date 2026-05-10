from django.urls import path
from . import views

app_name = "planning"

urlpatterns = [
    path("", views.PlanListView.as_view(), name="plan_list"),
    path("create/", views.create_tomorrow, name="create_tomorrow"),
    path("<str:date_str>/", views.PlanSheetView.as_view(), name="plan_sheet"),
    path("<str:date_str>/builder/", views.PlanBuilderView.as_view(), name="plan_builder"),

    path("<str:date_str>/finalize/", views.finalize_plan_view, name="plan_finalize"),
    path("<str:date_str>/reopen/", views.reopen_plan_view, name="plan_reopen"),
    path("<str:date_str>/refresh/", views.refresh_plan_view, name="plan_refresh"),
    path("<str:date_str>/erase/", views.erase_plan_view, name="plan_erase"),

    path("tasks/<int:pk>/tap/", views.task_tap_view, name="task_tap"),
    path("tasks/<int:pk>/claim/", views.task_claim_view, name="task_claim"),
    path("tasks/<int:pk>/note/", views.task_note_view, name="task_note"),
]
