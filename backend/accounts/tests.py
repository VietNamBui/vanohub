import logging
from typing import Any, cast
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.db import DatabaseError, IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from cvat_integration.models import CvatAccount
from projects.models import Project

from . import credentials
from .models import Role, RoleAssignment, User, expand_roles
from .permissions import Cap


class ExpandRolesTests(TestCase):
    def test_pm_implies_qc2(self):
        self.assertEqual(expand_roles([Role.PROJECT_MANAGER]), {Role.PROJECT_MANAGER, Role.QC2})

    def test_qc2_does_not_imply_pm(self):
        self.assertEqual(expand_roles([Role.QC2]), {Role.QC2})

    def test_only_four_roles_remain(self):
        self.assertEqual(set(Role.values), {"project_manager", "qc2", "qc1", "annotator"})


class RoleAssignmentConstraintTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.project = Project.objects.create(name="P1")

    def test_project_role_requires_project(self):
        with self.assertRaises(IntegrityError):
            RoleAssignment.objects.create(user=self.user, role=Role.PROJECT_MANAGER, project=cast(Any, None))

    def test_same_role_same_project_is_rejected(self):
        RoleAssignment.objects.create(user=self.user, role=Role.QC2, project=self.project)
        with self.assertRaises(IntegrityError):
            RoleAssignment.objects.create(user=self.user, role=Role.QC2, project=self.project)


