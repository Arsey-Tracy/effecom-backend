from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from .models import GuestSession


GUEST_TOKEN_COOKIE = "guest_token"
GUEST_TOKEN_SALT = "translation.guest-session"


class GuestAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.COOKIES.get(GUEST_TOKEN_COOKIE) or request.headers.get(
            "X-Guest-Token"
        )
        if not token:
            return None

        try:
            session_id = TimestampSigner(salt=GUEST_TOKEN_SALT).unsign(
                token,
                max_age=settings.GUEST_SESSION_LIFETIME_SECONDS,
            )
        except (BadSignature, SignatureExpired):
            return None

        try:
            guest_session = GuestSession.objects.get(
                pk=session_id,
                expires_at__gt=timezone.now(),
            )
        except (
            GuestSession.DoesNotExist,
            DjangoValidationError,
            ValueError,
        ):
            return None

        return AnonymousUser(), guest_session

    def authenticate_header(self, request):
        return "Guest"
