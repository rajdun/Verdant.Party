from django.urls import path

from apps.orders import views

app_name = "orders"

urlpatterns = [
    path("", views.OrderListView.as_view(), name="order_list"),
    path("<int:pk>/", views.OrderDetailView.as_view(), name="order_detail"),
    path("<int:pk>/realizuj/", views.order_start_fulfillment, name="order_start_fulfillment"),
    path("<int:pk>/wyslij/", views.order_mark_shipped, name="order_mark_shipped"),
    path("<int:pk>/anuluj/", views.order_cancel, name="order_cancel"),
]
