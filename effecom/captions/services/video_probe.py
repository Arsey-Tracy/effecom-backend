import json
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

from .errors import MediaProcessingError


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    has_video: bool
    has_audio: bool


def probe_video(path):
    command = [
        settings.FFPROBE_BINARY,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=settings.CAPTION_FFPROBE_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        raise MediaProcessingError(
            "FFprobe is unavailable. Install it to validate video uploads."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessingError("Video inspection timed out.") from exc
    except OSError as exc:
        raise MediaProcessingError("Video inspection could not be started.") from exc

    if result.returncode != 0:
        raise MediaProcessingError("The uploaded file is not a readable video.")
    try:
        metadata = json.loads(result.stdout)
        streams = metadata["streams"]
        duration = float(metadata["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaProcessingError("The uploaded file has invalid video metadata.") from exc

    if not math.isfinite(duration) or duration <= 0:
        raise MediaProcessingError("The uploaded video has no valid duration.")
    if not isinstance(streams, list):
        raise MediaProcessingError("The uploaded file has invalid video metadata.")

    stream_types = {
        stream.get("codec_type")
        for stream in streams
        if isinstance(stream, dict)
    }
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
