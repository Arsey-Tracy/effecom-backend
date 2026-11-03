from django.conf import settings
from rest_framework import serializers


class TranslationRequestSerializer(serializers.Serializer):
    text = serializers.CharField(
        trim_whitespace=True, max_length=settings.SUNBIRD_MAX_TEXT_LENGTH
    )
    source_language = serializers.CharField(
        trim_whitespace=True, max_length=16, required=False, allow_blank=True
    )
    target_language = serializers.CharField(
        trim_whitespace=True, max_length=16
    )

    def validate_source_language(self, value):
        return value.lower()

    def validate_target_language(self, value):
        return value.lower()

    def validate(self, attrs):
        languages = [
            language
            for language in (
                attrs.get("source_language", ""),
                attrs["target_language"],
            )
            if language
        ]
        unsupported_languages = [
            language
            for language in languages
            if language not in settings.SUNBIRD_TRANSLATION_LANGUAGES
        ]
        if unsupported_languages:
            raise serializers.ValidationError(
                {
                    "language": (
                        f"Unsupported language code(s): "
                        f"{', '.join(unsupported_languages)}."
                    ),
                }
            )
        if (
            attrs.get("source_language")
            and attrs["source_language"] == attrs["target_language"]
        ):
            raise serializers.ValidationError(
                {
                    "target_language": (
                        "Choose a language different from the source."
                    )
                }
            )
        return attrs
