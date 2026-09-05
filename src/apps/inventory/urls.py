from django.urls import path

from apps.inventory import views

app_name = "inventory"

urlpatterns = [
    path("", views.StockOverviewView.as_view(), name="stock_overview"),
    path("przyjecia/", views.StockBatchListView.as_view(), name="stockbatch_list"),
    path("przyjecia/dodaj/", views.StockBatchCreateView.as_view(), name="stockbatch_create"),
    path("przyjecia/<int:pk>/edytuj/", views.StockBatchUpdateView.as_view(), name="stockbatch_update"),
    path("przyjecia/<int:pk>/usun/", views.StockBatchDeleteView.as_view(), name="stockbatch_delete"),
    path("przyjecia/<int:pk>/zmien-lokalizacje/", views.stockbatch_relocate, name="stockbatch_relocate"),
    path("lokalizacje/", views.LocationListView.as_view(), name="location_list"),
    path("lokalizacje/dodaj/", views.LocationCreateView.as_view(), name="location_create"),
    path("lokalizacje/<int:pk>/edytuj/", views.LocationUpdateView.as_view(), name="location_update"),
    path("lokalizacje/<int:pk>/usun/", views.LocationDeleteView.as_view(), name="location_delete"),
    path("lokalizacje/<int:pk>/aktywuj/", views.location_activate, name="location_activate"),
    path("lokalizacje/<int:pk>/dezaktywuj/", views.location_deactivate, name="location_deactivate"),
]
