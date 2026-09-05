from django.conf import settings
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect
from django.urls import reverse


def root_redirect(request):
    """Landing page: catalog for logged-in users, login form otherwise."""
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    return redirect(reverse(settings.LOGIN_URL))


class VerdantLoginView(LoginView):
    template_name = "users/login.html"
    redirect_authenticated_user = True


class VerdantLogoutView(LogoutView):
    pass
