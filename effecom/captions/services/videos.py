from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from kombu.exceptions import OperationalError as KombuOperationalError
from redis.exceptions import RedisError

from captions.models import CaptionTrack, Video
from captions.tasks import transcribe_video
from captions.validators import validate_caption_segments

from .errors import (
    CaptionStorageError,
    CaptionVersionConflict,
    TaskQueueUnavailable,
    VideoStateConflict,
)
from .video_probe import validate_video_upload


def create_video(*, user, uploaded_file, title=None):
    probe = validate_video_upload(uploaded_file)
    if title is None:
        title = PurePosixPath(uploaded_file.name.replace("\\", "/")).stem
    video = Video(
        user=user,
        title=title,
        original_video=uploaded_file,
        duration=probe.duration_seconds,
        file_size=uploaded_file.size,
    )
    try:
        video.save()
    except OSError as exc:
        raise CaptionStorageError(
            "The uploaded video could not be stored."
        ) from exc
    return video


def owned_videos(user):
    return Video.objects.filter(user=user)


def get_owned_video(user, video_id):
    return owned_videos(user).filter(pk=video_id).first()


def delete_video(video):
    storage = video.original_video.storage
    stored_name = video.original_video.name
    if stored_name:
        try:
            storage.delete(stored_name)
        except OSError as exc:
            raise CaptionStorageError(
                "The video could not be removed from storage."
            ) from exc
    video.delete()


def queue_video(video):
    with transaction.atomic():
        queued_video = (
            Video.objects.select_for_update()
            .filter(pk=video.pk, user_id=video.user_id)
            .first()
        )
        if queued_video is None:
            return None
        if queued_video.status not in (Video.Status.UPLOADED, Video.Status.FAILED):
            raise VideoStateConflict

        now = timezone.now()
        queued_video.status = Video.Status.QUEUED
        queued_video.progress = 0
        queued_video.stage = "Queued"
        queued_video.error_message = ""
        queued_video.heartbeat_at = now
        queued_video.started_at = None
        queued_video.finished_at = None
        queued_video.save(
            update_fields=(
                "status",
                "progress",
                "stage",
                "error_message",
                "heartbeat_at",
                "started_at",
                "finished_at",
                "updated_at",
            )
        )

    try:
        transcribe_video.delay(str(queued_video.pk))
    except (KombuOperationalError, RedisError, OSError) as exc:
        now = timezone.now()
        Video.objects.filter(
            pk=queued_video.pk,
            status=Video.Status.QUEUED,
        ).update(
            status=Video.Status.FAILED,
            stage="Failed",
            error_message="The transcription job could not be queued. Please retry.",
            finished_at=now,
            heartbeat_at=now,
            updated_at=now,
        )
        raise TaskQueueUnavailable from exc
    return Video.objects.get(pk=queued_video.pk, user_id=video.user_id)


def get_caption_track(video, language=None):
    tracks = video.caption_tracks.all()
    if language:
        return tracks.filter(language=language).first()
    if video.detected_language:
        selected = tracks.filter(language=video.detected_language).first()
        if selected is not None:
            return selected
    return tracks.first()


def _validate_segment_id(segment_id, field_name):
    if isinstance(segment_id, bool) or not isinstance(segment_id, (str, int)):
        raise ValidationError(f"{field_name} must be a string or integer.")
    if isinstance(segment_id, str) and not segment_id.strip():
        raise ValidationError(f"{field_name} must not be empty.")


def _merge_caption_segments(current_segments, updates, deleted_ids, duration):
    if not isinstance(current_segments, list):
        raise ValidationError("The saved caption segments are invalid.")

    existing = {}
    for index, segment in enumerate(current_segments):
        if not isinstance(segment, dict):
            raise ValidationError("The saved caption segments are invalid.")
        segment_id = segment.get("id")
        _validate_segment_id(segment_id, f"segments[{index}].id")
        if segment_id in existing:
            raise ValidationError("The saved caption segment ids are not unique.")
        existing[segment_id] = segment

    deleted = set()
    for index, segment_id in enumerate(deleted_ids):
        _validate_segment_id(segment_id, f"deleted_ids[{index}]")
        if segment_id in deleted:
            raise ValidationError("deleted_ids must not contain duplicates.")
        if segment_id not in existing:
            raise ValidationError("A deleted segment id does not exist.")
        deleted.add(segment_id)

    updated = {}
    for index, segment in enumerate(updates):
        if not isinstance(segment, dict):
            raise ValidationError(f"segments[{index}] must be an object.")
        segment_id = segment.get("id")
        _validate_segment_id(segment_id, f"segments[{index}].id")
        if segment_id in updated:
            raise ValidationError("Updated segment ids must be unique.")
        if segment_id in deleted:
            raise ValidationError("A segment cannot be updated and deleted.")
        if segment_id in existing:
            updated[segment_id] = {**existing[segment_id], **segment}
        else:
            updated[segment_id] = segment

    merged = []
    for segment in current_segments:
        segment_id = segment["id"]
        if segment_id in deleted:
            continue
        merged.append(updated.pop(segment_id, segment))
    merged.extend(updated.values())

    for segment in merged:
        validate_caption_segments([segment], duration)
    merged.sort(key=lambda segment: float(segment["start"]))
    validate_caption_segments(merged, duration)
    return merged


def update_caption_track(*, video, language, version, segments, deleted_ids):
    track = CaptionTrack.objects.filter(video=video, language=language).first()
    if track is None:
        raise CaptionTrack.DoesNotExist
    if track.version != version:
        raise CaptionVersionConflict(track.version)

    merged_segments = _merge_caption_segments(
        track.segments,
        segments,
        deleted_ids,
        video.duration,
    )
    updated = CaptionTrack.objects.filter(
        pk=track.pk,
        version=version,
    ).update(
        segments=merged_segments,
        version=F("version") + 1,
        updated_at=timezone.now(),
    )
    if not updated:
        current_version = CaptionTrack.objects.filter(pk=track.pk).values_list(
            "version",
            flat=True,
        ).first()
        if current_version is None:
            raise CaptionTrack.DoesNotExist
        raise CaptionVersionConflict(current_version)

    track.refresh_from_db()
    return track
