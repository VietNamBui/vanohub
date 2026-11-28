from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

User = get_user_model()


class UnifiedAuthTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="test_qc",
            password="testpassword123",
            email="test_qc@company.local",
            is_staff=False,
        )

    def test_local_login_success(self) -> None:
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "test_qc", "password": "testpassword123"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("token", resp.data)
        self.assertEqual(resp.data["user"]["username"], "test_qc")

    def test_local_login_invalid_credentials(self) -> None:
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "test_qc", "password": "wrongpassword"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_missing_fields(self) -> None:
        resp = self.client.post("/api/auth/login/", {"username": "test_qc"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(CVAT_BASE_URL="http://cvat-test-server:8080")
    @mock.patch("requests.post")
    @mock.patch("requests.get")
    def test_cvat_unified_login_success(self, mock_get: mock.MagicMock, mock_post: mock.MagicMock) -> None:
        # Mock CVAT /api/auth/login response
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"key": "cvat_valid_secret_token_123"}

        # Mock CVAT /api/users/self response
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "id": 99,
            "username": "cvat_user_alice",
            "email": "alice@cvat.org",
            "is_staff": True,
            "is_superuser": False,
        }

        resp = self.client.post(
            "/api/auth/login/",
            {"username": "cvat_user_alice", "password": "cvatpassword"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["token"], "cvat_valid_secret_token_123")
        self.assertEqual(resp.data["user"]["username"], "cvat_user_alice")
        self.assertTrue(resp.data["user"]["is_staff"])

        # User is automatically synchronized into local database
        synced_user = User.objects.filter(username="cvat_user_alice").first()
        self.assertIsNotNone(synced_user)
        self.assertTrue(synced_user.is_staff)

    @override_settings(CVAT_BASE_URL="http://cvat-test-server:8080")
    @mock.patch("requests.post")
    def test_cvat_unified_login_fails_when_user_not_in_cvat(self, mock_post: mock.MagicMock) -> None:
        # If user does not exist in CVAT, CVAT returns 400 or 401
        mock_post.return_value.status_code = 400
        mock_post.return_value.json.return_value = {"non_field_errors": ["Unable to log in with provided credentials."]}

        resp = self.client.post(
            "/api/auth/login/",
            {"username": "unknown_cvat_user", "password": "somepassword"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn("Tài khoản hoặc mật khẩu không chính xác", resp.data["detail"])

    def test_current_user_and_logout(self) -> None:
        token, _ = Token.objects.get_or_create(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        resp_user = self.client.get("/api/auth/user/")
        self.assertEqual(resp_user.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_user.data["username"], "test_qc")
        self.assertEqual(resp_user.data["role"], "annotator")

        resp_logout = self.client.post("/api/auth/logout/")
        self.assertEqual(resp_logout.status_code, status.HTTP_200_OK)

    @override_settings(CVAT_BASE_URL="http://cvat-test-server:8080")
    @mock.patch("requests.post")
    @mock.patch("requests.get")
    def test_cvat_login_fails_closed_when_verify_with_cvat_fails(
        self, mock_get: mock.MagicMock, mock_post: mock.MagicMock
    ) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"key": "cvat_token_unverified"}
        mock_get.return_value.status_code = 500

        resp = self.client.post(
            "/api/auth/login/",
            {"username": "ghost_user", "password": "pw"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertFalse(User.objects.filter(username="ghost_user").exists())

    @override_settings(CVAT_BASE_URL="http://cvat-test-server:8080")
    @mock.patch("requests.post")
    @mock.patch("requests.get")
    def test_cvat_login_syncs_staff_demotion_down(
        self, mock_get: mock.MagicMock, mock_post: mock.MagicMock
    ) -> None:
        existing = User.objects.create_user(
            username="demoted_admin",
            password="pw",
            email="old@company.local",
            is_staff=True,
            is_superuser=True,
        )
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"key": "cvat_tok_demoted"}
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "id": 101,
            "username": "demoted_admin",
            "email": "new@company.local",
            "is_staff": False,
            "is_superuser": False,
        }

        resp = self.client.post(
            "/api/auth/login/",
            {"username": "demoted_admin", "password": "pw"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        existing.refresh_from_db()
        self.assertFalse(existing.is_staff)
        self.assertFalse(existing.is_superuser)
        self.assertEqual(existing.email, "new@company.local")

    @override_settings(CVAT_BASE_URL="http://cvat-test-server:8080", CVAT_REQUIRE_HTTPS=True)
    def test_cvat_login_blocks_plain_http_when_https_required(self) -> None:
        resp = self.client.post(
            "/api/auth/login/",
            {"username": "test_qc", "password": "testpassword123"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
