from django.urls import path

from . import views

app_name = "ordering"

urlpatterns = [
    path("", views.OrderListView.as_view(), name="order_list"),
    path("create/", views.create_today_order, name="order_create"),
    path("create/blank/", views.create_blank_today_order, name="order_create_blank"),
    path("<str:date_str>/", views.OrderDetailView.as_view(), name="order_detail"),
    path("<str:date_str>/clone/", views.clone_order_to_today_view, name="order_clone"),
    path("<str:date_str>/export/", views.export_order_excel, name="order_export"),
]

