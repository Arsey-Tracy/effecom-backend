from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import APIView

from effecom.sunbird import SunbirdError


class QuotaExceeded(exceptions.APIException):
    status_code = 429
    default_code = "guest_quota_exceeded"
    default_detail = "Trial limit reached. Sign up to continue."

    def __init__(self, *, api_code=None, detail=None):
        self.api_code = api_code or self.default_code
        super().__init__(detail or self.default_detail, code=self.api_code)


class V1APIView(APIView):
    def handle_exception(self, exc):
        if isinstance(exc, SunbirdError):
            response = Response(status=exc.status_code)
        else:
            response = super().handle_exception(exc)

        if isinstance(exc, QuotaExceeded):
            code = exc.api_code
            message = str(exc.detail)
            details = {}
        elif isinstance(exc, exceptions.ValidationError):
            code = "validation_error"
            message = "Request validation failed."
            details = response.data
        elif isinstance(exc, SunbirdError):
            code = exc.code or {
                504: "upstream_timeout",
                503: "upstream_auth_failed",
                422: "upstream_rejected",
            }.get(exc.status_code, "upstream_unavailable")
            message = str(exc)
            details = {}
        else:
            code = getattr(exc, "default_code", "request_failed")
            message = "The request could not be completed."
            details = response.data if response.status_code < 500 else {}

        response.data = {
            "error": {
                "code": code,
                "message": message,
                "details": details,
            }
        }
        if isinstance(exc, SunbirdError) and exc.retry_after:
            response["Retry-After"] = exc.retry_after
        return response
