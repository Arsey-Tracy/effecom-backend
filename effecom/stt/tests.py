from io import BytesIO
from unittest.mock import Mock, patch
import wave

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from account.models import Activity
from effecom.sunbird import clear_auth_cache
from translation.models import GuestSession


@override_settings(
    SUNBIRD_ACCESS_TOKEN="test-token",
    SUNBIRD_USERNAME="",
    SUNBIRD_PASSWORD="",
    SUNBIRD_STT_LANGUAGES=("lug",),
)
class SpeechToTextApiTests(APITestCase):
    def setUp(self):
        clear_auth_cache()

    def audio_upload(self, *, seconds=1, name="sample.wav"):
        output = BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 16000 * seconds)
        return SimpleUploadedFile(
            name,
            output.getvalue(),
            content_type="audio/wav",
        )

    def create_guest_session(self):
        response = self.client.post(
            "/api/v1/guest/session/",
            {},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    @staticmethod
    def provider_response(transcription="Oli otya?"):
        return Mock(
            ok=True,
            json=Mock(return_value={"audio_transcription": transcription}),
        )

    def post_data(self, upload=None, language="lug"):
        return {
            "audio": upload or self.audio_upload(),
            "language": language,
        }

    def test_guest_transcription_forwards_multipart_audio_and_tracks_usage(self):
        self.create_guest_session()
        with patch(
            "effecom.sunbird.requests.post",
            return_value=self.provider_response(),
        ) as post:
            response = self.client.post(
                "/api/v1/stt/",
                self.post_data(),
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["audio_transcription"], "Oli otya?")
        self.assertEqual(
            post.call_args.args[0],
            "https://api.sunbird.ai/tasks/audio/transcriptions",
        )
        self.assertEqual(post.call_args.kwargs["data"], {"language": "lug"})
        self.assertEqual(
            post.call_args.kwargs["files"]["audio"][0],
            "recording.wav",
        )
        self.assertEqual(
            post.call_args.kwargs["files"]["audio"][2],
            "audio/wav",
        )
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 180))
        guest = GuestSession.objects.get()
        self.assertEqual(guest.transcriptions_used, 1)
        self.assertEqual(guest.audio_seconds_used, 1)

    @override_settings(
        GUEST_LIMITS={
            "transcriptions": 1,
            "audio_seconds": 30,
        }
    )
    def test_guest_transcription_limit_prevents_another_provider_request(self):
        self.create_guest_session()
        with patch(
            "effecom.sunbird.requests.post",
            return_value=self.provider_response(),
        ) as post:
            first = self.client.post(
                "/api/v1/stt/",
                self.post_data(),
                format="multipart",
            )
            second = self.client.post(
                "/api/v1/stt/",
                self.post_data(),
                format="multipart",
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(
            second.data["error"]["code"],
            "transcription_quota_exceeded",
        )
        post.assert_called_once()

    def test_failed_provider_request_releases_guest_quota(self):
        self.create_guest_session()
        failed_response = Mock(
            ok=False,
            status_code=500,
            json=Mock(return_value={"detail": "private provider detail"}),
        )
        with patch(
            "effecom.sunbird.requests.post",
            return_value=failed_response,
        ):
            response = self.client.post(
                "/api/v1/stt/",
                self.post_data(),
                format="multipart",
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(GuestSession.objects.get().transcriptions_used, 0)
        self.assertEqual(GuestSession.objects.get().audio_seconds_used, 0)

    def test_transcription_requires_a_guest_session(self):
        with patch("effecom.sunbird.requests.post") as post:
            response = self.client.post(
                "/api/v1/stt/",
                self.post_data(),
                format="multipart",
            )

        self.assertEqual(response.status_code, 401)
        post.assert_not_called()

    def test_invalid_audio_and_unconfigured_language_are_rejected(self):
        self.create_guest_session()
        with patch("effecom.sunbird.requests.post") as post:
            invalid_audio = self.client.post(
                "/api/v1/stt/",
                self.post_data(
                    SimpleUploadedFile(
                        "not-audio.wav",
                        b"not an audio recording",
                        content_type="audio/wav",
                    )
                ),
                format="multipart",
            )
            unsupported_language = self.client.post(
                "/api/v1/stt/",
                self.post_data(language="eng"),
                format="multipart",
            )

        self.assertEqual(invalid_audio.status_code, 400)
        self.assertEqual(unsupported_language.status_code, 400)
        post.assert_not_called()

    def test_audio_duration_limit_is_enforced(self):
        self.create_guest_session()
        with override_settings(SUNBIRD_MAX_AUDIO_SECONDS=1):
            with patch("effecom.sunbird.requests.post") as post:
                response = self.client.post(
                    "/api/v1/stt/",
                    self.post_data(self.audio_upload(seconds=2)),
                    format="multipart",
                )

        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    def test_signed_in_transcription_is_saved_to_activity_history(self):
        user = get_user_model().objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="test-password",
        )
        self.client.force_authenticate(user)
        with patch(
            "effecom.sunbird.requests.post",
            return_value=self.provider_response("Transcribed words"),
        ):
            response = self.client.post(
                "/api/v1/stt/",
                self.post_data(),
                format="multipart",
            )

        self.assertEqual(response.status_code, 200)
        activity = Activity.objects.get(user=user)
        self.assertEqual(activity.tool, Activity.Tool.STT)
        self.assertEqual(activity.text, "Transcribed words")
        self.assertEqual(activity.language, "lug")
