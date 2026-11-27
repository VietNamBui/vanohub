from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Role, RoleAssignment, User
from accounts.testing import ProjectFixture
from cvat_integration import sync
from jobs.models import Job, JobStatus

from .models import ActivityLog, Dataset, Project


class ProjectApiTests(TestCase):
    """Kiểm tra phân quyền theo phạm vi dự án của /api/projects/."""

    def setUp(self):
        self.client = APIClient()
        self.project_a = Project.objects.create(name="Project A")
        self.project_b = Project.objects.create(name="Project B")

        self.pm = self._user("pm", Role.PROJECT_MANAGER, self.project_a)
        self.qc2_only = self._user("qc2", Role.QC2, self.project_a)
        self.annotator = self._user("ann", Role.ANNOTATOR, self.project_b)
        self.outsider = User.objects.create_user("outsider", password="pw")

    def _user(self, username, role, project):
        user = User.objects.create_user(username, password="pw")
        RoleAssignment.objects.create(user=user, role=role, project=project)
        return user

    def _list(self, user):
        self.client.force_authenticate(user)
        return self.client.get(reverse("project-list"))

    def _detail(self, user, project):
        self.client.force_authenticate(user)
        return self.client.get(reverse("project-detail", args=[project.pk]))

    def test_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("project-list")).status_code, 401)

    def test_pm_sees_only_own_project_and_is_also_qc2(self):
        response = self._list(self.pm)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([p["name"] for p in response.data], ["Project A"])
        self.assertEqual(response.data[0]["my_roles"], [Role.PROJECT_MANAGER, Role.QC2])

    def test_qc2_only_is_not_project_manager(self):
        response = self._list(self.qc2_only)
        self.assertEqual(response.data[0]["my_roles"], [Role.QC2])

    def test_user_without_roles_sees_nothing(self):
        self.assertEqual(self._list(self.outsider).data, [])

    def test_project_outside_scope_returns_404(self):
        self.assertEqual(self._detail(self.pm, self.project_b).status_code, 404)

    def test_detail_member_counts_include_implied_roles(self):
        response = self._detail(self.pm, self.project_a)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["member_total"], 2)
        # PM được tính vào QC2 → 2 người có quyền QC2 (pm + qc2_only), 1 PM.
        self.assertEqual(response.data["member_counts"], {Role.PROJECT_MANAGER: 1, Role.QC2: 2})

    def test_user_with_two_roles_is_counted_once(self):
        RoleAssignment.objects.create(user=self.pm, role=Role.QC1, project=self.project_a)
        response = self._detail(self.pm, self.project_a)
        self.assertEqual(response.data["member_total"], 2)
        self.assertEqual(response.data["my_roles"], sorted([Role.PROJECT_MANAGER, Role.QC2, Role.QC1]))





class DataManagementTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)

    def test_projects_and_tasks_are_not_created_on_vanohub(self):
        """Project (Dataset) và Task (Batch) đến từ đồng bộ CVAT, không tạo tay."""
        self.assertEqual(self.pm.post(self.f.url("datasets/"), {"name": "X"}, format="json").status_code, 405)
        self.assertEqual(self.pm.post(self.f.url("batches/"), {"name": "X"}, format="json").status_code, 405)

    def test_task_deadline_applies_to_its_unfinished_jobs(self):
        open_job = self.f.job(status=JobStatus.ANNOTATING)
        done_job = self.f.job(status=JobStatus.APPROVED)
        response = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"),
                                 {"deadline": "2026-12-01T00:00:00Z"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        open_job.refresh_from_db()
        done_job.refresh_from_db()
        self.assertIsNotNone(open_job.deadline)
        self.assertIsNone(done_job.deadline)

    def test_task_name_is_read_only_and_team_must_belong_to_org(self):
        from teams.models import Team

        self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"name": "Đổi tên"}, format="json")
        self.f.batch.refresh_from_db()
        self.assertEqual(self.f.batch.name, "B1")
        other = ProjectFixture("Q")
        foreign_team = Team.objects.create(project=other.project, name="T")
        response = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": foreign_team.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_lists_count_tasks_and_jobs(self):
        self.f.job(status=JobStatus.APPROVED)
        self.f.job(status=JobStatus.ANNOTATING)
        project = self.pm.get(self.f.url("datasets/")).data[0]
        self.assertEqual((project["task_count"], project["job_count"], project["done_count"]), (1, 2, 1))
        task = self.pm.get(self.f.url("batches/")).data[0]
        self.assertEqual((task["dataset_name"], task["job_count"]), ("D1", 2))

    def test_qc2_only_cannot_manage_data(self):
        qc2 = self.f.client(self.f.qc2)
        self.assertEqual(qc2.get(self.f.url("datasets/")).status_code, 403)
        response = qc2.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"deadline": None}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_settings_readable_by_qc2_but_only_pm_can_change(self):
        qc2 = self.f.client(self.f.qc2)
        self.assertEqual(qc2.get(self.f.url("settings/")).status_code, 200)
        self.assertEqual(qc2.patch(self.f.url("settings/"), {"sampling_rate": 20}, format="json").status_code, 403)
        self.assertEqual(self.pm.patch(self.f.url("settings/"), {"sampling_rate": 20}, format="json").status_code, 200)

    def test_delivery_requires_all_jobs_approved(self):
        job = self.f.job(status=JobStatus.PENDING_QC2)
        refused = self.pm.post(self.f.url("deliveries/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(refused.status_code, 400)
        Job.objects.filter(pk=job.pk).update(status=JobStatus.APPROVED)
        ok = self.pm.post(self.f.url("deliveries/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.DELIVERED)

    def test_overview_marks_undefined_kpis(self):
        self.f.job(status=JobStatus.APPROVED)
        data = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(data["counts"]["jobs"], 1)
        self.assertEqual(data["metrics"]["quality_cl"]["status"], "pending_definition")
        self.assertIsNone(data["metrics"]["quality_cl"]["value"])
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("overview/")).status_code, 403)

    def test_guideline_versions_increment(self):
        for _ in range(2):
            self.pm.post(self.f.url("guidelines/"), {"title": "G", "content": "x"}, format="json")
        versions = [g["version"] for g in self.f.client(self.f.ann1).get(self.f.url("guidelines/")).data]
        self.assertEqual(versions, [2, 1])


class FakeCvat:
    """CVAT giả: 1 organization (#7, owner = user CVAT 50, worker = 77), 1 project (#900), 1 task (#5)."""

    def __init__(self, jobs, owner=50):
        self.jobs = jobs
        self.owner = owner
        self.pushed = []

    def list_organizations(self):
        return [{"id": 7, "slug": "acme", "name": "ACME"}, {"id": 8, "slug": "empty", "name": "Chưa có PM"}]

    def list_memberships(self, org_id):
        if org_id != 7:
            return [{"user": {"id": 999}, "role": "owner", "is_active": True}]  # owner chưa liên kết VanoHub
        return [{"user": {"id": self.owner}, "role": "owner", "is_active": True},
                {"user": {"id": 77}, "role": "worker", "is_active": True}]

    def list_org_projects(self, org_id):
        return [{"id": 900, "name": "Robotaxi CVAT"}] if org_id == 7 else []

    def list_project_tasks(self, project_id):
        return [{"id": 5, "name": "Front cam 01"}]

    def list_task_jobs(self, task_id):
        return self.jobs

    def count_job_objects(self, job_id):
        return 7

    def set_job_assignee(self, job_id, cvat_user_id):
        self.pushed.append((job_id, cvat_user_id))


class CvatSyncTests(TestCase):
    def setUp(self):
        from cvat_integration.models import CvatAccount

        self.f = ProjectFixture()
        self.boss = User.objects.create_user("boss", password="pw")
        CvatAccount.objects.create(user=self.boss, cvat_user_id=50, cvat_username="boss_cvat")
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=77, cvat_username="cvat_ann1")

    def test_org_with_linked_owner_becomes_organization_with_pm_and_members(self):
        result = sync.sync_organizations(client=FakeCvat([]))
        org = Project.objects.get(cvat_org_id=7)
        self.assertEqual((org.name, org.cvat_org_slug), ("ACME", "acme"))
        self.assertIn(Role.PROJECT_MANAGER, self.boss.get_project_roles(org))
        self.assertEqual(self.f.ann1.get_project_roles(org), {Role.ANNOTATOR})  # worker → Annotator
        self.assertEqual([w["cvat_org_id"] for w in result["waiting"]], [8])  # chưa có PM liên kết → chưa tạo
        sync.sync_organizations(client=FakeCvat([]))
        self.assertEqual(Project.objects.filter(cvat_org_id=7).count(), 1)

    def test_new_org_pulls_projects_tasks_and_annotation_jobs_only(self):
        client = FakeCvat([
            {"id": 101, "type": "annotation", "stage": "annotation", "state": "in progress",
             "start_frame": 0, "stop_frame": 9, "assignee": {"id": 77}},
            {"id": 102, "type": "annotation", "stage": "validation", "state": "completed",
             "start_frame": 10, "stop_frame": 19, "assignee": None},
            {"id": 103, "type": "ground_truth", "stage": "annotation", "state": "new", "start_frame": 0, "stop_frame": 3},
        ])
        sync.sync_organizations(client=client)
        org = Project.objects.get(cvat_org_id=7)
        dataset = Dataset.objects.get(cvat_project_id=900)
        task = dataset.batches.get()
        self.assertEqual((dataset.project, task.cvat_task_id, task.name), (org, 5, "Front cam 01"))
        j101 = Job.objects.get(cvat_job_id=101)
        self.assertEqual((j101.status, j101.annotator, j101.frame_count, j101.batch), (JobStatus.ANNOTATING, self.f.ann1, 10, task))
        j102 = Job.objects.get(cvat_job_id=102)
        self.assertEqual((j102.status, j102.cvat_start_frame), (JobStatus.PENDING_QC2, 10))
        self.assertEqual(j102.audit_samples.count(), 1)  # vào Chờ QC2 → có lượt QC2
        self.assertFalse(Job.objects.filter(cvat_job_id=103).exists())  # bỏ Ground Truth job

    def _linked_fixture(self):
        self.f.project.cvat_org_id = 7
        self.f.project.save()
        self.f.dataset.cvat_project_id = 900
        self.f.dataset.save()
        self.f.batch.cvat_task_id = 5
        self.f.batch.save()

    def test_sync_never_overrides_jobs_already_in_qc2(self):
        self._linked_fixture()
        job = self.f.job(status=JobStatus.APPROVED, cvat_job_id=201)
        sync.sync_organization(self.f.project, self.f.pm,
                               client=FakeCvat([{"id": 201, "stage": "annotation", "state": "new"}]), count_objects=True)
        job.refresh_from_db()
        self.assertEqual((job.status, job.object_count), (JobStatus.APPROVED, 7))

    def test_cvat_rejection_increments_rework_round(self):
        self._linked_fixture()
        job = self.f.job(status=JobStatus.QC1_REVIEWING, cvat_job_id=301)
        sync.sync_organization(self.f.project, self.f.pm,
                               client=FakeCvat([{"id": 301, "stage": "validation", "state": "rejected"}]))
        job.refresh_from_db()
        self.assertEqual((job.status, job.rework_round), (JobStatus.REWORK, 1))


class MemberRolesTests(TestCase):
    def setUp(self):
        from accounts.testing import ProjectFixture

        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)

    def _add(self, client, user, role):
        return client.post(self.f.url(f"members/{user.id}/roles/"), {"role": role}, format="json")

    def test_pm_can_add_role(self):
        response = self._add(self.pm, self.f.ann1, "qc1")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIn("qc1", response.data["roles"])
        self.assertIn("qc1", self.f.ann1.get_project_roles(self.f.project))

    def test_cannot_add_pm_or_existing_or_implied_role(self):
        self.assertEqual(self._add(self.pm, self.f.ann1, "project_manager").status_code, 400)
        self.assertEqual(self._add(self.pm, self.f.ann1, "annotator").status_code, 400)
        self.assertEqual(self._add(self.pm, self.f.pm, "qc2").status_code, 400)  # PM đã ngầm có QC2

    def test_qc2_only_cannot_add_role(self):
        self.assertEqual(self._add(self.f.client(self.f.qc2), self.f.ann1, "qc1").status_code, 403)

    def test_user_outside_project_is_404(self):
        from accounts.testing import make_user

        other = Project.objects.create(name="Other")
        outsider = make_user("outsider", "annotator", project=other)
        self.assertEqual(self._add(self.pm, outsider, "qc1").status_code, 404)


