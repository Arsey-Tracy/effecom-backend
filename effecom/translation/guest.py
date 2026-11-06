import hashlib
import hmac
from datetime import timedelta

from django.conf import settings
from django.core.signing import TimestampSigner
from django.db import transaction
from django.utils import timezone

from .authentication import GUEST_TOKEN_SALT
from .models import GuestSession


class GuestSessionLimitExceeded(Exception):
    pass


def _hash(value):
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def issue_guest_session(request):
    ip_address = request.META.get("REMOTE_ADDR", "")
    ip_hash = _hash(ip_address)
    user_agent_hash = _hash(request.META.get("HTTP_USER_AGENT", "")) if (
        request.META.get("HTTP_USER_AGENT")
    ) else ""
    now = timezone.now()
    expires_at = now + timedelta(seconds=settings.GUEST_SESSION_LIFETIME_SECONDS)

    with transaction.atomic():
        sessions_created_today = GuestSession.objects.filter(
            ip_hash=ip_hash,
            created_at__gte=now - timedelta(days=1),
        ).count()
        if sessions_created_today >= settings.GUEST_SESSIONS_PER_IP_PER_DAY:
            raise GuestSessionLimitExceeded

        guest_session = GuestSession.objects.create(
            ip_hash=ip_hash,
            user_agent_hash=user_agent_hash,
            expires_at=expires_at,
        )

    token = TimestampSigner(salt=GUEST_TOKEN_SALT).sign(str(guest_session.pk))
    return guest_session, token


def set_guest_cookie(response, token):
    response.set_cookie(
        "guest_token",
        token,
        max_age=settings.GUEST_SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=settings.GUEST_COOKIE_SECURE,
        samesite=settings.GUEST_COOKIE_SAMESITE,
        path="/api/v1/",
    )
    return response
