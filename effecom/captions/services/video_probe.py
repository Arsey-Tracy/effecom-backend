import math
import tempfile
from dataclasses import dataclass
from pathlib import Path

import av
from django.conf import settings
from django.core.exceptions import ValidationError

from .errors import MediaProcessingError


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    has_video: bool
    has_audio: bool


def _stream_duration_seconds(stream):
    duration = getattr(stream, "duration", None)
    if duration is None:
        return None
    try:
        seconds = float(duration) * float(stream.time_base)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


def _container_duration_seconds(container):
    duration = getattr(container, "duration", None)
    if duration is not None:
        try:
            seconds = float(duration) / float(av.time_base)
        except (TypeError, ValueError, ZeroDivisionError):
            seconds = None
        if seconds is not None and math.isfinite(seconds) and seconds > 0:
            return seconds

    longest = None
    for stream in container.streams:
        seconds = _stream_duration_seconds(stream)
        if seconds is not None and (longest is None or seconds > longest):
            longest = seconds
    return longest


def probe_video(path):
    try:
        container = av.open(str(path))
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise MediaProcessingError(
            "The uploaded file is not a readable video."
        ) from exc

    try:
        stream_types = {
            stream.type
            for stream in container.streams
            if isinstance(stream.type, str)
        }
        duration = _container_duration_seconds(container)
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise MediaProcessingError(
            "The uploaded file has invalid video metadata."
        ) from exc
    finally:
        container.close()

    if not math.isfinite(duration or 0) or duration <= 0:
        raise MediaProcessingError("The uploaded video has no valid duration.")
    if not isinstance(stream_types, set) or not stream_types:
        raise MediaProcessingError("The uploaded file has invalid video metadata.")

    has_video = "video" in stream_types
    has_audio = "audio" in stream_types
    if not has_video:
        raise MediaProcessingError("The uploaded file does not contain a video stream.")
    if not has_audio:
        raise MediaProcessingError("The uploaded video does not contain an audio stream.")
    return VideoProbe(duration, has_video, has_audio)


def validate_video_upload(uploaded_file):
    extension = Path(getattr(uploaded_file, "name", "")).suffix.lower()
    if extension not in settings.CAPTION_ALLOWED_VIDEO_EXTENSIONS:
        extensions = ", ".join(settings.CAPTION_ALLOWED_VIDEO_EXTENSIONS)
        raise ValidationError(f"Choose a video file with one of these extensions: {extensions}.")

    max_bytes = settings.CAPTION_MAX_UPLOAD_MB * 1024 * 1024
    reported_size = getattr(uploaded_file, "size", None)
    if reported_size is None or reported_size <= 0:
        raise ValidationError("The uploaded video is empty.")
    if reported_size > max_bytes:
        raise ValidationError(
            f"The video exceeds the {settings.CAPTION_MAX_UPLOAD_MB} MB upload limit."
        )

    try:
        with tempfile.TemporaryDirectory(prefix="caption-probe-") as directory:
            video_path = Path(directory) / "upload"
            copied_size = 0
            with video_path.open("wb") as target:
                for chunk in uploaded_file.chunks():
                    copied_size += len(chunk)
                    if copied_size > max_bytes:
                        raise ValidationError(
                            f"The video exceeds the {settings.CAPTION_MAX_UPLOAD_MB} MB upload limit."
                        )
                    target.write(chunk)
            if copied_size == 0:
                raise ValidationError("The uploaded video is empty.")
            if copied_size != reported_size:
                raise ValidationError("The uploaded video could not be read completely.")
            try:
                probe = probe_video(video_path)
            except MediaProcessingError as exc:
                raise ValidationError(str(exc)) from exc
    except OSError as exc:
        raise ValidationError("The uploaded video could not be inspected.") from exc
    finally:
        uploaded_file.seek(0)

    max_duration = settings.CAPTION_MAX_DURATION_MIN * 60
    if probe.duration_seconds > max_duration:
        raise ValidationError(
            f"The video exceeds the {settings.CAPTION_MAX_DURATION_MIN} minute duration limit."
        )
    return probe