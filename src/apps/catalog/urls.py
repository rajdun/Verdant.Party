from django.urls import path

from apps.catalog import views

app_name = "catalog"

urlpatterns = [
    path("", views.ProductListView.as_view(), name="product_list"),
    path("products/add/", views.ProductCreateView.as_view(), name="product_create"),
    path("products/<slug:slug>/", views.ProductDetailView.as_view(), name="product_detail"),
    path("products/<slug:slug>/edit/", views.ProductUpdateView.as_view(), name="product_update"),
    path("products/<slug:slug>/delete/", views.ProductDeleteView.as_view(), name="product_delete"),
    path("products/<slug:slug>/activate/", views.product_activate, name="product_activate"),
    path("products/<slug:slug>/deactivate/", views.product_deactivate, name="product_deactivate"),
    path("products/<slug:slug>/images/add/", views.product_image_add, name="product_image_add"),
    path("images/<int:pk>/delete/", views.product_image_delete, name="product_image_delete"),
    path("images/<int:pk>/set-primary/", views.product_image_set_primary, name="product_image_set_primary"),
    path("products/<slug:slug>/images/reorder/", views.product_image_reorder, name="product_image_reorder"),
]
