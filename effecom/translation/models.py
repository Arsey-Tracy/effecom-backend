import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Language(models.Model):
    code = models.CharField(max_length=3, primary_key=True)
    name = models.CharField(max_length=100)
    supports_translation = models.BooleanField(default=False)
    supports_stt = models.BooleanField(default=False)
    supports_tts = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "code")

    def __str__(self):
        return f"{self.name} ({self.code})"


class GuestSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ip_hash = models.CharField(max_length=64, db_index=True)
    user_agent_hash = models.CharField(max_length=64, blank=True)
    translations_used = models.PositiveIntegerField(default=0)
    transcriptions_used = models.PositiveIntegerField(default=0)
    audio_seconds_used = models.PositiveIntegerField(default=0)
    characters_used = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=("ip_hash", "created_at"), name="guest_ip_created_idx"),
        ]


class TranslationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="translation_requests",
    )
    guest_session = models.ForeignKey(
        GuestSession,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="translation_requests",
    )
    source_language = models.CharField(max_length=3, blank=True)
    detected_source_language = models.CharField(max_length=3, blank=True)
    target_language = models.CharField(max_length=3)
    source_text = models.TextField()
    translated_text = models.TextField(blank=True)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    sunbird_job_id = models.CharField(max_length=100, blank=True)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error_code = models.CharField(max_length=50, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(user__isnull=False, guest_session__isnull=True)
                    | Q(user__isnull=True, guest_session__isnull=False)
                ),
                name="translation_exactly_one_owner",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-created_at"),
                name="trans_user_created_idx",
            ),
            models.Index(
                fields=("guest_session", "-created_at"),
                name="trans_guest_created_idx",
            ),
        ]
