from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from translation.catalog import LANGUAGE_NAMES


class ToolOptionsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        languages = [
            {"code": code, "name": LANGUAGE_NAMES.get(code, code.upper())}
            for code in settings.SUNBIRD_TRANSLATION_LANGUAGES
        ]
        voices = [
            {"language": language, "name": name}
            for language, name in settings.SUNBIRD_TTS_VOICES
        ]
        return Response(
            {
                "languages": languages,
                "voices": voices,
                "max_text_length": settings.SUNBIRD_MAX_TEXT_LENGTH,
            }
        )
