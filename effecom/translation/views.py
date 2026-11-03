from django.conf import settings
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from effecom.sunbird import SunbirdError, post_task
from account.models import Activity
from .serializers import TranslationRequestSerializer


class TranslationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TranslationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = dict(serializer.validated_data)
        source_language = payload.get("source_language", "")
        if not source_language:
            payload.pop("source_language", None)

        try:
            result = post_task(
                "/tasks/translate",
                payload,
                timeout=(5, settings.SUNBIRD_TRANSLATION_TIMEOUT_SECONDS),
            )
        except SunbirdError as exc:
            return Response({"error": str(exc)}, status=exc.status_code)

        if request.user.is_authenticated:
            Activity.objects.create(
                user=request.user,
                tool=Activity.Tool.TRANSLATION,
                text=serializer.validated_data["text"],
                source_language=source_language,
                target_language=serializer.validated_data["target_language"],
                result=result,
            )

        return Response(result)
