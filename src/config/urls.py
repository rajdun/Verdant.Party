"""
URL configuration for config project.

Root urlconf — wires each domain app's own urls.py under a path prefix.
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('catalog/', include('apps.catalog.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('orders/', include('apps.orders.urls')),
    path('users/', include('apps.users.urls')),
    path('finance/', include('apps.finance.urls')),
    path('logistics/', include('apps.logistics.urls')),
    path('marketplaces/', include('apps.marketplaces.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
