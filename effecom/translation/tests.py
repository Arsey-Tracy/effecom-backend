from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from account.models import Activity
from effecom.sunbird import clear_auth_cache


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