class AuthApiTests(TestCase):
    client: Any

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("bob", password="secret-pw")
        self.project = Project.objects.create(name="P1", cvat_org_slug="org-p1")
        RoleAssignment.objects.create(user=self.user, role=Role.PROJECT_MANAGER, project=self.project)

    def test_login_returns_tokens_and_me_works_with_bearer(self):
        response = self.client.post(
            reverse("token_obtain_pair"), {"username": "bob", "password": "secret-pw"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        me = self.client.get(reverse("me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["username"], "bob")
        self.assertNotIn("is_director", me.data)
        self.assertTrue(me.data["is_pm"])
        self.assertFalse(me.data["cvat_linked"])
        self.assertIsNone(me.data["cvat_username"])
        self.assertEqual(me.data["role_assignments"][0]["role"], Role.PROJECT_MANAGER)
        self.assertEqual(len(me.data["projects"]), 1)
        proj = me.data["projects"][0]
        self.assertEqual(proj["id"], self.project.id)
        self.assertEqual(proj["cvat_org_slug"], "org-p1")
        self.assertEqual(proj["roles"], [Role.PROJECT_MANAGER, Role.QC2])
        self.assertIn(Cap.MANAGE_TEAM, proj["capabilities"])
        self.assertIn(Cap.PERFORM_AUDIT, proj["capabilities"])

    def test_me_reflects_cvat_account_and_ignores_cvat_username_write(self):
        CvatAccount.objects.create(user=self.user, cvat_user_id=77, cvat_username="bob_cvat")
        self.client.force_authenticate(self.user)
        res = self.client.patch(reverse("me"), {"cvat_username": "spoofed"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertTrue(res.data["cvat_linked"])
        self.assertEqual(res.data["cvat_username"], "bob_cvat")

    def test_wrong_password_is_rejected(self):
        response = self.client.post(
            reverse("token_obtain_pair"), {"username": "bob", "password": "wrong"}, format="json"
        )
        self.assertEqual(response.status_code, 401)

    def test_me_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("me")).status_code, 401)

    def test_patch_me_updates_profile_and_notification_preferences(self):
        self.client.force_authenticate(self.user)
        res = self.client.patch(
            reverse("me"),
            {
                "full_name": "Hà Thị Lan",
                "email": "lan.ha@annota.vn",
                "timezone_name": "Asia/Ho_Chi_Minh",
                "notify_rework": False,
                "notify_qc_pass": True,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["first_name"], "Hà")
        self.assertEqual(res.data["last_name"], "Thị Lan")
        self.assertEqual(res.data["email"], "lan.ha@annota.vn")
        self.assertEqual(res.data["timezone_name"], "Asia/Ho_Chi_Minh")
        self.assertFalse(res.data["notify_rework"])

    def test_patch_me_keeps_fixed_vietnam_timezone(self):
        self.client.force_authenticate(self.user)
        res = self.client.patch(reverse("me"), {"timezone_name": "Asia/Tokyo"}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["timezone_name"], "Asia/Ho_Chi_Minh")
        self.user.refresh_from_db()
        self.assertEqual(self.user.timezone_name, "Asia/Ho_Chi_Minh")

    def test_change_password_validates_current_password_and_clears_initial_password(self):
        credentials.set_initial_password(self.user, "secret-pw")
        self.user.save(update_fields=["password", "initial_password_encrypted"])
        self.client.force_authenticate(self.user)

        bad = self.client.post(
            reverse("change-password"),
            {"current_password": "wrong", "new_password": "NewStrongPassword#2026"},
            format="json",
        )
        self.assertEqual(bad.status_code, 400)

        same = self.client.post(
            reverse("change-password"),
            {"current_password": "secret-pw", "new_password": "secret-pw"},
            format="json",
        )
        self.assertEqual(same.status_code, 400)

        ok = self.client.post(
            reverse("change-password"),
            {"current_password": "secret-pw", "new_password": "NewStrongPassword#2026"},
            format="json",
        )
        self.assertEqual(ok.status_code, 204)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPassword#2026"))
        self.assertEqual(self.user.initial_password_encrypted, "")

    def test_patch_me_rejects_xss_and_invalid_avatar_urls(self):
        self.client.force_authenticate(self.user)
        bad_urls = [
            "javascript:alert(1)",
            "JAVASCRIPT:alert(document.cookie)",
            "data:text/html,<script>alert(1)</script>",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+PC9zdmc+",
            "ftp://example.com/avatar.png",
            "data:image/png;base64," + ("A" * 500_000),
        ]
        for url in bad_urls:
            res = self.client.patch(reverse("me"), {"avatar_url": url}, format="json")
            self.assertEqual(res.status_code, 400, f"Expected 400 for {url[:60]}, got {res.status_code}")

    def test_patch_me_accepts_safe_avatar_urls_and_empty(self):
        self.client.force_authenticate(self.user)
        safe_urls = [
            "",
            "https://cdn.example.com/avatar.png",
            "http://localhost:8000/media/avatar.jpg",
            "data:image/png;base64,iVBORw0KGgo=",
            "data:image/webp;base64,UklGRh4AAABXRUJQ",
            "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7",
        ]
        for url in safe_urls:
            res = self.client.patch(reverse("me"), {"avatar_url": url}, format="json")
            self.assertEqual(res.status_code, 200, f"Expected 200 for {url}, got {res.status_code}: {res.data}")
            self.assertEqual(res.data["avatar_url"], url)

    def test_change_password_rejects_non_string_payloads_with_400(self):
        self.client.force_authenticate(self.user)
        payloads: list[Any] = [
            {"current_password": ["secret-pw"], "new_password": "NewStrongPassword#2026"},
            {"current_password": 12345, "new_password": "NewStrongPassword#2026"},
            {"current_password": {"pw": "secret-pw"}, "new_password": "NewStrongPassword#2026"},
            {"current_password": None, "new_password": "NewStrongPassword#2026"},
            {"current_password": "secret-pw", "new_password": ["NewStrongPassword#2026"]},
            {"current_password": "secret-pw", "new_password": {"pw": "NewStrongPassword#2026"}},
            {"current_password": "secret-pw", "new_password": 99999999},
            {"current_password": "secret-pw", "new_password": None},
            {"current_password": "", "new_password": "NewStrongPassword#2026"},
            {"current_password": "secret-pw", "new_password": ""},
        ]
        for payload in payloads:
            res = self.client.post(reverse("change-password"), payload, format="json")
            self.assertEqual(res.status_code, 400, f"Expected 400 for {payload}, got {res.status_code}")


class SecurityAndBoundaryTests(TestCase):
    client: Any

    def setUp(self):
        self.client = APIClient()
        self.project = Project.objects.create(name="SecOrg")
        self.pm = User.objects.create_user("sec_pm", password="pw-pm")
        self.pm2 = User.objects.create_user("sec_pm2", password="pw-pm2")
        self.member = User.objects.create_user("sec_member", password="pw-old")
        RoleAssignment.objects.create(user=self.pm, role=Role.PROJECT_MANAGER, project=self.project)
        RoleAssignment.objects.create(user=self.pm2, role=Role.PROJECT_MANAGER, project=self.project)
        RoleAssignment.objects.create(user=self.member, role=Role.ANNOTATOR, project=self.project)
        RoleAssignment.objects.create(user=self.member, role=Role.QC1, project=self.project)

    def _login(self, username: str, password: str) -> dict[str, str]:
        res = self.client.post(reverse("token_obtain_pair"), {"username": username, "password": password}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        return {"access": res.data["access"], "refresh": res.data["refresh"]}

    def test_jwt_revoked_on_password_change_reset_role_removal_and_pm_sync(self):
        tokens = self._login("sec_member", "pw-old")
        member_client = APIClient()
        member_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(member_client.get(reverse("me")).status_code, 200)

        # 1. Tự đổi mật khẩu → thu hồi ngay cả access và refresh token cũ
        self.assertEqual(
            member_client.post(
                reverse("change-password"),
                {"current_password": "pw-old", "new_password": "NewStrongPassword#2026"},
                format="json",
            ).status_code,
            204,
        )
        self.assertEqual(member_client.get(reverse("me")).status_code, 401)
        self.assertEqual(
            self.client.post(reverse("token_refresh"), {"refresh": tokens["refresh"]}, format="json").status_code,
            401,
        )

        # Đăng nhập lại với mật khẩu mới hoạt động bình thường
        tokens2 = self._login("sec_member", "NewStrongPassword#2026")
        member_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens2['access']}")
        self.assertEqual(member_client.get(reverse("me")).status_code, 200)

        # 2. PM reset mật khẩu thành viên → thu hồi ngay JWT của thành viên
        pm_client = APIClient()
        pm_client.force_authenticate(self.pm)
        reset = pm_client.post(f"/api/projects/{self.project.id}/members/{self.member.id}/reset-password/")
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(member_client.get(reverse("me")).status_code, 401)
        self.assertEqual(
            self.client.post(reverse("token_refresh"), {"refresh": tokens2["refresh"]}, format="json").status_code,
            401,
        )

        # 3. Gỡ vai trò thành viên → thu hồi ngay JWT của thành viên
        tokens3 = self._login("sec_member", reset.data["password"])
        member_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens3['access']}")
        self.assertEqual(member_client.get(reverse("me")).status_code, 200)
        del_role = pm_client.delete(f"/api/projects/{self.project.id}/members/{self.member.id}/roles/qc1/")
        self.assertEqual(del_role.status_code, 200)
        self.assertEqual(member_client.get(reverse("me")).status_code, 401)
        self.assertEqual(
            self.client.post(reverse("token_refresh"), {"refresh": tokens3["refresh"]}, format="json").status_code,
            401,
        )

        # 4. Gỡ PM qua PATCH /api/projects/{id}/ → thu hồi ngay JWT của PM bị gỡ
        pm2_tokens = self._login("sec_pm2", "pw-pm2")
        pm2_client = APIClient()
        pm2_client.credentials(HTTP_AUTHORIZATION=f"Bearer {pm2_tokens['access']}")
        self.assertEqual(pm2_client.get(reverse("me")).status_code, 200)
        upd = pm_client.patch(
            reverse("project-detail", args=[self.project.id]),
            {"pm_ids": [self.pm.id]},
            format="json",
        )
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(pm2_client.get(reverse("me")).status_code, 401)
        self.assertEqual(
            self.client.post(reverse("token_refresh"), {"refresh": pm2_tokens["refresh"]}, format="json").status_code,
            401,
        )

    def test_credential_keys_decouple_from_secret_key_with_legacy_fallback(self):
        legacy_token = credentials.encrypt("TempPass#1")
        self.assertEqual(credentials.decrypt(legacy_token), "TempPass#1")

        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()
        with override_settings(
            CREDENTIAL_ENCRYPTION_KEYS=[key1],
            CREDENTIAL_LEGACY_SECRET_KEY_FALLBACK=True,
        ):
            # Vẫn giải mã được token cũ mã hoá bằng SECRET_KEY
            self.assertEqual(credentials.decrypt(legacy_token), "TempPass#1")
            new_token = credentials.encrypt("TempPass#2")

        # Khi đổi SECRET_KEY và xoay sang [key2, key1], token mới vẫn đọc được
        with override_settings(
            SECRET_KEY="rotated-django-secret-key-value",
            CREDENTIAL_ENCRYPTION_KEYS=[key2, key1],
            CREDENTIAL_LEGACY_SECRET_KEY_FALLBACK=True,
        ):
            self.assertEqual(credentials.decrypt(new_token), "TempPass#2")

        # Tắt fallback → token cũ mã hoá bằng SECRET_KEY trở thành unreadable (None)
        with override_settings(
            CREDENTIAL_ENCRYPTION_KEYS=[key1],
            CREDENTIAL_LEGACY_SECRET_KEY_FALLBACK=False,
        ):
            self.assertIsNone(credentials.decrypt(legacy_token))

    def test_logging_secret_redaction_filter_masks_sensitive_values(self):
        from config.settings import RedactingFormatter, SecretRedactionFilter

        filt = SecretRedactionFilter()
        fmt = RedactingFormatter("%(message)s")
        with override_settings(
            SECRET_KEY="super-secret-django-key",
            CVAT_ACCESS_TOKEN="cvat-pat-secret-value",
            CVAT_PASSWORD="cvat-login-password",
        ):
            record = logging.LogRecord(
                name="cvat_integration",
                level=logging.WARNING,
                pathname=__file__,
                lineno=1,
                msg="Header Authorization: Bearer %s token=%s password=%s key=%s",
                args=("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signaturevalue", "cvat-pat-secret-value", "cvat-login-password", "super-secret-django-key"),
                exc_info=None,
            )
            filt.filter(record)
            rendered = fmt.format(record)
            self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", rendered)
            self.assertNotIn("cvat-pat-secret-value", rendered)
            self.assertNotIn("cvat-login-password", rendered)
            self.assertNotIn("super-secret-django-key", rendered)
            self.assertIn("[REDACTED]", rendered)

    def test_project_scoped_overflow_project_id_returns_404(self):
        pm_client = APIClient()
        pm_client.force_authenticate(self.pm)
        for bad_id in ("999999999999", "99999999999999999999999"):
            res = pm_client.get(f"/api/projects/{bad_id}/jobs/")
            self.assertEqual(res.status_code, 404, f"Expected 404 for {bad_id}, got {res.status_code}")

    def test_health_endpoint_checks_database_without_auth(self):
        anon = APIClient()
        ok = anon.get(reverse("health"))
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json(), {"status": "ok", "database": "ok"})
        self.assertEqual(ok["Cache-Control"], "no-store")
        self.assertEqual(anon.post(reverse("health"), {}, format="json").status_code, 405)

        with patch("config.views.connection.cursor", side_effect=DatabaseError("db down")):
            down = anon.get(reverse("health"))
        self.assertEqual(down.status_code, 503)
        self.assertEqual(down.json(), {"status": "error", "database": "unavailable"})
        self.assertEqual(down["Cache-Control"], "no-store")
