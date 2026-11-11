from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from rest_framework.test import APITestCase

from .models import Activity


class UserModelTests(TestCase):
    def test_user_has_unique_email_and_hashed_password(self):
        self.assertTrue(get_user_model()._meta.get_field("email").unique)
        user = get_user_model().objects.create_user(
            username="mariam",
            email="mariam@example.com",
            password="a-strong-test-password",
        )

        self.assertEqual(user.email, "mariam@example.com")
        self.assertTrue(user.check_password("a-strong-test-password"))
        self.assertFalse(user.check_password("not-the-password"))


class AccountApiTests(APITestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="secure-member-password-239!",
            first_name="Member",
        )

    def test_guest_cannot_read_activity_history(self):
        response = self.client.get("/api/v1/account/history/")
        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_user_can_update_profile_name(self):
        self.client.force_authenticate(self.user)

        response = self.client.patch(
            "/api/v1/auth/me/",
            {"first_name": "Updated"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["first_name"], "Updated")
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Updated")

    def test_tool_options_only_list_supported_translation_languages(self):
        response = self.client.get("/api/v1/auth/options/")

        self.assertEqual(response.status_code, 200)
        codes = {language["code"] for language in response.data["languages"]}
        self.assertTrue(
            codes.issubset(settings.SUNBIRD_TRANSLATION_SUPPORTED_LANGUAGES)
        )
        self.assertNotIn("fra", codes)
        self.assertNotIn("kpo", codes)
        self.assertNotIn("lth", codes)
        self.assertEqual(
            {language["code"] for language in response.data["stt_languages"]},
            set(settings.SUNBIRD_STT_LANGUAGES),
        )

    def test_activity_history_is_scoped_to_signed_in_user(self):
        other_user = get_user_model().objects.create_user(
            username="other@example.com",
            email="other@example.com",
            password="secure-other-password-239!",
        )
        Activity.objects.create(
            user=self.user,
            tool=Activity.Tool.TRANSLATION,
            text="My message",
            source_language="lug",
            target_language="eng",
            result={"translation": "My result"},
        )
        Activity.objects.create(
            user=other_user,
            tool=Activity.Tool.TRANSLATION,
            text="Private message",
            source_language="lug",
            target_language="eng",
            result={"translation": "Private result"},
        )

        self.client.force_authenticate(self.user)
        response = self.client.get("/api/v1/account/history/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["text"], "My message")

    def test_csrf_bootstrap_and_registration_set_jwt_cookies(self):
        client = Client(enforce_csrf_checks=True)
        csrf_response = client.get("/api/v1/auth/csrf/")
        token = csrf_response.json()["csrfToken"]

        response = client.post(
            "/api/v1/auth/register/",
            {
                "email": "new-member@example.com",
                "first_name": "New",
                "password": "difficult-passphrase-Z9!",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=token,
        )

        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.json())
        self.assertIn("effecom_access", response.cookies)
        self.assertIn("effecom_refresh", response.cookies)
        self.assertTrue(response.cookies["effecom_access"]["httponly"])
        self.assertTrue(response.cookies["effecom_refresh"]["httponly"])
        self.assertEqual(
            client.get("/api/v1/auth/me/").status_code,
            200,
        )

    @override_settings(CSRF_COOKIE_SAMESITE="None", CSRF_COOKIE_SECURE=True)
    def test_csrf_cookie_supports_cross_site_frontend(self):
        response = self.client.get("/api/v1/auth/csrf/")

        csrf_cookie = response.cookies["csrftoken"]
        self.assertEqual(csrf_cookie["samesite"], "None")
        self.assertTrue(csrf_cookie["secure"])

    def test_registration_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)

        response = client.post(
            "/api/v1/auth/register/",
            {
                "email": "new-member@example.com",
                "first_name": "New",
                "password": "difficult-passphrase-Z9!",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_login_with_email_sets_jwt_cookies(self):
        csrf = self.client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        response = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "MEMBER@example.com",
                "password": "secure-member-password-239!",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("effecom_access", response.cookies)
        self.assertIn("effecom_refresh", response.cookies)
        self.assertEqual(
            self.client.get("/api/v1/auth/me/").status_code,
            200,
        )

    def test_refresh_renews_access_cookie(self):
        client = Client(enforce_csrf_checks=True)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        login = client.post(
            "/api/v1/auth/login/",
            {
                "email": "member@example.com",
                "password": "secure-member-password-239!",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(login.status_code, 200)
        csrf = client.cookies["csrftoken"].value

        response = client.post(
            "/api/v1/auth/token/refresh/",
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )

        self.assertEqual(response.status_code, 204)
        self.assertIn("effecom_access", response.cookies)
        self.assertEqual(client.get("/api/v1/auth/me/").status_code, 200)

    def test_cookie_authenticated_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        csrf = client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        login = client.post(
            "/api/v1/auth/login/",
            {
                "email": "member@example.com",
                "password": "secure-member-password-239!",
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(login.status_code, 200)

        response = client.patch(
            "/api/v1/auth/me/",
            {"first_name": "Updated"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_logout_clears_and_blacklists_refresh_cookie(self):
        csrf = self.client.get("/api/v1/auth/csrf/").json()["csrfToken"]
        login = self.client.post(
            "/api/v1/auth/login/",
            {
                "email": "member@example.com",
                "password": "secure-member-password-239!",
            },
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(login.status_code, 200)
        refresh_token = self.client.cookies["effecom_refresh"].value

        response = self.client.post(
            "/api/v1/auth/logout/",
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.cookies["effecom_refresh"]["max-age"], 0)
        self.client.cookies["effecom_refresh"] = refresh_token
        refresh = self.client.post(
            "/api/v1/auth/token/refresh/",
            format="json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(refresh.status_code, 401)
