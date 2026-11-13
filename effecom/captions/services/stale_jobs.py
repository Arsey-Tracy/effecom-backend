from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from captions.models import Video


def fail_stale_caption_jobs():
    now = timezone.now()
    cutoff = now - timedelta(minutes=settings.CAPTION_STALE_JOB_MINUTES)
    stale_heartbeat = Q(heartbeat_at__lt=cutoff) | Q(
        heartbeat_at__isnull=True,
        started_at__lt=cutoff,
    )
    return Video.objects.filter(
        status__in=(
            Video.Status.QUEUED,
            Video.Status.EXTRACTING_AUDIO,
            Video.Status.TRANSCRIBING,
            Video.Status.GENERATING_CAPTIONS,
        )
    ).filter(stale_heartbeat).update(
        status=Video.Status.FAILED,
        stage="Failed",
        error_message="Processing stopped unexpectedly. Retry this video.",
        finished_at=now,
        heartbeat_at=now,
        updated_at=now,
    )
