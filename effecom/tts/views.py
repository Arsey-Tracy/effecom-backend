from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from effecom.sunbird import SunbirdError, post_task
from account.models import Activity
from .serializers import TextToSpeechRequestSerializer


class TextToSpeechView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = TextToSpeechRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payload = {
            **serializer.validated_data,
            "response_mode": "url",
        }
        try:
            result = post_task("/tasks/audio/speech", payload)
        except SunbirdError as exc:
            response = Response({"error": str(exc)}, status=exc.status_code)
            if exc.retry_after:
                response["Retry-After"] = exc.retry_after
            return response

        if request.user.is_authenticated:
            Activity.objects.create(
                user=request.user,
                tool=Activity.Tool.TTS,
                text=serializer.validated_data["text"],
                language=serializer.validated_data["language"],
                voice=serializer.validated_data["voice"],
                result=result,
            )

        return Response(result)