class BatchTeamTests(TestCase):
    def setUp(self):
        from teams.models import Team

        self.f = ProjectFixture()
        self.team = Team.objects.create(project=self.f.project, name="Team A")
        other = Project.objects.create(name="Other")
        self.foreign_team = Team.objects.create(project=other, name="Team X")
        self.pm = self.f.client(self.f.pm)

    def test_pm_assigns_team_to_batch(self):
        response = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": self.team.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["team_name"], "Team A")
        response = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": None}, format="json")
        self.assertIsNone(response.data["team"])

    def test_team_from_other_project_is_rejected(self):
        response = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": self.foreign_team.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_deleting_team_unassigns_batch(self):
        self.f.batch.team = self.team
        self.f.batch.save()
        self.team.delete()
        self.f.batch.refresh_from_db()
        self.assertIsNone(self.f.batch.team)


class MemberAccountTests(TestCase):
    """PM tạo tài khoản thành viên, xem / cấp lại mật khẩu tạm; người dùng tự đổi mật khẩu."""

    def setUp(self):
        from accounts.testing import ProjectFixture

        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)

    def _create(self, client=None, **data):
        payload = {"full_name": "Nguyễn Văn Đức", "roles": ["annotator"], **data}
        return (client or self.pm).post(self.f.url("members/"), payload, format="json")

    def test_pm_creates_account_with_generated_username_and_password(self):
        from accounts.models import User

        response = self._create(roles=["annotator", "qc1"])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["username"], "nguyenvanduc")
        user = User.objects.get(username="nguyenvanduc")
        self.assertTrue(user.check_password(response.data["password"]))
        self.assertEqual(sorted(user.get_project_roles(self.f.project)), ["annotator", "qc1"])
        # Trùng tên → thêm số
        self.assertEqual(self._create().data["username"], "nguyenvanduc2")

    def test_only_manage_team_can_create(self):
        self.assertEqual(self._create(client=self.f.client(self.f.ann1)).status_code, 403)

    def test_cannot_put_member_in_team_of_other_project(self):
        from teams.models import Team

        other = Project.objects.create(name="Khác")
        team = Team.objects.create(project=other, name="T")
        self.assertEqual(self._create(team=team.id).status_code, 400)

    def test_credential_visible_until_user_changes_password(self):
        from accounts.models import User

        created = self._create().data
        user_id = created["user"]["id"]
        cred = self.pm.get(self.f.url(f"members/{user_id}/credential/")).data
        self.assertEqual((cred["status"], cred["password"]), ("initial", created["password"]))
        self.assertTrue(ActivityLog.objects.filter(action="member.view_password").exists())
        listed = next(m for m in self.pm.get(self.f.url("members/")).data if m["user"]["id"] == user_id)
        self.assertTrue(listed["has_initial_password"])
        self.assertFalse(listed["cvat_linked"])

        me = self.f.client(User.objects.get(pk=user_id))
        response = me.post("/api/auth/me/password/",
                           {"current_password": created["password"], "new_password": "Moi-Mat-Khau-2026"}, format="json")
        self.assertEqual(response.status_code, 204, response.data)
        cred = self.pm.get(self.f.url(f"members/{user_id}/credential/")).data
        self.assertEqual((cred["status"], cred["password"]), ("changed", None))

    def test_change_password_requires_current_password(self):
        response = self.f.client(self.f.ann1).post(
            "/api/auth/me/password/", {"current_password": "sai", "new_password": "Moi-Mat-Khau-2026"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_reset_password(self):
        response = self.pm.post(self.f.url(f"members/{self.f.ann1.id}/reset-password/"))
        self.assertEqual(response.status_code, 200, response.data)
        self.f.ann1.refresh_from_db()
        self.assertTrue(self.f.ann1.check_password(response.data["password"]))
        # Không cấp lại cho PM / chính mình
        self.assertEqual(self.pm.post(self.f.url(f"members/{self.f.pm.id}/reset-password/")).status_code, 400)


class MemberRoleRemovalTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        RoleAssignment.objects.create(user=self.f.ann1, role=Role.QC1, project=self.f.project)

    def _remove(self, user, role, client=None):
        return (client or self.pm).delete(self.f.url(f"members/{user.id}/roles/{role}/"))

    def test_pm_removes_role(self):
        response = self._remove(self.f.ann1, "qc1")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["roles"], ["annotator"])
        self.assertTrue(ActivityLog.objects.filter(action="member.remove_role").exists())

    def test_cannot_remove_last_role_implied_role_or_pm(self):
        self.assertEqual(self._remove(self.f.ann2, "annotator").status_code, 400)  # vai trò cuối cùng
        self.assertEqual(self._remove(self.f.pm, "qc2").status_code, 400)  # QC2 đi kèm PM
        self.assertEqual(self._remove(self.f.pm, "project_manager").status_code, 400)

    def test_cannot_remove_role_while_holding_its_work(self):
        self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)

        RoleAssignment.objects.create(user=self.f.qc1, role=Role.ANNOTATOR, project=self.f.project)
        self.assertEqual(self._remove(self.f.qc1, "qc1").status_code, 400)

    def test_only_manage_team_can_remove(self):
        self.assertEqual(self._remove(self.f.ann1, "qc1", client=self.f.client(self.f.qc2)).status_code, 403)
