import math

from django.core.exceptions import ValidationError


def _timestamp(milliseconds, decimal_separator):
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return (
        f"{hours:02}:{minutes:02}:{whole_seconds:02}"
        f"{decimal_separator}{milliseconds:03}"
    )


def _timestamp_milliseconds(seconds):
    try:
        value = float(seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValidationError(
            "Caption timestamps must be finite and non-negative."
        ) from exc
    if not math.isfinite(value) or value < 0:
        raise ValidationError("Caption timestamps must be finite and non-negative.")
    try:
        return math.floor(value * 1000 + 0.5)
    except OverflowError as exc:
        raise ValidationError(
            "Caption timestamps must be finite and non-negative."
        ) from exc


def _caption_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("Caption text must not be empty.")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


def render_srt(segments):
    cues = []
    for index, segment in enumerate(segments, start=1):
        text = _caption_text(segment["text"])
        start_ms = _timestamp_milliseconds(segment["start"])
        end_ms = max(_timestamp_milliseconds(segment["end"]), start_ms + 1)
        start = _timestamp(start_ms, ",")
        end = _timestamp(end_ms, ",")
        cues.append(f"{index}\n{start} --> {end}\n{text}")
    return "\n\n".join(cues) + "\n" if cues else ""


def render_vtt(segments):
    cues = []
    for index, segment in enumerate(segments, start=1):
        text = _caption_text(segment["text"])
        start_ms = _timestamp_milliseconds(segment["start"])
        end_ms = max(_timestamp_milliseconds(segment["end"]), start_ms + 1)
        start = _timestamp(start_ms, ".")
        end = _timestamp(end_ms, ".")
        cues.append(f"{index}\n{start} --> {end}\n{text}")
    return "WEBVTT\n\n" + "\n\n".join(cues) + "\n" if cues else "WEBVTT\n"


def export_track(track, file_format):
    if file_format == "srt":
        return render_srt(track.segments)
    if file_format == "vtt":
        return render_vtt(track.segments)
    raise ValueError("Subtitle format must be 'srt' or 'vtt'.")
