from django.urls import path

from .views_v1 import (
    GuestSessionView,
    GuestUsageView,
    LanguageListView,
    TranslationDetailView,
    TranslationListCreateView,
)

urlpatterns = [
    path("languages/", LanguageListView.as_view(), name="language-list"),
    path("guest/session/", GuestSessionView.as_view(), name="guest-session"),
    path("guest/usage/", GuestUsageView.as_view(), name="guest-usage"),
    path("translations/", TranslationListCreateView.as_view(), name="translation-list"),
    path(
        "translations/<uuid:pk>/",
        TranslationDetailView.as_view(),
        name="translation-detail",
    ),
]
