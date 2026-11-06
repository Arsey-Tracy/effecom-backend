from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings


class User(AbstractUser):
    email = models.EmailField(unique=True)

    def __str__(self):
        return self.email


class Activity(models.Model):
    class Tool(models.TextChoices):
        TTS = "tts", "Text-to-Speech"
        STT = "stt", "Speech-to-Text"
        TRANSLATION = "translation", "Translation"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="activities",
    )
    tool = models.CharField(max_length=16, choices=Tool.choices)
    text = models.TextField(max_length=2000)
    language = models.CharField(max_length=16, blank=True)
    voice = models.CharField(max_length=64, blank=True)
    source_language = models.CharField(max_length=16, blank=True)
    target_language = models.CharField(max_length=16, blank=True)
    result = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.get_tool_display()} for {self.user.email}"
