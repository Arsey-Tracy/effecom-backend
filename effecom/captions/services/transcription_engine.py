import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable

from .errors import TranscriptionError, TranscriptionModelError


@dataclass(frozen=True)
class WhisperOptions:
    model_size: str
    device: str
    compute_type: str
    language: str
    beam_size: int
    vad_filter: bool
    word_timestamps: bool


@dataclass(frozen=True)
class TranscriptionResult:
    language: str | None
    segments: list[dict]


@lru_cache(maxsize=1)
def _load_model(model_size, device, compute_type):
    try:
        from faster_whisper import WhisperModel

        return WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
        )
    except Exception as exc:
        raise TranscriptionModelError(
            "The transcription model could not be loaded."
        ) from exc


def _finite_timestamp(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        timestamp = float(value)
    except OverflowError:
        return None
    return timestamp if math.isfinite(timestamp) else None


def _word_segments(words, start, end):
    result = []
    for word in words or ():
        word_start = _finite_timestamp(getattr(word, "start", None))
        word_end = _finite_timestamp(getattr(word, "end", None))
        text = getattr(word, "word", "")
        if (
            word_start is None
            or word_end is None
            or word_end <= word_start
            or not isinstance(text, str)
            or not text.strip()
        ):
            continue
        word_start = max(start, word_start)
        word_end = min(end, word_end)
        if word_end > word_start:
            result.append(
                {
                    "start": word_start,
                    "end": word_end,
                    "text": text.strip(),
                }
            )
    return result


def transcribe_audio(
    audio_path,
    *,
    duration_seconds,
    options,
    progress_callback: Callable[[int], None] | None = None,
):
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("duration_seconds must be finite and greater than zero.")

    model = _load_model(options.model_size, options.device, options.compute_type)
    language = (
        None if options.language.strip().lower() == "auto" else options.language
    )
    try:
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=options.beam_size,
            vad_filter=options.vad_filter,
            word_timestamps=options.word_timestamps,
        )
    except Exception as exc:
        raise TranscriptionError("The audio could not be transcribed.") from exc

    transcript_segments = []
    try:
        for segment in segments:
            raw_end = _finite_timestamp(getattr(segment, "end", None))
            if raw_end is not None and progress_callback is not None:
                progress = min(99, max(0, int(raw_end / duration_seconds * 100)))
                progress_callback(progress)

            start = _finite_timestamp(getattr(segment, "start", None))
            end = raw_end
            if start is None or end is None or end <= start:
                continue
            start = max(start, 0.0)
            end = min(end, duration_seconds)
            text = getattr(segment, "text", "")
            if end <= start or not isinstance(text, str) or not text.strip():
                continue

            caption = {
                "id": str(len(transcript_segments) + 1),
                "start": start,
                "end": end,
                "text": text.strip(),
            }
            if options.word_timestamps:
                caption["words"] = _word_segments(
                    getattr(segment, "words", None),
                    start,
                    end,
                )
            transcript_segments.append(caption)
    except Exception as exc:
        raise TranscriptionError("The audio transcription could not be completed.") from exc

    detected_language = getattr(info, "language", None)
    if not isinstance(detected_language, str) or not detected_language.strip():
        detected_language = None
    return TranscriptionResult(detected_language, transcript_segments)
