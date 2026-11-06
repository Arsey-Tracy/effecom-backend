from django.urls import path

from .views import SpeechToTextView

urlpatterns = [
    path("", SpeechToTextView.as_view(), name="speech-to-text"),
]