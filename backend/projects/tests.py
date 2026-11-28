from datetime import timedelta
from typing import Any
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, RoleAssignment, User
from accounts.testing import ProjectFixture, make_user
from cvat_integration import sync
from cvat_integration.models import CvatAccount
from jobs.models import DailyOutputRecord, Job, JobStatus
from quality.models import Audit, AuditSample
from teams.models import Team

from .models import (
    ActivityLog,
    Announcement,
    AnnouncementRead,
    Batch,
    Dataset,
    DataStatus,
    Project,
    SamplingMethod,
    UserNotification,
)


class ProjectApiTests(TestCase):
    """Kiểm tra phân quyền theo phạm vi organization của /api/projects/."""

    client: Any

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
        response = self.pm.patch(
            self.f.url(f"batches/{self.f.batch.id}/"),
            {"deadline": "2026-12-01T00:00:00Z"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        open_job.refresh_from_db()
        done_job.refresh_from_db()
        self.assertIsNotNone(open_job.deadline)
        self.assertIsNone(done_job.deadline)

    def test_task_name_is_read_only_and_team_must_belong_to_org(self):
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
        ok = self.pm.patch(
            self.f.url("settings/"),
            {"sampling_rate": 20, "escalation_policy": "warn_only", "annotator_wip_limit": 3},
            format="json",
        )
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(ok.data["escalation_policy"], "warn_only")
        self.assertEqual(ok.data["annotator_wip_limit"], 3)
        # max_rework_rounds = 0 → 400
        self.assertEqual(
            self.pm.patch(self.f.url("settings/"), {"max_rework_rounds": 0}, format="json").status_code,
            400,
        )

    def test_delivery_requires_all_jobs_approved_and_recipient_output_path_and_logs_updates(self):
        job = self.f.job(status=JobStatus.PENDING_QC2)
        payload = {"batch": self.f.batch.id, "recipient": "Client A", "output_path": "s3://bucket/batch-1"}
        refused = self.pm.post(self.f.url("deliveries/"), payload, format="json")
        self.assertEqual(refused.status_code, 400)
        Job.objects.filter(pk=job.pk).update(status=JobStatus.APPROVED)
        # Thiếu người nhận / đường dẫn đầu ra → 400
        missing = self.pm.post(self.f.url("deliveries/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(missing.status_code, 400)
        ok = self.pm.post(self.f.url("deliveries/"), payload, format="json")
        self.assertEqual(ok.status_code, 201, ok.data)
        self.assertEqual(ok.data["recipient"], "Client A")
        self.assertEqual(ok.data["output_path"], "s3://bucket/batch-1")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.DELIVERED)

        # Cập nhật ghi chú / phản hồi khách hàng / đường dẫn bàn giao
        bad_patch = self.pm.patch(self.f.url(f"deliveries/{ok.data['id']}/"), {"recipient": "   "}, format="json")
        self.assertEqual(bad_patch.status_code, 400)
        patched = self.pm.patch(
            self.f.url(f"deliveries/{ok.data['id']}/"),
            {"client_feedback": "OK", "note": "Đã giao đầy đủ"},
            format="json",
        )
        self.assertEqual(patched.status_code, 200, patched.data)
        self.assertEqual(patched.data["client_feedback"], "OK")
        self.assertTrue(ActivityLog.objects.filter(project=self.f.project, action="delivery.update").exists())

    def test_overview_marks_undefined_kpis(self):
        self.f.job(status=JobStatus.APPROVED)
        data = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(data["counts"]["jobs"], 1)
        self.assertEqual(data["metrics"]["estimated_completion"]["status"], "pending_definition")
        self.assertIsNone(data["metrics"]["estimated_completion"]["value"])
        self.assertEqual(data["metrics"]["quality_cl"]["status"], "pending_definition")
        self.assertIsNone(data["metrics"]["quality_cl"]["value"])
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("overview/")).status_code, 403)

    def test_delivery_candidates_distinct_count_with_multiple_audits(self):
        self.f.job(status=JobStatus.APPROVED)
        self.f.job(status=JobStatus.APPROVED)
        for seed in (1, 2):
            Audit.objects.create(
                project=self.f.project,
                batch=self.f.batch,
                status=Audit.Status.COMPLETED,
                method=SamplingMethod.RANDOM,
                sampling_rate=50,
                seed=seed,
                eligible_count=2,
            )
        rows = self.pm.get(self.f.url("deliveries/candidates/")).data
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["job_count"], 2)
        self.assertEqual(rows[0]["approved_count"], 2)
        self.assertEqual(rows[0]["open_audits"], 0)
        self.assertTrue(rows[0]["ready"])

        # Khóa batch → không còn ready và bị chặn tạo Delivery
        self.pm.post(self.f.url(f"batches/{self.f.batch.id}/lock/"))
        locked_rows = self.pm.get(self.f.url("deliveries/candidates/")).data
        self.assertFalse(locked_rows[0]["ready"])
        blocked_del = self.pm.post(
            self.f.url("deliveries/"),
            {"batch": self.f.batch.id, "recipient": "Client", "output_path": "s3://out"},
            format="json",
        )
        self.assertEqual(blocked_del.status_code, 400)

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
        return [
            {"user": {"id": self.owner}, "role": "owner", "is_active": True},
            {"user": {"id": 77}, "role": "worker", "is_active": True},
        ]

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
            {
                "id": 101,
                "type": "annotation",
                "stage": "annotation",
                "state": "in progress",
                "start_frame": 0,
                "stop_frame": 9,
                "assignee": {"id": 77},
            },
            {
                "id": 102,
                "type": "annotation",
                "stage": "validation",
                "state": "completed",
                "start_frame": 10,
                "stop_frame": 19,
                "assignee": None,
            },
            {
                "id": 103,
                "type": "ground_truth",
                "stage": "annotation",
                "state": "new",
                "start_frame": 0,
                "stop_frame": 3,
            },
        ])
        sync.sync_organizations(client=client)
        org = Project.objects.get(cvat_org_id=7)
        dataset = Dataset.objects.get(cvat_project_id=900)
        task = dataset.batches.get()
        self.assertEqual((dataset.project, task.cvat_task_id, task.name), (org, 5, "Front cam 01"))
        j101 = Job.objects.get(cvat_job_id=101)
        self.assertEqual(
            (j101.status, j101.annotator, j101.frame_count, j101.batch),
            (JobStatus.ANNOTATING, self.f.ann1, 10, task),
        )
        j102 = Job.objects.get(cvat_job_id=102)
        self.assertEqual((j102.status, j102.cvat_start_frame), (JobStatus.QC1_PASSED, 10))
        self.assertEqual(j102.audit_samples.count(), 0)  # CVAT không tự vượt bước confirm-qc2
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
        approved_job = self.f.job(status=JobStatus.APPROVED, cvat_job_id=201)
        active_job = self.f.job(status=JobStatus.ANNOTATING, cvat_job_id=202)
        sync.sync_organization(
            self.f.project,
            actor=self.f.pm,
            client=FakeCvat(
                [
                    {"id": 201, "stage": "annotation", "state": "new"},
                    {"id": 202, "stage": "annotation", "state": "in progress"},
                ]
            ),
            count_objects=True,
        )
        approved_job.refresh_from_db()
        active_job.refresh_from_db()
        # Sau QC1 (APPROVED): đồng bộ CVAT không ghi đè status hay object_count và không cộng DailyOutputRecord
        self.assertEqual((approved_job.status, approved_job.object_count), (JobStatus.APPROVED, 0))
        self.assertFalse(DailyOutputRecord.objects.filter(job=approved_job).exists())
        # Job còn trong SYNCABLE_STATUSES vẫn được cập nhật object_count từ CVAT
        self.assertEqual((active_job.status, active_job.object_count), (JobStatus.ANNOTATING, 7))

    def test_cvat_rejection_increments_rework_round(self):
        self._linked_fixture()
        job = self.f.job(status=JobStatus.QC1_REVIEWING, cvat_job_id=301)
        sync.sync_organization(
            self.f.project,
            actor=self.f.pm,
            client=FakeCvat([{"id": 301, "stage": "validation", "state": "rejected"}]),
        )
        job.refresh_from_db()
        self.assertEqual((job.status, job.rework_round), (JobStatus.REWORK, 1))


