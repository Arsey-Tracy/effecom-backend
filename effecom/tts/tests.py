from io import StringIO
from unittest.mock import Mock, patch

from django.core.management import call_command, CommandError
from django.test import override_settings
import requests
from rest_framework.test import APITestCase

from effecom.sunbird import clear_auth_cache


@override_settings(
    SUNBIRD_ACCESS_TOKEN="test-token",
    SUNBIRD_USERNAME="",
    SUNBIRD_PASSWORD="",
)
class TextToSpeechApiTests(APITestCase):
    def setUp(self):
        clear_auth_cache()

    @patch("effecom.sunbird.requests.post")
    def test_tts_returns_sunbird_audio_response(self, post):
        result = {"audio_url": "https://audio.example/result.mp3"}
        post.return_value = Mock(ok=True, json=Mock(return_value=result))

        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, result)
        post.assert_called_once()
        self.assertEqual(
            post.call_args.args[0],
            "https://api.sunbird.ai/tasks/audio/speech",
        )
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "text": "Oli otya?",
                "language": "lug",
                "voice": "Namuli",
                "response_mode": "url",
            },
        )

    @patch("effecom.sunbird.requests.post")
    def test_unconfigured_voice_is_rejected(self, post):
        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Hello", "language": "eng", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    @override_settings(SUNBIRD_ACCESS_TOKEN="")
    @patch("effecom.sunbird.requests.post")
    def test_missing_provider_token_returns_service_unavailable(self, post):
        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {
                "error": (
                    "Sunbird is not configured. Set SUNBIRD_USERNAME and "
                    "SUNBIRD_PASSWORD or SUNBIRD_ACCESS_TOKEN."
                )
            },
        )
        post.assert_not_called()

    @patch("effecom.sunbird.requests.post")
    def test_upstream_error_does_not_expose_provider_response(self, post):
        post.return_value = Mock(
            ok=False,
            status_code=500,
            json=Mock(return_value={"detail": "private provider detail"}),
        )

        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.data,
            {"error": "Sunbird could not complete this request."},
        )

    @patch("effecom.sunbird.sleep")
    @patch("effecom.sunbird.requests.post")
    def test_transient_upstream_error_is_retried(self, post, sleep):
        result = {"audio_url": "https://audio.example/result.mp3"}
        post.side_effect = [
            Mock(ok=False, status_code=503),
            Mock(ok=True, json=Mock(return_value=result)),
        ]

        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(0.25)

    @patch("effecom.sunbird.requests.post")
    def test_upstream_rate_limit_is_safe_and_preserves_retry_after(self, post):
        post.return_value = Mock(
            ok=False,
            status_code=429,
            headers={"Retry-After": "30"},
        )

        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], "30")
        self.assertEqual(
            response.data,
            {"error": "Sunbird is busy. Please retry shortly."},
        )

    @patch("effecom.sunbird.requests.post")
    def test_upstream_auth_error_is_actionable_without_exposing_details(self, post):
        post.return_value = Mock(
            ok=False,
            status_code=401,
            json=Mock(return_value={"detail": "private token detail"}),
        )

        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"error": "Sunbird rejected the configured access token."},
        )

    @patch(
        "effecom.sunbird.requests.post",
        side_effect=requests.Timeout,
    )
    def test_sunbird_timeout_returns_gateway_timeout(self, post):
        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.data, {"error": "Sunbird request timed out."})
        post.assert_called_once()

    @override_settings(
        SUNBIRD_ACCESS_TOKEN="",
        SUNBIRD_USERNAME="service@example.test",
        SUNBIRD_PASSWORD="test-password",
    )
    @patch("effecom.sunbird.requests.post")
    def test_login_credentials_are_exchanged_for_a_cached_token(self, post):
        result = {"audio_url": "https://audio.example/result.mp3"}
        post.side_effect = [
            Mock(
                ok=True,
                json=Mock(
                    return_value={
                        "access_token": "issued-token",
                        "token_type": "bearer",
                    }
                ),
            ),
            Mock(ok=True, json=Mock(return_value=result)),
        ]

        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, result)
        self.assertEqual(post.call_count, 2)
        login_call, speech_call = post.call_args_list
        self.assertEqual(
            login_call.args[0],
            "https://api.sunbird.ai/auth/token",
        )
        self.assertEqual(
            login_call.kwargs["data"],
            {
                "username": "service@example.test",
                "password": "test-password",
            },
        )
        self.assertNotIn(
            "password",
            speech_call.kwargs["headers"]["Authorization"],
        )
        authorization = speech_call.kwargs["headers"]["Authorization"]
        self.assertTrue(authorization.lower().startswith("bearer "))
        self.assertTrue(authorization.endswith("issued-token"))

    @override_settings(
        SUNBIRD_ACCESS_TOKEN="old-token",
        SUNBIRD_USERNAME="service@example.test",
        SUNBIRD_PASSWORD="test-password",
    )
    @patch("effecom.sunbird.requests.post")
    def test_unauthorized_token_triggers_one_login_and_retries_once(self, post):
        result = {"audio_url": "https://audio.example/result.mp3"}
        post.side_effect = [
            Mock(ok=False, status_code=401),
            Mock(
                ok=True,
                json=Mock(
                    return_value={
                        "access_token": "replacement-token",
                        "token_type": "bearer",
                    }
                ),
            ),
            Mock(ok=True, json=Mock(return_value=result)),
        ]

        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, result)
        self.assertEqual(post.call_count, 3)
        initial_authorization = post.call_args_list[0].kwargs["headers"]["Authorization"]
        retry_authorization = post.call_args_list[2].kwargs["headers"]["Authorization"]
        self.assertTrue(initial_authorization.lower().startswith("bearer "))
        self.assertTrue(retry_authorization.lower().startswith("bearer "))
        self.assertTrue(retry_authorization.endswith("replacement-token"))
        self.assertNotEqual(initial_authorization, retry_authorization)

    @override_settings(
        SUNBIRD_ACCESS_TOKEN="",
        SUNBIRD_USERNAME="service@example.test",
        SUNBIRD_PASSWORD="wrong-password",
    )
    @patch("effecom.sunbird.requests.post")
    def test_invalid_login_credentials_return_safe_error(self, post):
        post.return_value = Mock(
            ok=False,
            status_code=401,
            text="private authentication response",
        )

        response = self.client.post(
            "/api/v1/tts/",
            {"text": "Oli otya?", "language": "lug", "voice": "Namuli"},
            format="json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.data,
            {"error": "Sunbird rejected the configured login credentials."},
        )
        post.assert_called_once()


