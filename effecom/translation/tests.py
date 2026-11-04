from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APITestCase

from account.models import Activity
from effecom.sunbird import SunbirdError, clear_auth_cache
from translation.models import GuestSession, Language, TranslationRequest


@override_settings(
    SUNBIRD_ACCESS_TOKEN="test-token",
    SUNBIRD_USERNAME="",
    SUNBIRD_PASSWORD="",
    SUNBIRD_TRANSLATION_TIMEOUT_SECONDS=120,
)
class TranslationApiTests(APITestCase):
    def setUp(self):
        clear_auth_cache()

    @patch("effecom.sunbird.requests.post")
    def test_translation_is_forwarded_to_sunbird(self, post):
        post.return_value = Mock(
            ok=True,
            json=Mock(return_value={"translation": "Hello"}),
        )

        response = self.client.post(
            "/api/v1/translate/",
            {
                "text": "Nze ndi mukwano gwa Tracy",
                "source_language": "lug",
                "target_language": "eng",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"translation": "Hello"})
        post.assert_called_once()
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "text": "Nze ndi mukwano gwa Tracy",
                "source_language": "lug",
                "target_language": "eng",
            },
        )
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-token",
        )
        self.assertEqual(post.call_args.kwargs["timeout"], (5, 120))

    @patch("effecom.sunbird.requests.post")
    def test_signed_in_translation_is_saved_to_account_history(self, post):
        user = get_user_model().objects.create_user(
            username="history@example.com",
            email="history@example.com",
            password="secure-history-password-239!",
        )
        self.client.force_authenticate(user)
        post.return_value = Mock(
            ok=True,
            json=Mock(return_value={"translation": "Hello"}),
        )

        response = self.client.post(
            "/api/v1/translate/",
            {
                "text": "Nze ndi mukwano gwa Tracy",
                "source_language": "lug",
                "target_language": "eng",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Activity.objects.filter(user=user).count(), 1)

    @patch("effecom.sunbird.requests.post")
    def test_source_language_can_be_inferred_by_sunbird(self, post):
        post.return_value = Mock(
            ok=True,
            json=Mock(
                return_value={
                    "status": "COMPLETED",
                    "output": {
                        "translated_text": "Oli otya?",
                        "source_language": "eng",
                        "target_language": "lug",
                    },
                }
            ),
        )

        response = self.client.post(
            "/api/v1/translate/",
            {"text": "How are you?", "target_language": "lug"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            post.call_args.kwargs["json"],
            {"text": "How are you?", "target_language": "lug"},
        )

    @patch("effecom.sunbird.requests.post")
    def test_same_source_and_target_language_is_rejected(self, post):
        response = self.client.post(
            "/api/v1/translate/",
            {
                "text": "Oli otya?",
                "source_language": "lug",
                "target_language": "lug",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    @patch("effecom.sunbird.requests.post")
    def test_unsupported_language_code_is_rejected(self, post):
        response = self.client.post(
            "/api/v1/translate/",
            {
                "text": "hello",
                "source_language": "not-a-language",
                "target_language": "lug",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        post.assert_not_called()

    @patch("effecom.sunbird.requests.post")
    def test_text_over_configured_limit_is_rejected(self, post):
        response = self.client.post(
            "/api/v1/translate/",
            {
                "text": "x" * 2001,
                "source_language": "lug",
                "target_language": "eng",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        post.assert_not_called()


class TranslationV1ApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_languages", verbosity=0)

    def setUp(self):
        cache.clear()

    def create_guest_session(self, client=None):
        client = client or self.client
        response = client.post("/api/v1/guest/session/", {}, format="json")
        self.assertEqual(response.status_code, 201)
        return response

    def test_guest_session_uses_httponly_lax_cookie_and_reports_usage(self):
        response = self.create_guest_session()

        self.assertTrue(response.cookies["guest_token"]["httponly"])
        self.assertEqual(response.cookies["guest_token"]["samesite"], "Lax")
        usage = self.client.get("/api/v1/guest/usage/")

        self.assertEqual(usage.status_code, 200)
        self.assertEqual(usage.data["translations_used"], 0)
        self.assertEqual(usage.data["translations_limit"], 10)

    def test_language_catalog_filters_capability_and_keeps_stt_disabled(self):
        response = self.client.get("/api/v1/languages/?capability=translation")

        self.assertEqual(response.status_code, 200)
        self.assertIn("lug", {language["code"] for language in response.data})
        stt_response = self.client.get("/api/v1/languages/?capability=stt")
        self.assertEqual(stt_response.data, [])
        self.assertFalse(Language.objects.filter(supports_stt=True).exists())

    @patch("translation.services.post_task")
    def test_guest_translation_consumes_quota_and_returns_record(self, post_task):
        self.create_guest_session()
        post_task.return_value = {
            "id": "job-1",
            "status": "COMPLETED",
            "output": {
                "translated_text": "Oli otya?",
                "source_language": "eng",
                "target_language": "lug",
            },
        }

        response = self.client.post(
            "/api/v1/translations/",
            {"text": "How are you?", "target_language": "lug"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["translated_text"], "Oli otya?")
        self.assertEqual(response.data["detected_source_language"], "eng")
        guest = GuestSession.objects.get()
        self.assertEqual(guest.translations_used, 1)
        post_task.assert_called_once()

    @override_settings(
        GUEST_LIMITS={
            "translations": 1,
            "translate_chars": 500,
            "transcriptions": 3,
            "audio_seconds": 30,
        }
    )
    @patch("translation.services.post_task")
    def test_quota_exhaustion_does_not_call_upstream_again(self, post_task):
        self.create_guest_session()
        post_task.return_value = {"translation": "Hello"}
        request_data = {"text": "Hello", "target_language": "lug"}

        first = self.client.post(
            "/api/v1/translations/", request_data, format="json"
        )
        second = self.client.post(
            "/api/v1/translations/", request_data, format="json"
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.data["error"]["code"], "guest_quota_exceeded")
        post_task.assert_called_once()

    @patch(
        "translation.services.post_task",
        side_effect=SunbirdError("Sunbird request timed out.", status_code=504),
    )
    def test_failed_upstream_request_releases_guest_quota(self, post_task):
        self.create_guest_session()

        response = self.client.post(
            "/api/v1/translations/",
            {"text": "Hello", "target_language": "lug"},
            format="json",
        )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.data["error"]["code"], "upstream_timeout")
        self.assertEqual(GuestSession.objects.get().translations_used, 0)
        self.assertEqual(
            TranslationRequest.objects.get().status,
            TranslationRequest.Status.FAILED,
        )
        post_task.assert_called_once()

    @patch("translation.services.post_task")
    def test_guest_cannot_read_another_guests_translation(self, post_task):
        self.create_guest_session()
        post_task.return_value = {"translation": "Hello"}
        created = self.client.post(
            "/api/v1/translations/",
            {"text": "Hi", "target_language": "lug"},
            format="json",
        )
        translation_id = created.data["id"]

        other_client = self.client_class()
        self.create_guest_session(other_client)
        response = other_client.get(
            f"/api/v1/translations/{translation_id}/"
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.status_code, 404)
    @patch("translation.services.post_task")
    def test_authenticated_history_is_scoped_to_its_owner(self, post_task):
        user = get_user_model().objects.create_user(
            username="translation-owner@example.com",
            email="translation-owner@example.com",
            password="secure-test-password-239!",
        )
        self.client.force_authenticate(user)
        post_task.return_value = {"translation": "Hello"}

        created = self.client.post(
            "/api/v1/translations/",
            {"text": "Hi", "target_language": "lug"},
            format="json",
        )
        history = self.client.get("/api/v1/translations/")
        other_user = get_user_model().objects.create_user(
            username="other-owner@example.com",
            email="other-owner@example.com",
            password="secure-test-password-239!",
        )
        self.client.force_authenticate(other_user)
        inaccessible = self.client.get(
            f"/api/v1/translations/{created.data['id']}/"
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(len(history.data["results"]), 1)
        self.assertEqual(inaccessible.status_code, 404)
