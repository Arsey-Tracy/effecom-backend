from django.conf import settings
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Activity
from .serializers import (
    AccountSerializer,
    ActivitySerializer,
    LoginSerializer,
    RegistrationSerializer,
)


def set_auth_cookies(response, refresh_token):
    access_lifetime = settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"]
    refresh_lifetime = settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"]
    cookie_options = {
        "secure": settings.JWT_COOKIE_SECURE,
        "httponly": True,
        "samesite": settings.JWT_COOKIE_SAMESITE,
    }
    response.set_cookie(
        settings.JWT_ACCESS_COOKIE_NAME,
        str(refresh_token.access_token),
        max_age=int(access_lifetime.total_seconds()),
        path=settings.JWT_ACCESS_COOKIE_PATH,
        **cookie_options,
    )
    response.set_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        str(refresh_token),
        max_age=int(refresh_lifetime.total_seconds()),
        path=settings.JWT_REFRESH_COOKIE_PATH,
        **cookie_options,
    )
    return response


def clear_auth_cookies(response):
    for name, path in (
        (settings.JWT_ACCESS_COOKIE_NAME, settings.JWT_ACCESS_COOKIE_PATH),
        (settings.JWT_REFRESH_COOKIE_NAME, settings.JWT_REFRESH_COOKIE_PATH),
    ):
        response.delete_cookie(
            name,
            path=path,
            samesite=settings.JWT_COOKIE_SAMESITE,
        )
    return response


@require_GET
@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({"csrfToken": get_token(request)})


class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(csrf_protect)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        serializer = RegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        response = Response(AccountSerializer(user).data, status=201)
        return set_auth_cookies(response, RefreshToken.for_user(user))


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(csrf_protect)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        serializer = LoginSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        response = Response(AccountSerializer(user).data)
        return set_auth_cookies(response, RefreshToken.for_user(user))


class RefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @method_decorator(csrf_protect)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if not refresh_token:
            return Response({"detail": "Refresh token is missing."}, status=401)

        serializer = TokenRefreshSerializer(data={"refresh": refresh_token})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError:
            return Response(
                {"detail": "Refresh token is invalid or expired."},
                status=401,
            )
        access_token = serializer.validated_data["access"]
        response = Response(status=204)
        response.set_cookie(
            settings.JWT_ACCESS_COOKIE_NAME,
            access_token,
            max_age=int(
                settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()
            ),
            path=settings.JWT_ACCESS_COOKIE_PATH,
            secure=settings.JWT_COOKIE_SECURE,
            httponly=True,
            samesite=settings.JWT_COOKIE_SAMESITE,
        )
        return response


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except TokenError:
                pass
        return clear_auth_cookies(Response(status=204))


class CurrentAccountView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(AccountSerializer(request.user).data)

    def patch(self, request):
        serializer = AccountSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ActivityListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        activities = Activity.objects.filter(user=request.user)[:20]
        return Response(ActivitySerializer(activities, many=True).data)
