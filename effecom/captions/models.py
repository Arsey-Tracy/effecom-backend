import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import Q


def video_upload_path(instance, filename):
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.CAPTION_ALLOWED_VIDEO_EXTENSIONS:
        suffix = ""
    try:
        file_id = uuid.UUID(str(instance.pk)).hex
    except (AttributeError, TypeError, ValueError):
        file_id = uuid.uuid4().hex
    return f"captions/videos/{file_id}{suffix}"


class Video(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        QUEUED = "queued", "Queued"
        EXTRACTING_AUDIO = "extracting_audio", "Extracting audio"
        TRANSCRIBING = "transcribing", "Transcribing"
        GENERATING_CAPTIONS = "generating_captions", "Generating captions"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="caption_videos",
    )
    title = models.CharField(max_length=255)
    original_video = models.FileField(upload_to=video_upload_path)
    duration = models.FloatField(blank=True, null=True)
    file_size = models.PositiveBigIntegerField(default=0)
    detected_language = models.CharField(max_length=32, blank=True)
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.UPLOADED,
    )
    progress = models.PositiveSmallIntegerField(default=0)
    stage = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)
    heartbeat_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(blank=True, null=True)
    finished_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=("user", "-created_at"),
                name="cap_video_owner_created_idx",
            ),
            models.Index(
                fields=("status", "heartbeat_at"),
                name="cap_video_status_hb_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(progress__gte=0, progress__lte=100),
                name="caption_video_progress_range",
            )
        ]

    def __str__(self):
        return self.title


class CaptionTrack(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    video = models.ForeignKey(
        Video,
        on_delete=models.CASCADE,
        related_name="caption_tracks",
    )
    language = models.CharField(max_length=32)
    segments = models.JSONField(default=list)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("language",)
        constraints = [
            models.UniqueConstraint(
                fields=("video", "language"),
                name="cap_track_video_lang_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=("video", "-updated_at"),
                name="cap_track_video_updated_idx",
            )
        ]

    def __str__(self):
        return f"{self.video.title} ({self.language})"
