from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .services.upload_tickets import consume_upload_ticket


class CaptionUploadTicketAuthentication(BaseAuthentication):
    def authenticate(self, request):
        authorization = request.headers.get("Authorization", "")
        parts = authorization.split()
        if len(parts) != 2 or parts[0].lower() != "captionupload":
            return None

        user = consume_upload_ticket(parts[1])
        if user is None:
            raise AuthenticationFailed("Upload ticket is invalid or expired.")
        return user, None

    def authenticate_header(self, request):
        return "CaptionUpload"
