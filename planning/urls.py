from django.urls import path
from . import views

app_name = "planning"

urlpatterns = [
    path("", views.PlanListView.as_view(), name="plan_list"),
    path("create/", views.create_tomorrow, name="create_tomorrow"),
    path("<str:date_str>/", views.PlanSheetView.as_view(), name="plan_sheet"),
    path("<str:date_str>/builder/", views.PlanBuilderView.as_view(), name="plan_builder"),

    path("<str:date_str>/complete/", views.complete_plan_view, name="plan_complete"),
    path("<str:date_str>/reopen/", views.reopen_plan_view, name="plan_reopen"),
    path("<str:date_str>/erase/", views.erase_plan_view, name="plan_erase"),

    path("tasks/<int:pk>/tap/", views.task_tap_view, name="task_tap"),
    path("tasks/<int:pk>/claim/", views.task_claim_view, name="task_claim"),
    path("tasks/<int:pk>/note/", views.task_note_view, name="task_note"),

    path("<str:date_str>/tasks/add/", views.add_adhoc_tasks_view, name="task_add_adhoc"),
    path("tasks/<int:pk>/remove/", views.remove_adhoc_task_view, name="task_remove_adhoc"),
]
