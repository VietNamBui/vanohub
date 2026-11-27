from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from projects.models import Project

from .models import Role, RoleAssignment, User, expand_roles


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
            RoleAssignment.objects.create(user=self.user, role=Role.PROJECT_MANAGER, project=None)

    def test_same_role_same_project_is_rejected(self):
        RoleAssignment.objects.create(user=self.user, role=Role.QC2, project=self.project)
        with self.assertRaises(IntegrityError):
            RoleAssignment.objects.create(user=self.user, role=Role.QC2, project=self.project)


class AuthApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user("bob", password="secret-pw")
        self.project = Project.objects.create(name="P1")
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
        self.assertEqual(me.data["role_assignments"][0]["role"], Role.PROJECT_MANAGER)

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

    def test_change_password_validates_current_password(self):
        from . import credentials

        credentials.set_initial_password(self.user, "secret-pw")
        self.user.save(update_fields=["password", "initial_password_encrypted"])
        self.client.force_authenticate(self.user)
        bad = self.client.post(
            reverse("change-password"),
            {"current_password": "wrong", "new_password": "NewStrongPassword#2026"},
            format="json",
        )
        self.assertEqual(bad.status_code, 400)

        ok = self.client.post(
            reverse("change-password"),
            {"current_password": "secret-pw", "new_password": "NewStrongPassword#2026"},
            format="json",
        )
        self.assertEqual(ok.status_code, 204)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrongPassword#2026"))
        self.assertEqual(self.user.initial_password_encrypted, "")
