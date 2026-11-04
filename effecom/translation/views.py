from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from effecom.sunbird import SunbirdError
from .api import QuotaExceeded
from .guest import GuestSessionLimitExceeded, issue_guest_session, set_guest_cookie
from .models import GuestSession
from .services import translate
from .serializers import TranslationRequestSerializer


class TranslationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TranslationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        guest_session = request.auth
        cookie_token = None
        if not request.user.is_authenticated and not isinstance(
            guest_session, GuestSession
        ):
            try:
                guest_session, cookie_token = issue_guest_session(request)
            except GuestSessionLimitExceeded:
                return Response(
                    {"error": "Guest session limit reached for this network."},
                    status=429,
                )

        owner = request.user if request.user.is_authenticated else guest_session

        try:
            translation = translate(
                owner,
                serializer.validated_data,
                timeout=(5, settings.SUNBIRD_TRANSLATION_TIMEOUT_SECONDS),
            )
        except QuotaExceeded as exc:
            response = Response({"error": str(exc.detail)}, status=exc.status_code)
            if cookie_token:
                set_guest_cookie(response, cookie_token)
            return response
        except SunbirdError as exc:
            response = Response({"error": str(exc)}, status=exc.status_code)
            if exc.retry_after:
                response["Retry-After"] = exc.retry_after
            if cookie_token:
                set_guest_cookie(response, cookie_token)
            return response

        response = Response(translation.provider_response)
        if cookie_token:
            set_guest_cookie(response, cookie_token)
        return response
