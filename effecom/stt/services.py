from django.conf import settings
from django.db import transaction
from django.utils import timezone

from account.models import Activity
from effecom.sunbird import SunbirdError, post_file_task
from translation.api import QuotaExceeded
from translation.models import GuestSession


def _reserve_guest_audio(guest_session, audio_seconds):
    with transaction.atomic():
        guest = GuestSession.objects.select_for_update().get(pk=guest_session.pk)
        if guest.expires_at <= timezone.now():
            raise QuotaExceeded(
                api_code="guest_session_expired",
                detail="Guest session expired. Start a new trial session.",
            )
        if guest.transcriptions_used >= settings.GUEST_LIMITS["transcriptions"]:
            raise QuotaExceeded(
                api_code="transcription_quota_exceeded",
                detail="Guest transcription limit reached.",
            )
        if (
            guest.audio_seconds_used + audio_seconds
            > settings.GUEST_LIMITS["audio_seconds"]
        ):
            raise QuotaExceeded(
                api_code="audio_quota_exceeded",
                detail="Guest audio duration limit reached.",
            )
        guest.transcriptions_used += 1
        guest.audio_seconds_used += audio_seconds
        guest.save(update_fields=("transcriptions_used", "audio_seconds_used"))
        return guest.pk


def _release_guest_audio(guest_id, audio_seconds):
    with transaction.atomic():
        guest = GuestSession.objects.select_for_update().get(pk=guest_id)
        guest.transcriptions_used = max(0, guest.transcriptions_used - 1)
        guest.audio_seconds_used = max(0, guest.audio_seconds_used - audio_seconds)
        guest.save(update_fields=("transcriptions_used", "audio_seconds_used"))


def transcribe(owner, validated_data):
    audio = validated_data["audio"]
    language = validated_data["language"]
    audio_seconds = validated_data["audio_seconds"]
    guest_id = None

    if not getattr(owner, "is_authenticated", False):
        guest_id = _reserve_guest_audio(owner, audio_seconds)

    try:
        result = post_file_task(
            "/tasks/audio/transcriptions",
            files={"audio": ("recording.wav", audio, "audio/wav")},
            data={"language": language},
            timeout=(
                settings.SUNBIRD_CONNECT_TIMEOUT_SECONDS,
                settings.SUNBIRD_STT_TIMEOUT_SECONDS,
            ),
        )
        transcription = result.get("audio_transcription")
        if not isinstance(transcription, str):
            raise SunbirdError(
                "Sunbird returned an invalid transcription response.",
                code="upstream_invalid_response",
            )
    except SunbirdError:
        if guest_id is not None:
            _release_guest_audio(guest_id, audio_seconds)
        raise

    if getattr(owner, "is_authenticated", False):
        Activity.objects.create(
            user=owner,
            tool=Activity.Tool.STT,
            text=transcription,
            language=language,
            result=result,
        )

    return result
