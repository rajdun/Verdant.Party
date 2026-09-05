from django.urls import path

from apps.logistics import views

app_name = "logistics"

urlpatterns = [
    path("realizacja/", views.FulfillmentBatchListView.as_view(), name="batch_list"),
    path("realizacja/utworz/", views.batch_create, name="batch_create"),
    path("realizacja/<int:pk>/", views.batch_summary, name="batch_summary"),
    path("realizacja/<int:pk>/zbieranie/", views.batch_picking, name="batch_picking"),
    path("realizacja/<int:pk>/pakowanie/", views.batch_packing, name="batch_packing"),
    path(
        "realizacja/<int:pk>/pakowanie/<int:order_pk>/",
        views.batch_packing_order,
        name="batch_packing_order",
    ),
    path(
        "realizacja/<int:pk>/pakowanie/<int:order_pk>/zatwierdz/",
        views.order_pack_confirm,
        name="order_pack_confirm",
    ),
    path(
        "realizacja/<int:pk>/pakowanie/<int:order_pk>/koszt-allegro/",
        views.order_fetch_shipping_cost,
        name="order_fetch_shipping_cost",
    ),
    path("realizacja/<int:pk>/zakoncz/", views.batch_finish, name="batch_finish"),
    path("realizacja/<int:pk>/anuluj/", views.batch_cancel, name="batch_cancel"),
]
