from django.urls import path

from apps.marketplaces import views

app_name = "marketplaces"

urlpatterns = [
    path("", views.MarketplaceListView.as_view(), name="marketplace_list"),
    path("dodaj/", views.MarketplaceCreateView.as_view(), name="marketplace_create"),
    path("oauth/callback/", views.oauth_callback, name="oauth_callback"),
    path("mapowania/", views.ListingListView.as_view(), name="listing_list"),
    path("mapowania/<int:pk>/edytuj/", views.ListingUpdateView.as_view(), name="listing_update"),
    path("mapowania/<int:pk>/usun/", views.ListingDeleteView.as_view(), name="listing_delete"),
    path("mapowania/<int:pk>/zakoncz/", views.listing_end, name="listing_end"),
    path("mapowania/<int:pk>/reaktywuj/", views.listing_reactivate, name="listing_reactivate"),
    path("synchronizacje/", views.SyncRunListView.as_view(), name="syncrun_list"),
    path("<int:pk>/", views.MarketplaceDetailView.as_view(), name="marketplace_detail"),
    path("<int:pk>/edytuj/", views.MarketplaceUpdateView.as_view(), name="marketplace_update"),
    path("<int:pk>/usun/", views.MarketplaceDeleteView.as_view(), name="marketplace_delete"),
    path("<int:pk>/dane-dostepowe/", views.marketplace_credentials, name="marketplace_credentials"),
    path("<int:pk>/polacz/", views.marketplace_connect, name="marketplace_connect"),
    path("<int:pk>/odswiez-token/", views.marketplace_refresh_token, name="marketplace_refresh_token"),
    path("<int:pk>/synchronizuj/", views.marketplace_sync, name="marketplace_sync"),
    path("<int:pk>/aktywuj/", views.marketplace_activate, name="marketplace_activate"),
    path("<int:pk>/dezaktywuj/", views.marketplace_deactivate, name="marketplace_deactivate"),
    path("<int:pk>/oferty/", views.external_listing_list, name="external_listing_list"),
    path("<int:pk>/oferty/mapuj/", views.listing_map, name="listing_map"),
]
