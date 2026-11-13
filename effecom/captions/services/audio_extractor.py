import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

from .errors import MediaProcessingError


@contextmanager
def extract_audio(video_path):
    with tempfile.TemporaryDirectory(prefix="caption-audio-") as directory:
        audio_path = Path(directory) / "audio.wav"
        command = [
            settings.FFMPEG_BINARY,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(audio_path),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=settings.CAPTION_FFMPEG_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise MediaProcessingError(
                "FFmpeg is unavailable. Install it to process video audio."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaProcessingError("Audio extraction timed out.") from exc
        except OSError as exc:
            raise MediaProcessingError("Audio extraction could not be started.") from exc

        if result.returncode != 0 or not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise MediaProcessingError("Audio could not be extracted from the video.")
        yield audio_path