@override_settings(SUNBIRD_USERNAME="", SUNBIRD_PASSWORD="")
class CheckSunbirdCommandTests(APITestCase):
    def setUp(self):
        clear_auth_cache()

    @override_settings(SUNBIRD_ACCESS_TOKEN="test-token")
    @patch("effecom.sunbird.requests.get")
    def test_command_checks_provider_auth_without_showing_profile(self, get):
        get.return_value = Mock(ok=True, status_code=200)
        output = StringIO()

        call_command("check_sunbird", stdout=output)

        self.assertIn("Sunbird authentication is working.", output.getvalue())
        self.assertNotIn("test-token", output.getvalue())
        get.assert_called_once_with(
            "https://api.sunbird.ai/auth/me",
            headers={"Authorization": "Bearer test-token"},
            timeout=(5, 15),
        )

    @override_settings(
        SUNBIRD_ACCESS_TOKEN="",
        SUNBIRD_USERNAME="",
        SUNBIRD_PASSWORD="",
    )
    @patch("effecom.sunbird.requests.get")
    def test_command_fails_clearly_when_token_is_missing(self, get):
        with self.assertRaisesMessage(CommandError, "SUNBIRD_USERNAME"):
            call_command("check_sunbird", stdout=StringIO())

        get.assert_not_called()

    @override_settings(SUNBIRD_ACCESS_TOKEN="invalid-token")
    @patch("effecom.sunbird.requests.get")
    def test_command_does_not_expose_provider_error_body(self, get):
        get.return_value = Mock(
            ok=False,
            status_code=401,
            text="private token detail",
        )

        with self.assertRaisesMessage(CommandError, "Sunbird rejected"):
            call_command("check_sunbird", stdout=StringIO())

        get.assert_called_once()
