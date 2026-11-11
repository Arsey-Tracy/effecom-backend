from django.urls import path

from .views import (
    CurrentAccountView,
    LoginView,
    LogoutView,
    RefreshView,
    RegisterView,
    csrf_token,
)
from .options import ToolOptionsView

urlpatterns = [
    path("options/", ToolOptionsView.as_view(), name="tool-options"),
    path("csrf/", csrf_token, name="csrf-token"),
    path("register/", RegisterView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("token/refresh/", RefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", CurrentAccountView.as_view(), name="current-account"),
]