class MemberRolesTests(TestCase):
    def setUp(self):
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
        other = Project.objects.create(name="Other")
        outsider = make_user("outsider", "annotator", project=other)
        self.assertEqual(self._add(self.pm, outsider, "qc1").status_code, 404)


class BatchTeamTests(TestCase):
    def setUp(self):
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
        response = self.pm.patch(
            self.f.url(f"batches/{self.f.batch.id}/"), {"team": self.foreign_team.id}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_deleting_team_unassigns_batch(self):
        self.f.batch.team_id = self.team.id
        self.f.batch.save()
        self.team.delete()
        self.f.batch.refresh_from_db()
        self.assertIsNone(self.f.batch.team)


class ProjectCreateAndBatchConfirmQc2Tests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.team = Team.objects.create(project=self.f.project, name="Team Alpha")
        self.f.batch.team_id = self.team.id
        self.f.batch.save()
        self.pm_client = self.f.client(self.f.pm)
        self.qc1_client = self.f.client(self.f.qc1)
        self.ann_client = self.f.client(self.f.ann1)

    def test_pm_creates_and_updates_project_with_validation_while_non_pm_forbidden(self):
        created = self.pm_client.post(
            reverse("project-list"),
            {
                "name": "Project C",
                "description": "Created by PM",
                "pm_ids": [self.f.pm.id],
                "escalation_policy": "warn_only",
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual([u["id"] for u in created.data["project_managers"]], [self.f.pm.id])
        self.assertEqual(created.data["escalation_policy"], "warn_only")

        # Chặn max_rework_rounds = 0 và chặn pm_ids = [] khi cập nhật
        self.assertEqual(
            self.pm_client.post(
                reverse("project-list"), {"name": "Bad", "max_rework_rounds": 0}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.pm_client.patch(
                reverse("project-detail", args=[self.f.project.id]), {"pm_ids": []}, format="json"
            ).status_code,
            400,
        )

        # Non-PM không được tạo hoặc sửa organization
        self.assertEqual(
            self.ann_client.post(reverse("project-list"), {"name": "Illegal"}, format="json").status_code, 403
        )
        self.assertEqual(
            self.qc1_client.post(reverse("project-list"), {"name": "Illegal"}, format="json").status_code, 403
        )
        self.assertEqual(
            self.ann_client.patch(
                reverse("project-detail", args=[self.f.project.id]), {"name": "Nope"}, format="json"
            ).status_code,
            403,
        )

    def test_pm_confirms_batch_to_qc2_only_when_100_percent_passed_and_unlocked(self):
        j1 = self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann1, frame_count=10)
        j2 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2, frame_count=10)

        # QC1 không có quyền confirm_qc2
        self.assertEqual(
            self.qc1_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code,
            403,
        )
        # Còn j2 chưa đạt QC1 → từ chối
        early = self.pm_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        self.assertEqual(early.status_code, 400)

        # Đạt QC1 100% nhưng có job khoá → từ chối
        Job.objects.filter(pk=j2.pk).update(status=JobStatus.QC1_PASSED, is_locked=True)
        locked_resp = self.pm_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        self.assertEqual(locked_resp.status_code, 400)

        Job.objects.filter(pk=j2.pk).update(is_locked=False)
        pinned_ready = UserNotification.objects.create(
            recipient=self.f.pm,
            project=self.f.project,
            category=UserNotification.Category.REVIEW_NEEDED,
            title=f"Task {self.f.batch.name} sẵn sàng xác nhận chuyển QC2",
            is_pinned_pending=True,
        )

        with patch("projects.views.schedule_assignee_push") as mock_push:
            ok = self.pm_client.post(
                self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {"note": "xong"}, format="json"
            )
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(
            set(Job.objects.filter(pk__in=[j1.pk, j2.pk]).values_list("status", flat=True)),
            {JobStatus.PENDING_QC2},
        )
        self.assertEqual(AuditSample.objects.filter(job__in=[j1, j2], result=AuditSample.Result.PENDING).count(), 2)
        pinned_ready.refresh_from_db()
        self.assertFalse(pinned_ready.is_pinned_pending)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.f.qc2, category=UserNotification.Category.REVIEW_NEEDED
            ).exists()
        )
        mock_push.assert_called_once_with(sorted([j1.id, j2.id]))

    def test_confirm_qc2_rejects_empty_locked_batch_dataset_repeat_and_enforces_isolation(self):
        empty_batch = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="Empty Batch")
        self.assertEqual(
            self.pm_client.post(self.f.url(f"batches/{empty_batch.id}/confirm-qc2/"), {}, format="json").status_code,
            400,
        )

        j = self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann1, frame_count=10)

        self.f.batch.status = DataStatus.LOCKED
        self.f.batch.save(update_fields=["status"])
        self.assertEqual(
            self.pm_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code,
            400,
        )
        self.f.batch.status = DataStatus.ACTIVE
        self.f.batch.save(update_fields=["status"])

        self.f.dataset.status = DataStatus.LOCKED
        self.f.dataset.save(update_fields=["status"])
        self.assertEqual(
            self.pm_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code,
            400,
        )
        self.f.dataset.status = DataStatus.ACTIVE
        self.f.dataset.save(update_fields=["status"])

        qc2_client = self.f.client(self.f.qc2)
        outsider_client = self.f.client(make_user("outsider_qc2_confirm"))
        self.assertEqual(
            qc2_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code,
            403,
        )
        self.assertEqual(
            self.ann_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code,
            403,
        )
        self.assertEqual(
            outsider_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code,
            404,
        )

        with patch("projects.views.schedule_assignee_push"):
            ok = self.pm_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)

        repeat = self.pm_client.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        self.assertEqual(repeat.status_code, 400)
        self.assertEqual(AuditSample.objects.filter(job=j).count(), 1)

    def test_batch_deadline_activity_filters_and_notifications_use_rfc3339_utc(self):
        # Batch deadline yêu cầu RFC 3339 kèm múi giờ và trả về UTC 'Z'
        bad_batch = self.pm_client.patch(
            self.f.url(f"batches/{self.f.batch.id}/"),
            {"deadline": "2026-11-26T15:30:00"},
            format="json",
        )
        self.assertEqual(bad_batch.status_code, 400)

        ok_batch = self.pm_client.patch(
            self.f.url(f"batches/{self.f.batch.id}/"),
            {"deadline": "2026-11-26T15:30:00+07:00"},
            format="json",
        )
        self.assertEqual(ok_batch.status_code, 200, ok_batch.data)
        self.assertEqual(ok_batch.data["deadline"], "2026-11-26T08:30:00Z")

        # ActivityLog filter trả 400 khi date_from/date_to sai định dạng hoặc ngược khoảng
        self.assertEqual(self.pm_client.get(self.f.url("activity/?date_from=26/11/2026")).status_code, 400)
        self.assertEqual(
            self.pm_client.get(self.f.url("activity/?date_from=2026-11-28&date_to=2026-11-26")).status_code,
            400,
        )
        ok_logs = self.pm_client.get(self.f.url("activity/?date_from=2026-01-01&date_to=2099-12-31"))
        self.assertEqual(ok_logs.status_code, 200, ok_logs.data)

        # Notifications API trả created_at dạng RFC 3339 UTC kết thúc bằng 'Z'
        self.pm_client.post(self.f.url("announcements/"), {"content": "Kiểm tra UTC"}, format="json")
        notifs = self.pm_client.get(self.f.url("notifications/"))
        self.assertEqual(notifs.status_code, 200, notifs.data)
        self.assertTrue(notifs.data["items"])
        for item in notifs.data["items"]:
            self.assertTrue(item["created_at"].endswith("Z"), item["created_at"])


