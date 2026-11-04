from datetime import timedelta

from django.conf import settings
from django.core.signing import TimestampSigner
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import exceptions
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .api import QuotaExceeded, V1APIView
from .authentication import GUEST_TOKEN_SALT
from .guest import GuestSessionLimitExceeded, issue_guest_session, set_guest_cookie
from .models import GuestSession, Language, TranslationRequest
from .permissions import GuestBurstThrottle, IsUserOrGuest
from .serializers import (
    GuestUsageSerializer,
    LanguageSerializer,
    TranslationCreateSerializer,
    TranslationSerializer,
)
from .services import translate


class TranslationPagination(PageNumberPagination):
    page_size = 20


@method_decorator(cache_page(300), name="dispatch")
class LanguageListView(V1APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        capability = request.query_params.get("capability")
        if capability not in (None, "translation", "stt"):
            raise exceptions.ValidationError(
                {"capability": "Choose 'translation' or 'stt'."}
            )
        languages = Language.objects.filter(is_active=True)
        if capability == "translation":
            languages = languages.filter(supports_translation=True)
        elif capability == "stt":
            languages = languages.filter(supports_stt=True)
        return Response(LanguageSerializer(languages, many=True).data)


class GuestSessionView(V1APIView):
    throttle_classes = [GuestBurstThrottle]

    def post(self, request):
        guest_session = request.auth
        if isinstance(guest_session, GuestSession):
            guest_session.expires_at = timezone.now() + timedelta(
                seconds=settings.GUEST_SESSION_LIFETIME_SECONDS
            )
            guest_session.save(update_fields=("expires_at",))
            token = TimestampSigner(salt=GUEST_TOKEN_SALT).sign(
                str(guest_session.pk)
            )
        else:
            try:
                guest_session, token = issue_guest_session(request)
            except GuestSessionLimitExceeded as exc:
                raise QuotaExceeded(
                    api_code="guest_session_limit",
                    detail="Guest session limit reached for this network.",
                ) from exc

        response = Response(
            {
                "id": guest_session.pk,
                "expires_at": guest_session.expires_at,
            },
            status=201,
        )
        return set_guest_cookie(response, token)


class GuestUsageView(V1APIView):
    permission_classes = [IsUserOrGuest]

    def get(self, request):
        if request.user.is_authenticated:
            raise exceptions.PermissionDenied(
                "Usage is available for guest sessions only."
            )
        guest_session = request.auth
        data = {
            "translations_used": guest_session.translations_used,
            "translations_limit": settings.GUEST_LIMITS["translations"],
            "transcriptions_used": guest_session.transcriptions_used,
            "transcriptions_limit": settings.GUEST_LIMITS["transcriptions"],
            "audio_seconds_used": guest_session.audio_seconds_used,
            "audio_seconds_limit": settings.GUEST_LIMITS["audio_seconds"],
            "expires_at": guest_session.expires_at,
        }
        return Response(GuestUsageSerializer(data).data)


class TranslationListCreateView(V1APIView):
    throttle_classes = [GuestBurstThrottle]

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request):
        records = TranslationRequest.objects.filter(user=request.user)
        paginator = TranslationPagination()
        page = paginator.paginate_queryset(records, request, view=self)
        serializer = TranslationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        serializer = TranslationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        guest_session = request.auth
        if not request.user.is_authenticated and not isinstance(
            guest_session, GuestSession
        ):
            raise exceptions.NotAuthenticated(
                "Create a guest session before translating."
            )

        owner = request.user if request.user.is_authenticated else guest_session
        translation = translate(owner, serializer.validated_data)
        return Response(TranslationSerializer(translation).data, status=201)


class TranslationDetailView(V1APIView):
    permission_classes = [IsUserOrGuest]

    def get(self, request, pk):
        records = TranslationRequest.objects.filter(pk=pk)
        if request.user.is_authenticated:
            records = records.filter(user=request.user)
        else:
            records = records.filter(guest_session=request.auth)
        translation = records.first()
        if translation is None:
            raise exceptions.NotFound("Translation not found.")
        return Response(TranslationSerializer(translation).data)
