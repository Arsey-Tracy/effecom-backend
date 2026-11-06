import math
import struct
import wave

from django.conf import settings
from rest_framework import serializers


def get_audio_duration(uploaded_file):
    try:
        with wave.open(uploaded_file, "rb") as audio:
            frame_count = audio.getnframes()
            sample_rate = audio.getframerate()
    except (wave.Error, OSError, EOFError, struct.error) as exc:
        raise serializers.ValidationError(
            "Upload a valid WAV audio file."
        ) from exc
    finally:
        uploaded_file.seek(0)

    if not sample_rate or not frame_count:
        raise serializers.ValidationError("The audio recording must not be empty.")
    duration = frame_count / sample_rate
    if not math.isfinite(duration):
        raise serializers.ValidationError("The audio duration could not be read.")
    return duration


class SpeechToTextRequestSerializer(serializers.Serializer):
    audio = serializers.FileField()
    language = serializers.CharField(trim_whitespace=True, max_length=16)

    def validate_language(self, value):
        language = value.lower()
        if language not in settings.SUNBIRD_STT_LANGUAGES:
            raise serializers.ValidationError(
                "This language is not configured for speech-to-text."
            )
        return language

    def validate(self, attrs):
        audio = attrs["audio"]
        if audio.size > settings.SUNBIRD_MAX_AUDIO_SIZE_BYTES:
            raise serializers.ValidationError(
                {
                    "audio": (
                        "The audio file exceeds the maximum size of "
                        f"{settings.SUNBIRD_MAX_AUDIO_SIZE_BYTES} bytes."
                    )
                }
            )

        duration = get_audio_duration(audio)
        if duration > settings.SUNBIRD_MAX_AUDIO_SECONDS:
            raise serializers.ValidationError(
                {
                    "audio": (
                        "The audio exceeds the maximum duration of "
                        f"{settings.SUNBIRD_MAX_AUDIO_SECONDS} seconds."
                    )
                }
            )

        attrs["audio_seconds"] = max(1, math.ceil(duration))
        return attrs