class MemberAccountTests(TestCase):
    """PM tạo tài khoản thành viên, xem / cấp lại mật khẩu tạm; người dùng tự đổi mật khẩu."""

    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)

    def _create(self, client=None, **data):
        payload = {"full_name": "Nguyễn Văn Đức", "roles": ["annotator"], **data}
        return (client or self.pm).post(self.f.url("members/"), payload, format="json")

    def test_pm_creates_account_with_generated_username_and_password(self):
        response = self._create(roles=["annotator", "qc1"])
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["username"], "nguyenvanduc")
        user = User.objects.get(username="nguyenvanduc")
        self.assertTrue(user.check_password(response.data["password"]))
        self.assertEqual(sorted(user.get_project_roles(self.f.project)), ["annotator", "qc1"])
        self.assertEqual(self._create().data["username"], "nguyenvanduc2")

    def test_only_manage_team_can_create(self):
        self.assertEqual(self._create(client=self.f.client(self.f.ann1)).status_code, 403)

    def test_cannot_put_member_in_team_of_other_project(self):
        other = Project.objects.create(name="Khác")
        team = Team.objects.create(project=other, name="T")
        self.assertEqual(self._create(team=team.id).status_code, 400)

    def test_credential_visible_until_user_changes_password(self):
        created = self._create().data
        user_id = created["user"]["id"]
        cred = self.pm.get(self.f.url(f"members/{user_id}/credential/")).data
        self.assertEqual((cred["status"], cred["password"]), ("initial", created["password"]))
        self.assertTrue(ActivityLog.objects.filter(action="member.view_password").exists())
        listed = next(m for m in self.pm.get(self.f.url("members/")).data if m["user"]["id"] == user_id)
        self.assertTrue(listed["has_initial_password"])
        self.assertFalse(listed["cvat_linked"])

        me = self.f.client(User.objects.get(pk=user_id))
        response = me.post(
            "/api/auth/me/password/",
            {"current_password": created["password"], "new_password": "Moi-Mat-Khau-2026"},
            format="json",
        )
        self.assertEqual(response.status_code, 204, response.data)
        cred = self.pm.get(self.f.url(f"members/{user_id}/credential/")).data
        self.assertEqual((cred["status"], cred["password"]), ("changed", None))

    def test_change_password_requires_current_password(self):
        response = self.f.client(self.f.ann1).post(
            "/api/auth/me/password/",
            {"current_password": "sai", "new_password": "Moi-Mat-Khau-2026"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_reset_password(self):
        response = self.pm.post(self.f.url(f"members/{self.f.ann1.id}/reset-password/"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.f.ann1.refresh_from_db()
        self.assertTrue(self.f.ann1.check_password(response.data["password"]))
        self.assertEqual(self.pm.post(self.f.url(f"members/{self.f.pm.id}/reset-password/")).status_code, 400)

    def test_credential_and_reset_block_superuser_and_multi_org_targets(self):
        created = self._create().data
        uid = created["user"]["id"]
        cred_ok = self.pm.get(self.f.url(f"members/{uid}/credential/"))
        self.assertEqual(cred_ok.status_code, 200)
        self.assertEqual(cred_ok["Cache-Control"], "no-store")

        superuser = User.objects.create_superuser("su_target", "su@example.com", "pw")
        RoleAssignment.objects.create(user=superuser, role=Role.ANNOTATOR, project=self.f.project)
        for method, path in (
            ("get", f"members/{superuser.id}/credential/"),
            ("post", f"members/{superuser.id}/reset-password/"),
        ):
            self.assertEqual(getattr(self.pm, method)(self.f.url(path)).status_code, 400)

        other_project = Project.objects.create(name="Org Khác")
        RoleAssignment.objects.create(user=self.f.ann1, role=Role.ANNOTATOR, project=other_project)
        for method, path in (
            ("get", f"members/{self.f.ann1.id}/credential/"),
            ("post", f"members/{self.f.ann1.id}/reset-password/"),
        ):
            self.assertEqual(getattr(self.pm, method)(self.f.url(path)).status_code, 400)


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
        self.assertEqual(self._remove(self.f.ann2, "annotator").status_code, 400)
        self.assertEqual(self._remove(self.f.pm, "qc2").status_code, 400)
        self.assertEqual(self._remove(self.f.pm, "project_manager").status_code, 400)

    def test_cannot_remove_role_while_holding_its_work(self):
        self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)
        RoleAssignment.objects.create(user=self.f.qc1, role=Role.ANNOTATOR, project=self.f.project)
        self.assertEqual(self._remove(self.f.qc1, "qc1").status_code, 400)

    def test_only_manage_team_can_remove(self):
        self.assertEqual(self._remove(self.f.ann1, "qc1", client=self.f.client(self.f.qc2)).status_code, 403)


class DeliveryNotificationsAndHardeningTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.ann1 = self.f.client(self.f.ann1)

    def test_delivery_candidates_and_deliveries_include_dataset_name_and_block_locked_jobs(self):
        job = self.f.job(status=JobStatus.APPROVED, is_locked=True)
        payload = {"batch": self.f.batch.id, "recipient": "Client A", "output_path": "s3://bucket/d1"}

        candidates = self.pm.get(self.f.url("deliveries/candidates/"))
        self.assertEqual(candidates.status_code, 200, candidates.data)
        self.assertEqual(candidates.data[0]["dataset_name"], "D1")
        self.assertFalse(candidates.data[0]["ready"])

        blocked = self.pm.post(self.f.url("deliveries/"), payload, format="json")
        self.assertEqual(blocked.status_code, 400)

        Job.objects.filter(pk=job.pk).update(is_locked=False)
        candidates = self.pm.get(self.f.url("deliveries/candidates/")).data
        self.assertTrue(candidates[0]["ready"])

        created = self.pm.post(self.f.url("deliveries/"), payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["dataset_name"], "D1")

        listed = self.pm.get(self.f.url("deliveries/")).data
        self.assertEqual(listed[0]["dataset_name"], "D1")

        duplicate = self.pm.post(self.f.url("deliveries/"), payload, format="json")
        self.assertEqual(duplicate.status_code, 400)

    def test_notifications_announcement_read_clears_unread_count_and_preserves_pinned(self):
        ann_target = Announcement.objects.create(
            project=self.f.project, sender=self.f.pm, target_roles=[Role.ANNOTATOR], content="Cho annotator"
        )
        for idx in range(25):
            Announcement.objects.create(
                project=self.f.project, sender=self.f.pm, target_roles=[Role.QC1], content=f"QC1 #{idx}"
            )

        feed = self.ann1.get(self.f.url("notifications/"))
        self.assertEqual(feed.status_code, 200, feed.data)
        ann_items = [item for item in feed.data["items"] if item["source"] == "announcement"]
        self.assertEqual([item["id"] for item in ann_items], [f"ann-{ann_target.id}"])
        self.assertEqual(feed.data["unread_count"], 1)

        mark_one = self.ann1.post(
            self.f.url("notifications/mark-read/"), {"notification_id": f"ann-{ann_target.id}"}, format="json"
        )
        self.assertEqual(mark_one.status_code, 200, mark_one.data)
        self.assertEqual(mark_one.data["updated"], 1)
        self.assertTrue(AnnouncementRead.objects.filter(announcement=ann_target, user=self.f.ann1).exists())
        self.assertEqual(self.ann1.get(self.f.url("notifications/")).data["unread_count"], 0)

        ann2 = Announcement.objects.create(
            project=self.f.project, sender=self.f.pm, target_roles=[], content="Chung"
        )
        normal = UserNotification.objects.create(
            recipient=self.f.ann1, project=self.f.project, title="Thường", is_pinned_pending=False
        )
        pinned = UserNotification.objects.create(
            recipient=self.f.ann1, project=self.f.project, title="Đang treo", is_pinned_pending=True
        )
        self.assertEqual(self.ann1.get(self.f.url("notifications/")).data["unread_count"], 3)

        mark_all = self.ann1.post(self.f.url("notifications/mark-read/"), {}, format="json")
        self.assertEqual(mark_all.status_code, 200, mark_all.data)
        normal.refresh_from_db()
        pinned.refresh_from_db()
        self.assertTrue(normal.is_read)
        self.assertFalse(pinned.is_read)
        self.assertTrue(AnnouncementRead.objects.filter(announcement=ann2, user=self.f.ann1).exists())
        self.assertEqual(self.ann1.get(self.f.url("notifications/")).data["unread_count"], 1)

        self.f.job(
            status=JobStatus.ANNOTATING,
            annotator=self.f.ann1,
            deadline=timezone.now() + timedelta(hours=3),
        )
        deadline_items = [
            i for i in self.ann1.get(self.f.url("notifications/")).data["items"] if i["source"] == "deadline"
        ]
        self.assertTrue(deadline_items)
        self.assertNotIn("DB06", deadline_items[0]["body"])

        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1)
        n_with_job = UserNotification.objects.create(
            recipient=self.f.pm, project=self.f.project, job=job, title="PM job"
        )
        n_no_job = UserNotification.objects.create(
            recipient=self.f.pm, project=self.f.project, title="PM general"
        )
        pm_items = {i["id"]: i for i in self.pm.get(self.f.url("notifications/")).data["items"]}
        self.assertEqual(pm_items[f"sys-{n_with_job.id}"]["action_url"], f"/projects/{self.f.project.id}/jobs")
        self.assertEqual(pm_items[f"sys-{n_no_job.id}"]["action_url"], f"/projects/{self.f.project.id}")

    def test_mark_notifications_read_invalid_id_returns_400(self):
        for bad in ["abc", "sys-abc", "ann-abc", "due-1", "", True, -1, 9_999_999_999]:
            res = self.ann1.post(
                self.f.url("notifications/mark-read/"), {"notification_id": bad}, format="json"
            )
            self.assertEqual(res.status_code, 400, f"Expected 400 for {bad!r}, got {res.status_code}")

    def test_bad_int_query_params_batch_list_member_password_and_filtered_lock(self):
        self.assertEqual(self.pm.get(self.f.url("batches/?dataset=abc")).status_code, 400)
        self.assertEqual(self.pm.get(self.f.url("batches/?dataset=999999999999")).status_code, 400)
        self.assertEqual(self.pm.get(self.f.url("activity/?actor=abc")).status_code, 400)

        self.assertEqual(self.ann1.get(self.f.url("batches/")).status_code, 200)
        self.assertEqual(
            self.ann1.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"deadline": None}, format="json").status_code,
            403,
        )

        created = self.pm.post(
            self.f.url("members/"), {"full_name": "Tran Test", "roles": ["annotator"]}, format="json"
        ).data
        ann_members = {m["user"]["id"]: m for m in self.ann1.get(self.f.url("members/")).data}
        self.assertFalse(ann_members[created["user"]["id"]]["has_initial_password"])

        ds_lock = self.pm.post(self.f.url(f"datasets/{self.f.dataset.id}/lock/?status=active"))
        self.assertEqual(ds_lock.status_code, 200, ds_lock.data)
        self.assertEqual(ds_lock.data["status"], "locked")

        batch_lock = self.pm.post(self.f.url(f"batches/{self.f.batch.id}/lock/?status=active"))
        self.assertEqual(batch_lock.status_code, 200, batch_lock.data)
        self.assertEqual(batch_lock.data["status"], "locked")


