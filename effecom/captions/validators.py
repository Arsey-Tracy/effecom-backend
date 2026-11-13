import math

from django.core.exceptions import ValidationError


def _finite_number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name} must be a finite number.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValidationError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValidationError(f"{field_name} must be a finite number.")
    return number


def _validate_time_range(item, *, duration, field_name, lower_bound=0):
    if not isinstance(item, dict):
        raise ValidationError(f"{field_name} must be an object.")
    try:
        start = _finite_number(item["start"], f"{field_name}.start")
        end = _finite_number(item["end"], f"{field_name}.end")
    except KeyError as exc:
        raise ValidationError(f"{field_name} must include start and end.") from exc

    if start < lower_bound:
        raise ValidationError(f"{field_name}.start is outside its allowed range.")
    if end <= start:
        raise ValidationError(f"{field_name}.end must be greater than start.")
    if end > duration:
        raise ValidationError(f"{field_name} must be within the video duration.")
    return start, end


def _validate_words(words, *, segment_start, segment_end, duration, field_name):
    if not isinstance(words, list):
        raise ValidationError(f"{field_name} must be a list.")

    previous_start = segment_start
    for index, word in enumerate(words):
        word_name = f"{field_name}[{index}]"
        start, end = _validate_time_range(
            word,
            duration=duration,
            field_name=word_name,
            lower_bound=segment_start,
        )
        if end > segment_end:
            raise ValidationError(f"{word_name} must be within its caption segment.")
        if start < previous_start:
            raise ValidationError(f"{field_name} must be chronological.")
        text = word.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError(f"{word_name}.text must not be empty.")
        previous_start = start


def validate_caption_segments(segments, duration):
    video_duration = _finite_number(duration, "duration")
    if video_duration <= 0:
        raise ValidationError("duration must be greater than zero.")
    if not isinstance(segments, list):
        raise ValidationError("segments must be a list.")

    seen_ids = set()
    previous_start = 0.0
    for index, segment in enumerate(segments):
        field_name = f"segments[{index}]"
        start, _ = _validate_time_range(
            segment,
            duration=video_duration,
            field_name=field_name,
        )

        segment_id = segment.get("id")
        if isinstance(segment_id, bool) or not isinstance(segment_id, (str, int)):
            raise ValidationError(f"{field_name}.id must be a string or integer.")
        if isinstance(segment_id, str) and not segment_id.strip():
            raise ValidationError(f"{field_name}.id must not be empty.")
        if segment_id in seen_ids:
            raise ValidationError("Segment ids must be unique.")
        seen_ids.add(segment_id)

        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError(f"{field_name}.text must not be empty.")
        if start < previous_start:
            raise ValidationError("segments must be chronological.")
        previous_start = start

        if "words" in segment:
            _validate_words(
                segment["words"],
                segment_start=start,
                segment_end=float(segment["end"]),
                duration=video_duration,
                field_name=f"{field_name}.words",
            )
