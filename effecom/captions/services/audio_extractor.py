import logging
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import av
from django.conf import settings

from .errors import MediaProcessingError


logger = logging.getLogger(__name__)


def _decode_audio(video_path, audio_path):
    deadline = time.monotonic() + settings.CAPTION_FFMPEG_TIMEOUT_SECONDS
    try:
        container = av.open(str(video_path))
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise MediaProcessingError(
            "Audio could not be extracted from the video."
        ) from exc

    try:
        audio_stream = next(
            (stream for stream in container.streams if stream.type == "audio"),
            None,
        )
        if audio_stream is None:
            raise MediaProcessingError("The video does not contain an audio stream.")

        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        output = av.open(str(audio_path), "w")
        try:
            output_stream = output.add_stream("pcm_s16le", rate=16000)
            output_stream.layout = "mono"
            for frame in container.decode(audio_stream):
                if time.monotonic() > deadline:
                    raise MediaProcessingError("Audio extraction timed out.")
                for resampled in resampler.resample(frame):
                    for packet in output_stream.encode(resampled):
                        output.mux(packet)
            for packet in output_stream.encode(None):
                output.mux(packet)
        finally:
            output.close()
    except MediaProcessingError:
        raise
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise MediaProcessingError(
            "Audio could not be extracted from the video."
        ) from exc
    finally:
        container.close()

    if not audio_path.is_file() or audio_path.stat().st_size == 0:
        raise MediaProcessingError("Audio could not be extracted from the video.")


@contextmanager
def extract_audio(video_path):
    with tempfile.TemporaryDirectory(prefix="caption-audio-") as directory:
        audio_path = Path(directory) / "audio.wav"
        _decode_audio(video_path, audio_path)
        yield audio_path