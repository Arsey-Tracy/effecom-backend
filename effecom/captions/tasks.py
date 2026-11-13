import logging
from threading import Event, Thread

from celery import shared_task
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections
from django.utils import timezone

from captions.models import Video
from captions.services.errors import (
    MediaProcessingError,
    RetryableTranscriptionError,
    TranscriptionModelError,
)
from captions.services.pipeline import process_video


logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = (
    Video.Status.EXTRACTING_AUDIO,
    Video.Status.TRANSCRIBING,
    Video.Status.GENERATING_CAPTIONS,
)


def _update_heartbeat(video_id, stop_event):
    try:
        while not stop_event.wait(settings.CAPTION_HEARTBEAT_INTERVAL_SECONDS):
            close_old_connections()
            now = timezone.now()
            try:
                updated = Video.objects.filter(
                    pk=video_id,
                    status__in=_ACTIVE_STATUSES,
                ).update(heartbeat_at=now, updated_at=now)
            except DatabaseError:
                logger.exception(
                    "Caption worker heartbeat update failed.",
                    extra={"video_id": str(video_id)},
                )
                return
            if not updated:
                return
    finally:
        close_old_connections()


def _mark_failed(video_id, error_message):
    now = timezone.now()
    return Video.objects.filter(
        pk=video_id,
        status__in=_ACTIVE_STATUSES,
    ).update(
        status=Video.Status.FAILED,
        stage="Failed",
        error_message=error_message,
        finished_at=now,
        heartbeat_at=now,
        updated_at=now,
    )


def _safe_error_message(error):
    if isinstance(error, MediaProcessingError):
        return str(error)
    if isinstance(error, TranscriptionModelError):
        return "The transcription model could not be loaded. Please try again later."
    if isinstance(error, ValidationError):
        return "The generated captions did not pass validation."
    return "Transcription could not be completed. Please retry the job."


def _requeue_for_retry(video_id):
    now = timezone.now()
    return Video.objects.filter(
        pk=video_id,
        status__in=_ACTIVE_STATUSES,
    ).update(
        status=Video.Status.QUEUED,
        stage="Queued for retry",
        error_message="",
        finished_at=None,
        heartbeat_at=now,
        updated_at=now,
    )


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True)
def transcribe_video(self, video_id):
    now = timezone.now()
    claimed = Video.objects.filter(
        pk=video_id,
        status=Video.Status.QUEUED,
    ).update(
        status=Video.Status.EXTRACTING_AUDIO,
        stage="Extracting audio",
        progress=0,
        error_message="",
        started_at=now,
        finished_at=None,
        heartbeat_at=now,
        updated_at=now,
    )
    if not claimed:
        logger.info(
            "Skipping duplicate or inactive caption task.",
            extra={"video_id": str(video_id)},
        )
        return "skipped"

    heartbeat_stop = Event()
    heartbeat_thread = Thread(
        target=_update_heartbeat,
        args=(video_id, heartbeat_stop),
        name=f"caption-heartbeat-{video_id}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        completed = process_video(video_id)
        return "completed" if completed else "inactive"
    except RetryableTranscriptionError as exc:
        if self.request.retries < settings.CAPTION_TASK_MAX_RETRIES:
            if _requeue_for_retry(video_id):
                logger.warning(
                    "Retrying caption transcription after a transient model error.",
                    extra={
                        "video_id": str(video_id),
                        "retry": self.request.retries + 1,
                    },
                )
                raise self.retry(
                    exc=exc,
                    countdown=settings.CAPTION_TASK_RETRY_DELAY_SECONDS,
                    max_retries=settings.CAPTION_TASK_MAX_RETRIES,
                )
        _mark_failed(video_id, _safe_error_message(exc))
        logger.exception(
            "Caption transcription failed after retries.",
            extra={
                "video_id": str(video_id),
                "error_type": type(exc).__name__,
            },
        )
        raise
    except Exception as exc:
        _mark_failed(video_id, _safe_error_message(exc))
        logger.exception(
            "Caption transcription failed.",
            extra={
                "video_id": str(video_id),
                "error_type": type(exc).__name__,
            },
        )
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(
            timeout=settings.CAPTION_HEARTBEAT_INTERVAL_SECONDS + 1
        )
