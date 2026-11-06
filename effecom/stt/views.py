from rest_framework import exceptions
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from translation.api import V1APIView
from translation.models import GuestSession
from translation.permissions import GuestBurstThrottle

from .serializers import SpeechToTextRequestSerializer
from .services import transcribe


class SpeechToTextView(V1APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [AllowAny]
    throttle_classes = [GuestBurstThrottle]

    def get_authenticate_header(self, request):
        return "Guest"

    def post(self, request):
        owner = request.user
        if not owner.is_authenticated:
            owner = request.auth
            if not isinstance(owner, GuestSession):
                raise exceptions.NotAuthenticated()

        serializer = SpeechToTextRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(transcribe(owner, serializer.validated_data))