class Phase1HardeningAndP2Tests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.qc2 = self.f.client(self.f.qc2)

    def test_superuser_visibility_and_capabilities_consistent_without_polluting_membership(self):
        su = User.objects.create_superuser("global_su", "su@example.com", "pw")
        su_client = self.f.client(su)

        listed = su_client.get(reverse("project-list"))
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([p["id"] for p in listed.data], [self.f.project.id])
        self.assertEqual(listed.data[0]["my_roles"], [Role.PROJECT_MANAGER, Role.QC2])

        detail = su_client.get(reverse("project-detail", args=[self.f.project.id]))
        self.assertEqual(detail.status_code, 200)
        # Không đếm khống superuser vào member_total của org
        self.assertEqual(detail.data["member_total"], 5)
        self.assertEqual(su.get_project_roles(self.f.project), set())

        me = su_client.get(reverse("me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(len(me.data["projects"]), 1)
        self.assertEqual(me.data["projects"][0]["direct_roles"], [])
        self.assertIn(Role.PROJECT_MANAGER, me.data["projects"][0]["roles"])

        self.assertEqual(su_client.get(self.f.url("settings/")).status_code, 200)
        self.assertEqual(su_client.get(self.f.url(f"members/{self.f.ann1.id}/credential/")).status_code, 200)

    def test_delivery_put_with_and_without_batch_succeeds_and_candidates_clarify_fields(self):
        now = timezone.now()
        self.f.batch.deadline = now - timedelta(hours=2)
        self.f.batch.save(update_fields=["deadline"])
        self.f.job(status=JobStatus.APPROVED)
        Audit.objects.create(
            project=self.f.project,
            batch=self.f.batch,
            status=Audit.Status.IN_PROGRESS,
            method=SamplingMethod.RANDOM,
            sampling_rate=50,
            seed=1,
            eligible_count=1,
        )

        cand = self.pm.get(self.f.url("deliveries/candidates/"))
        self.assertEqual(cand.status_code, 200, cand.data)
        row = cand.data[0]
        self.assertEqual(row["pending_qc2_samples"], 0)
        self.assertEqual(row["in_progress_audits"], 1)
        self.assertEqual(row["open_audits"], 0)
        self.assertTrue(row["is_overdue"])
        self.assertEqual(row["due_state"], "overdue")
        self.assertTrue(row["ready"])

        created = self.pm.post(
            self.f.url("deliveries/"),
            {"batch": self.f.batch.id, "recipient": "Client A", "output_path": "s3://out/a"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertFalse(created.data["is_on_time"])
        delivery_id = created.data["id"]

        # PUT không gửi batch → 200
        put_no_batch = self.pm.put(
            self.f.url(f"deliveries/{delivery_id}/"),
            {"recipient": "Client B", "output_path": "s3://out/b", "note": "n1", "client_feedback": "good"},
            format="json",
        )
        self.assertEqual(put_no_batch.status_code, 200, put_no_batch.data)
        self.assertEqual(put_no_batch.data["recipient"], "Client B")
        self.assertEqual(put_no_batch.data["batch"], self.f.batch.id)

        # PUT có kèm batch (kể cả batch khác) → batch chỉ đọc, không lỗi 400 và không đổi batch
        other_batch = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="Other")
        put_with_batch = self.pm.put(
            self.f.url(f"deliveries/{delivery_id}/"),
            {"batch": other_batch.id, "recipient": "Client C", "output_path": "s3://out/c"},
            format="json",
        )
        self.assertEqual(put_with_batch.status_code, 200, put_with_batch.data)
        self.assertEqual(put_with_batch.data["batch"], self.f.batch.id)
        self.assertEqual(put_with_batch.data["recipient"], "Client C")

    def test_confirm_qc2_notifications_unpin_on_audit_finish_and_delivery(self):
        j1 = self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann1, frame_count=10)
        j2 = self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann2, frame_count=10)
        self.assertEqual(
            self.pm.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code,
            200,
        )
        # Đổi tên batch để kiểm tra unpin dựa trên FK batch không phụ thuộc tên
        self.f.batch.name = "Renamed Task"
        self.f.batch.save(update_fields=["name"])
        pinned = UserNotification.objects.filter(
            project=self.f.project,
            batch=self.f.batch,
            category=UserNotification.Category.REVIEW_NEEDED,
            is_pinned_pending=True,
        )
        self.assertTrue(pinned.exists())

        s1 = AuditSample.objects.get(job=j1, result=AuditSample.Result.PENDING)
        s2 = AuditSample.objects.get(job=j2, result=AuditSample.Result.PENDING)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{s1.id}/pass/"), {}, format="json").status_code, 200)
        # Còn s2 pending → vẫn ghim
        self.assertTrue(pinned.exists())
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{s2.id}/pass/"), {}, format="json").status_code, 200)
        # Hết mẫu pending & hết PENDING_QC2 → tự gỡ ghim
        self.assertFalse(pinned.exists())

        # Trường hợp còn thông báo ghim trên batch khác khi bàn giao → bàn giao cũng tự gỡ ghim
        b2 = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="B2")
        self.f.job(batch=b2, status=JobStatus.APPROVED)
        n_b2 = UserNotification.objects.create(
            recipient=self.f.qc2,
            project=self.f.project,
            batch=b2,
            category=UserNotification.Category.REVIEW_NEEDED,
            title="Task B2 đã được xác nhận chuyển QC2",
            is_pinned_pending=True,
        )
        self.assertEqual(
            self.pm.post(
                self.f.url("deliveries/"),
                {"batch": b2.id, "recipient": "C", "output_path": "s3://b2"},
                format="json",
            ).status_code,
            201,
        )
        n_b2.refresh_from_db()
        self.assertFalse(n_b2.is_pinned_pending)

    def test_members_post_sets_no_store_and_handles_integrity_errors_cleanly(self):
        res = self.pm.post(
            self.f.url("members/"),
            {"full_name": "Lê Thị Mai", "username": "lemai01", "roles": ["annotator"]},
            format="json",
        )
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res["Cache-Control"], "no-store")

        # Giả lập đụng độ username ở lớp DB khi race condition xảy ra
        with patch.object(User, "save", side_effect=IntegrityError("duplicate username")):
            dup = self.pm.post(
                self.f.url("members/"),
                {"full_name": "Lê Thị Mai", "username": "lemai_race", "roles": ["annotator"]},
                format="json",
            )
            self.assertEqual(dup.status_code, 400)

        # Auto-generated username thử lại qua savepoint khi đụng độ lần đầu
        real_save = User.save
        calls = {"n": 0}

        def save_fail_once(user_self, *args, **kwargs):
            if calls["n"] == 0:
                calls["n"] += 1
                raise IntegrityError("race")
            return real_save(user_self, *args, **kwargs)

        with patch.object(User, "save", autospec=True, side_effect=save_fail_once):
            retried = self.pm.post(
                self.f.url("members/"),
                {"full_name": "Phạm Văn An", "roles": ["annotator"]},
                format="json",
            )
            self.assertEqual(retried.status_code, 201, retried.data)
            self.assertEqual(retried["Cache-Control"], "no-store")

        # _sync_pms IntegrityError trả 400 thay vì 500
        with patch.object(RoleAssignment.objects, "get_or_create", side_effect=IntegrityError("fk")):
            other_pm = make_user("other_pm_err")
            err = self.pm.patch(
                reverse("project-detail", args=[self.f.project.id]),
                {"pm_ids": [self.f.pm.id, other_pm.id]},
                format="json",
            )
            self.assertEqual(err.status_code, 400)

    def test_locks_acquired_for_dataset_batch_settings_delivery_and_reset_password(self):
        with CaptureQueriesContext(connection) as q_ds:
            self.assertEqual(self.pm.post(self.f.url(f"datasets/{self.f.dataset.id}/lock/")).status_code, 200)
        self.assertTrue(any("projects_dataset" in q["sql"] and "FOR UPDATE" in q["sql"] for q in q_ds))
        self.assertEqual(self.pm.post(self.f.url(f"datasets/{self.f.dataset.id}/unlock/")).status_code, 200)

        self.f.job(status=JobStatus.ANNOTATING)
        with CaptureQueriesContext(connection) as q_batch_upd:
            self.assertEqual(
                self.pm.patch(
                    self.f.url(f"batches/{self.f.batch.id}/"),
                    {"deadline": "2026-12-05T00:00:00Z"},
                    format="json",
                ).status_code,
                200,
            )
        for_upd_batch = [q["sql"] for q in q_batch_upd if "FOR UPDATE" in q["sql"]]
        self.assertTrue(any("projects_batch" in s for s in for_upd_batch))
        self.assertTrue(any("jobs_job" in s for s in for_upd_batch))

        with CaptureQueriesContext(connection) as q_batch_lock:
            self.assertEqual(self.pm.post(self.f.url(f"batches/{self.f.batch.id}/lock/")).status_code, 200)
        self.assertTrue(any("projects_batch" in q["sql"] and "FOR UPDATE" in q["sql"] for q in q_batch_lock))
        self.assertEqual(self.pm.post(self.f.url(f"batches/{self.f.batch.id}/unlock/")).status_code, 200)

        with CaptureQueriesContext(connection) as q_settings:
            self.assertEqual(
                self.pm.patch(self.f.url("settings/"), {"sampling_rate": 25}, format="json").status_code,
                200,
            )
        self.assertTrue(any("projects_project" in q["sql"] and "FOR UPDATE" in q["sql"] for q in q_settings))

        with CaptureQueriesContext(connection) as q_reset:
            self.assertEqual(self.pm.post(self.f.url(f"members/{self.f.ann1.id}/reset-password/")).status_code, 200)
        self.assertTrue(any("accounts_user" in q["sql"] and "FOR UPDATE" in q["sql"] for q in q_reset))

        Job.objects.filter(batch=self.f.batch).update(status=JobStatus.APPROVED)
        with CaptureQueriesContext(connection) as q_del:
            self.assertEqual(
                self.pm.post(
                    self.f.url("deliveries/"),
                    {"batch": self.f.batch.id, "recipient": "Client", "output_path": "s3://p"},
                    format="json",
                ).status_code,
                201,
            )
        del_locks = [q["sql"] for q in q_del if "FOR UPDATE" in q["sql"]]
        self.assertGreaterEqual(len(del_locks), 3)
        self.assertIn("projects_dataset", del_locks[0])
        self.assertIn("projects_batch", del_locks[1])
        self.assertIn("jobs_job", del_locks[2])

    def test_project_serializer_id_oracles_uniform_for_foreign_and_missing_ids(self):
        other = ProjectFixture(name="proj_oracle")
        other_team = Team.objects.create(project=other.project, name="Other Team")
        foreign_team_id = other_team.id
        missing_team_id = foreign_team_id + 99999
        foreign_batch_id = other.batch.id
        missing_batch_id = foreign_batch_id + 99999

        # CreateMemberSerializer.team
        r_f_mem = self.pm.post(
            self.f.url("members/"),
            {"full_name": "Oracle A", "roles": [Role.ANNOTATOR], "team": foreign_team_id},
            format="json",
        )
        r_m_mem = self.pm.post(
            self.f.url("members/"),
            {"full_name": "Oracle B", "roles": [Role.ANNOTATOR], "team": missing_team_id},
            format="json",
        )
        self.assertEqual(r_f_mem.status_code, 400)
        self.assertEqual(r_m_mem.status_code, 400)
        self.assertEqual(r_f_mem.data, r_m_mem.data)

        # BatchSerializer.team
        r_f_batch = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": foreign_team_id}, format="json")
        r_m_batch = self.pm.patch(self.f.url(f"batches/{self.f.batch.id}/"), {"team": missing_team_id}, format="json")
        self.assertEqual(r_f_batch.status_code, 400)
        self.assertEqual(r_m_batch.status_code, 400)
        self.assertEqual(r_f_batch.data, r_m_batch.data)

        # AnnouncementSerializer.target_team
        r_f_ann = self.pm.post(
            self.f.url("announcements/"),
            {"content": "Thong bao", "target_team": foreign_team_id},
            format="json",
        )
        r_m_ann = self.pm.post(
            self.f.url("announcements/"),
            {"content": "Thong bao", "target_team": missing_team_id},
            format="json",
        )
        self.assertEqual(r_f_ann.status_code, 400)
        self.assertEqual(r_m_ann.status_code, 400)
        self.assertEqual(r_f_ann.data, r_m_ann.data)

        # DeliverySerializer.batch
        r_f_del = self.pm.post(
            self.f.url("deliveries/"),
            {"batch": foreign_batch_id, "recipient": "Client", "output_path": "s3://out"},
            format="json",
        )
        r_m_del = self.pm.post(
            self.f.url("deliveries/"),
            {"batch": missing_batch_id, "recipient": "Client", "output_path": "s3://out"},
            format="json",
        )
        self.assertEqual(r_f_del.status_code, 400)
        self.assertEqual(r_m_del.status_code, 400)
        self.assertEqual(r_f_del.data, r_m_del.data)
