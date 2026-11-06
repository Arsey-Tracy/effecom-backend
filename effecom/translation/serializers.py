from django.conf import settings
from rest_framework import serializers

from .models import Language, TranslationRequest


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


class LanguageDetectionRequestSerializer(serializers.Serializer):
    text = serializers.CharField(
        trim_whitespace=True, max_length=settings.SUNBIRD_MAX_TEXT_LENGTH
    )


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = (
            "code",
            "name",
            "supports_translation",
            "supports_stt",
        )
        read_only_fields = fields


class TranslationCreateSerializer(serializers.Serializer):
    text = serializers.CharField(
        max_length=settings.SUNBIRD_MAX_TRANSLATE_CHARS,
        trim_whitespace=True,
    )
    target_language = serializers.CharField(min_length=3, max_length=3)
    source_language = serializers.CharField(
        min_length=3,
        max_length=3,
        required=False,
        allow_blank=True,
    )

    def validate_source_language(self, value):
        return value.lower()

    def validate_target_language(self, value):
        return value.lower()

    def validate(self, attrs):
        source_language = attrs.get("source_language", "")
        target_language = attrs["target_language"]
        if source_language and source_language == target_language:
            raise serializers.ValidationError(
                {"target_language": "Choose a language different from the source."}
            )

        codes = [target_language]
        if source_language:
            codes.append(source_language)
        supported = set(
            Language.objects.filter(
                code__in=codes,
                supports_translation=True,
                is_active=True,
            ).values_list("code", flat=True)
        )
        unsupported = sorted(set(codes) - supported)
        if unsupported:
            raise serializers.ValidationError(
                {"language": f"Unsupported language code(s): {', '.join(unsupported)}."}
            )
        return attrs


class TranslationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TranslationRequest
        fields = (
            "id",
            "source_language",
            "detected_source_language",
            "target_language",
            "source_text",
            "translated_text",
            "status",
            "created_at",
        )
        read_only_fields = fields


class GuestUsageSerializer(serializers.Serializer):
    translations_used = serializers.IntegerField()
    translations_limit = serializers.IntegerField()
    transcriptions_used = serializers.IntegerField()
    transcriptions_limit = serializers.IntegerField()
    audio_seconds_used = serializers.IntegerField()
    audio_seconds_limit = serializers.IntegerField()
    expires_at = serializers.DateTimeField()
