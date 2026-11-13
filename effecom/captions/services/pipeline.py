import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from captions.models import CaptionTrack, Video
from captions.validators import validate_caption_segments

from .audio_extractor import extract_audio
from .errors import MediaProcessingError
from .transcription_engine import WhisperOptions, transcribe_audio
from .video_probe import probe_video


def _copy_original_video(video, destination):
    try:
        with video.original_video.open("rb") as source:
            with destination.open("wb") as target:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
    except OSError as exc:
        raise MediaProcessingError("The stored video could not be read.") from exc


def _report_progress(video_id, progress):
    now = timezone.now()
    Video.objects.filter(
        pk=video_id,
        status=Video.Status.TRANSCRIBING,
    ).update(
        progress=max(0, min(99, progress)),
        heartbeat_at=now,
        updated_at=now,
    )


def _make_progress_callback(video_id):
    last_write = time.monotonic()

    def report(progress):
        nonlocal last_write
        current_time = time.monotonic()
        if (
            current_time - last_write
            >= settings.CAPTION_PROGRESS_WRITE_INTERVAL_SECONDS
        ):
            _report_progress(video_id, progress)
            last_write = current_time

    return report


def _caption_language(detected_language):
    language = detected_language or settings.WHISPER_LANGUAGE
    if not language or language.strip().lower() == "auto":
        return "und"
    return language.strip()[:32]


def process_video(video_id):
    video = Video.objects.get(pk=video_id)
    if video.status != Video.Status.EXTRACTING_AUDIO:
        return False

    with tempfile.TemporaryDirectory(prefix="caption-video-") as directory:
        local_video = Path(directory) / "source-video"
        _copy_original_video(video, local_video)
        probe = probe_video(local_video)

        max_duration = settings.CAPTION_MAX_DURATION_MIN * 60
        if probe.duration_seconds > max_duration:
            raise MediaProcessingError(
                f"The video exceeds the {settings.CAPTION_MAX_DURATION_MIN} minute duration limit."
            )
        if video.duration is None:
            Video.objects.filter(
                pk=video_id,
                status=Video.Status.EXTRACTING_AUDIO,
            ).update(duration=probe.duration_seconds, updated_at=timezone.now())

        with extract_audio(local_video) as audio_path:
            now = timezone.now()
            transitioned = Video.objects.filter(
                pk=video_id,
                status=Video.Status.EXTRACTING_AUDIO,
            ).update(
                status=Video.Status.TRANSCRIBING,
                stage="Transcribing audio",
                heartbeat_at=now,
                updated_at=now,
            )
            if not transitioned:
                return False

            options = WhisperOptions(
                model_size=settings.WHISPER_MODEL_SIZE,
                device=settings.WHISPER_DEVICE,
                compute_type=settings.WHISPER_COMPUTE_TYPE,
                language=settings.WHISPER_LANGUAGE,
                beam_size=settings.WHISPER_BEAM_SIZE,
                vad_filter=settings.WHISPER_VAD,
                word_timestamps=settings.CAPTION_WORD_TIMESTAMPS,
            )
            result = transcribe_audio(
                audio_path,
                duration_seconds=probe.duration_seconds,
                options=options,
                progress_callback=_make_progress_callback(video_id),
            )
            validate_caption_segments(result.segments, probe.duration_seconds)

        now = timezone.now()
        transitioned = Video.objects.filter(
            pk=video_id,
            status=Video.Status.TRANSCRIBING,
        ).update(
            status=Video.Status.GENERATING_CAPTIONS,
            stage="Saving captions",
            heartbeat_at=now,
            updated_at=now,
        )
        if not transitioned:
            return False

    language = _caption_language(result.language)
    with transaction.atomic():
        video = Video.objects.select_for_update().get(pk=video_id)
        if video.status != Video.Status.GENERATING_CAPTIONS:
            return False
        CaptionTrack.objects.get_or_create(
            video=video,
            language=language,
            defaults={"segments": result.segments},
        )
        now = timezone.now()
        video.status = Video.Status.COMPLETED
        video.progress = 100
        video.stage = "Completed"
        video.detected_language = language
        video.error_message = ""
        video.heartbeat_at = now
        video.finished_at = now
        video.save(
            update_fields=(
                "status",
                "progress",
                "stage",
                "detected_language",
                "error_message",
                "heartbeat_at",
                "finished_at",
                "updated_at",
            )
        )
    return True
