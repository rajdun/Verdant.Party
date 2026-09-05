from django.urls import path

from apps.users import views

app_name = "users"

urlpatterns = [
    path("login/", views.VerdantLoginView.as_view(), name="login"),
    path("logout/", views.VerdantLogoutView.as_view(), name="logout"),
]
