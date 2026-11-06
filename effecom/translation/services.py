from datetime import timedelta
from time import perf_counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from account.models import Activity
from effecom.sunbird import SunbirdError, post_task

from .api import QuotaExceeded
from .models import GuestSession, TranslationRequest


def detect_language(text, *, timeout=None):
    return post_task(
        "/tasks/language_id",
        {"text": text},
        timeout=timeout
        or (
            settings.SUNBIRD_CONNECT_TIMEOUT_SECONDS,
            settings.SUNBIRD_TRANSLATION_TIMEOUT_SECONDS,
        ),
    )


def _reserve_translation(owner, text, source_language, target_language):
    now = timezone.now()
    request_fields = {
        "source_language": source_language,
        "target_language": target_language,
        "source_text": text,
    }

    with transaction.atomic():
        if getattr(owner, "is_authenticated", False):
            user_model = get_user_model()
            user_model.objects.select_for_update().get(pk=owner.pk)
            if len(text) > settings.AUTHENTICATED_LIMITS["translate_chars"]:
                raise QuotaExceeded(
                    api_code="translation_text_limit",
                    detail="Text exceeds the per-request character limit.",
                )
            window_start = now - timedelta(days=1)
            used = TranslationRequest.objects.filter(
                user_id=owner.pk,
                created_at__gte=window_start,
                status__in=(
                    TranslationRequest.Status.PENDING,
                    TranslationRequest.Status.COMPLETED,
                ),
            ).count()
            if used >= settings.AUTHENTICATED_LIMITS["translations_per_day"]:
                raise QuotaExceeded(
                    api_code="daily_quota_exceeded",
                    detail="Daily translation limit reached.",
                )
            return TranslationRequest.objects.create(
                user=owner,
                **request_fields,
            ), None

        guest = GuestSession.objects.select_for_update().get(pk=owner.pk)
        if guest.expires_at <= now:
            raise QuotaExceeded(
                api_code="guest_session_expired",
                detail="Guest session expired. Start a new trial session.",
            )
        if len(text) > settings.GUEST_LIMITS["translate_chars"]:
            raise QuotaExceeded(
                api_code="translation_text_limit",
                detail="Text exceeds the per-request character limit.",
            )
        if guest.translations_used >= settings.GUEST_LIMITS["translations"]:
            raise QuotaExceeded()
        guest.translations_used += 1
        guest.characters_used += len(text)
        guest.save(update_fields=("translations_used", "characters_used"))
        row = TranslationRequest.objects.create(
            guest_session=guest,
            **request_fields,
        )
        return row, guest.pk


def _mark_failed(row, guest_id, error_code):
    with transaction.atomic():
        row.status = TranslationRequest.Status.FAILED
        row.error_code = error_code
        row.save(update_fields=("status", "error_code"))
        if guest_id is not None:
            guest = GuestSession.objects.select_for_update().get(pk=guest_id)
            guest.translations_used = max(0, guest.translations_used - 1)
            guest.characters_used = max(
                0,
                guest.characters_used - len(row.source_text),
            )
            guest.save(update_fields=("translations_used", "characters_used"))


def translate(owner, validated_data, *, timeout=None):
    text = validated_data["text"]
    source_language = validated_data.get("source_language", "")
    target_language = validated_data["target_language"]
    row, guest_id = _reserve_translation(
        owner,
        text,
        source_language,
        target_language,
    )
    payload = {
        "text": text,
        "target_language": target_language,
    }
    if source_language:
        payload["source_language"] = source_language

    started_at = perf_counter()
    try:
        result = post_task(
            "/tasks/translate",
            payload,
            timeout=timeout
            or (
                settings.SUNBIRD_CONNECT_TIMEOUT_SECONDS,
                settings.SUNBIRD_TRANSLATION_TIMEOUT_SECONDS,
            ),
        )
    except SunbirdError as exc:
        _mark_failed(row, guest_id, f"upstream_{exc.status_code}")
        raise

    elapsed_ms = max(0, int((perf_counter() - started_at) * 1000))
    output = result.get("output")
    output = output if isinstance(output, dict) else {}
    translated_text = output.get("translated_text", result.get("translation", ""))
    if not isinstance(translated_text, str):
        translated_text = ""
    detected_source = output.get("source_language", "")
    if not isinstance(detected_source, str):
        detected_source = ""

    row.translated_text = translated_text
    row.detected_source_language = detected_source.lower()
    row.sunbird_job_id = str(result.get("id", ""))[:100]
    row.latency_ms = elapsed_ms
    row.provider_response = result
    row.status = TranslationRequest.Status.COMPLETED
    row.save(
        update_fields=(
            "translated_text",
            "detected_source_language",
            "sunbird_job_id",
            "latency_ms",
            "provider_response",
            "status",
        )
    )

    if getattr(owner, "is_authenticated", False):
        Activity.objects.create(
            user=owner,
            tool=Activity.Tool.TRANSLATION,
            text=text,
            source_language=source_language,
            target_language=target_language,
            result=result,
        )
    return row
