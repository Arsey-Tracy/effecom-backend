from django.conf import settings
from rest_framework import serializers


class TextToSpeechRequestSerializer(serializers.Serializer):
    text = serializers.CharField(
        trim_whitespace=True, max_length=settings.SUNBIRD_MAX_TEXT_LENGTH
    )
    language = serializers.CharField(
        trim_whitespace=True, max_length=16
    )
    voice = serializers.CharField(
        trim_whitespace=True, max_length=64
    )

    def validate_language(self, value):
        return value.lower()

    def validate(self, attrs):
        voice_pair = (attrs["language"], attrs["voice"])
        if voice_pair not in settings.SUNBIRD_TTS_VOICES:
            raise serializers.ValidationError(
                {
                    "voice": (
                        "This voice and language combination is not "
                        "configured."
                    )
                }
            )
        return attrs
