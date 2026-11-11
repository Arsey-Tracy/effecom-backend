from django.conf import settings
from rest_framework.authentication import CSRFCheck
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        authorization = self.get_header(request)
        if authorization is not None:
            return super().authenticate(request)

        raw_token = request.COOKIES.get(settings.JWT_ACCESS_COOKIE_NAME)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token.encode("utf-8"))
        self.enforce_csrf(request)
        return self.get_user(validated_token), validated_token

    @staticmethod
    def enforce_csrf(request):
        django_request = request._request
        check = CSRFCheck(lambda request: None)
        check.process_request(django_request)
        reason = check.process_view(django_request, None, (), {})
        if reason:
            raise PermissionDenied(f"CSRF Failed: {reason}")
