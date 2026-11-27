from unittest import mock

from accounts.models import Role, RoleAssignment, User
from accounts.testing import ProjectFixture
from django.db import connection
from django.test import TestCase
from jobs.models import Job, JobStatus
from projects.models import ActivityLog, DataStatus, Project
from quality.models import Audit, AuditSample, ErrorCategory

from . import sync
from .assignee import jobs_held_by, push_assignees
from .client import CvatError
from .models import CvatAccount


class FakeCvatClient:
    """Thay CvatClient thật: ghi lại các lần đặt assignee, trả user CVAT theo token."""

    users = {"tok-ann1": {"id": 11, "username": "cvat_ann1"}, "tok-other": {"id": 99, "username": "cvat_other"}}
    pushed = []

    def __init__(self, token=None, **kwargs):
        self.token = token

    def get_self(self):
        if self.token not in self.users:
            raise CvatError("CVAT từ chối xác thực. Kiểm tra tài khoản/token CVAT.")
        return self.users[self.token]

    def set_job_assignee(self, job_id, cvat_user_id):
        FakeCvatClient.pushed.append((job_id, cvat_user_id))


@mock.patch("cvat_integration.assignee.CvatClient", FakeCvatClient)
@mock.patch("cvat_integration.views.CvatClient", FakeCvatClient)
class CvatLinkTests(TestCase):
    def setUp(self):
        FakeCvatClient.pushed = []
        self.f = ProjectFixture()
        self.client = self.f.client(self.f.ann1)

    def test_link_with_token_stores_only_id_and_username(self):
        response = self.client.post("/api/cvat/link/", {"token": "tok-ann1"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["linked"])
        account = CvatAccount.objects.get(user=self.f.ann1)
        self.assertEqual((account.cvat_user_id, account.cvat_username), (11, "cvat_ann1"))
        self.assertTrue(ActivityLog.objects.filter(action="cvat.link", actor=self.f.ann1).exists())

    def test_invalid_token_is_rejected(self):
        response = self.client.post("/api/cvat/link/", {"token": "sai"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CvatAccount.objects.exists())

    def test_cvat_account_cannot_be_linked_to_two_people(self):
        CvatAccount.objects.create(user=self.f.ann2, cvat_user_id=11, cvat_username="cvat_ann1")
        response = self.client.post("/api/cvat/link/", {"token": "tok-ann1"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_linking_pushes_jobs_assigned_before_link(self):
        """Giao trên VanoHub khi chưa liên kết → liên kết xong thì đẩy assignee sang CVAT."""
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=500)
        response = self.client.post("/api/cvat/link/", {"token": "tok-ann1"}, format="json")
        self.assertEqual(response.data["sync"], {"pushed": 1, "error": None})
        self.assertEqual(FakeCvatClient.pushed, [(500, 11)])
        job.refresh_from_db()
        self.assertEqual(job.cvat_assignee_id, 11)

    def test_unlink_removes_assignee_on_cvat(self):
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="cvat_ann1")
        self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=501, cvat_assignee_id=11)
        response = self.client.delete("/api/cvat/link/")
        self.assertFalse(response.data["linked"])
        self.assertEqual(FakeCvatClient.pushed, [(501, None)])


@mock.patch("cvat_integration.assignee.CvatClient", FakeCvatClient)
class AssigneePushTests(TestCase):
    def setUp(self):
        FakeCvatClient.pushed = []
        self.f = ProjectFixture()
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="a1")
        CvatAccount.objects.create(user=self.f.qc1, cvat_user_id=33, cvat_username="q1")

    def test_holder_follows_status(self):
        annotating = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=1)
        in_qc1 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, cvat_job_id=2)
        approved = self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, cvat_job_id=3)
        result = push_assignees([annotating, in_qc1, approved])
        self.assertEqual(result, {"pushed": 2, "waiting": 0, "warnings": []})
        self.assertEqual(FakeCvatClient.pushed, [(1, 11), (2, 33)])  # job đã duyệt: không động vào

    def test_unlinked_holder_is_waiting_and_old_assignee_removed(self):
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann2, cvat_job_id=4, cvat_assignee_id=11)
        self.assertEqual(push_assignees([job]), {"pushed": 1, "waiting": 1, "warnings": []})
        self.assertEqual(FakeCvatClient.pushed, [(4, None)])

    def test_unchanged_assignee_is_not_pushed_again(self):
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=5, cvat_assignee_id=11)
        self.assertEqual(push_assignees([job])["pushed"], 0)
        self.assertEqual(FakeCvatClient.pushed, [])

    def test_qc2_sample_holder_is_auditor(self):
        CvatAccount.objects.create(user=self.f.qc2, cvat_user_id=22, cvat_username="q2")
        job = self.f.job(status=JobStatus.PENDING_QC2, cvat_job_id=6)
        audit = Audit.objects.create(project=self.f.project, batch=self.f.batch, method="random", sampling_rate=50,
                                     seed=1, eligible_count=1, created_by=self.f.pm)
        AuditSample.objects.create(audit=audit, job=job, auditor=self.f.qc2)
        push_assignees([job])
        self.assertEqual(FakeCvatClient.pushed, [(6, 22)])

    def test_pm_assignment_pushes_after_commit(self):
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2, cvat_job_id=7)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.f.client(self.f.pm).post(self.f.url(f"jobs/{job.id}/assign/"),
                                                     {"annotator": self.f.ann1.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(FakeCvatClient.pushed, [(7, 11)])

    def test_assignment_succeeds_even_if_cvat_is_down(self):
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2, cvat_job_id=8)
        with (
            mock.patch.object(FakeCvatClient, "set_job_assignee", side_effect=CvatError("down")),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.f.client(self.f.pm).post(
                self.f.url(f"jobs/{job.id}/assign/"), {"annotator": self.f.ann1.id}, format="json"
            )
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual((job.annotator, job.cvat_assignee_id), (self.f.ann1, None))


class FakeOrgCvat:
    """CVAT giả có organization: user 11 có email (mời được), user 33 không có email."""

    def __init__(self, members=()):
        self.members = list(members)
        self.invited = []
        self.pushed = []

    def list_memberships(self, org_id):
        return [{"user": {"id": uid}, "is_active": True} for uid in self.members]

    def get_user(self, user_id):
        return {11: {"id": 11, "username": "a1", "email": "a1@example.com"}, 33: {"id": 33, "username": "q1", "email": ""}}[user_id]

    def invite_to_org(self, org_slug, email, role="worker"):
        self.invited.append((org_slug, email, role))

    def set_job_assignee(self, job_id, cvat_user_id):
        self.pushed.append((job_id, cvat_user_id))


class AutoOrgMembershipTests(TestCase):
    """Giao job cho người chưa là thành viên CVAT organization → tự mời (worker) để họ thấy job."""

    def setUp(self):
        self.f = ProjectFixture()
        self.f.project.cvat_org_id, self.f.project.cvat_org_slug = 7, "acme"
        self.f.project.save()
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="a1")
        CvatAccount.objects.create(user=self.f.qc1, cvat_user_id=33, cvat_username="q1")

    def test_non_member_is_invited_once_then_assigned(self):
        client = FakeOrgCvat()
        jobs = [self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=n) for n in (1, 2)]
        result = push_assignees(jobs, client)
        self.assertEqual(client.invited, [("acme", "a1@example.com", "worker")])  # mời một lần cho cả hai job
        self.assertEqual(client.pushed, [(1, 11), (2, 11)])
        self.assertEqual(result["warnings"], [])

    def test_existing_member_is_not_invited(self):
        client = FakeOrgCvat(members=[11])
        push_assignees([self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=3)], client)
        self.assertEqual(client.invited, [])

    def test_user_without_email_still_gets_job_with_warning(self):
        client = FakeOrgCvat()
        result = push_assignees([self.f.job(status=JobStatus.PENDING_QC1, cvat_job_id=4)], client)
        self.assertEqual(client.pushed, [(4, 33)])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("chưa có email", result["warnings"][0])


class _FakeSyncClient:
    """CVAT client giả phục vụ kiểm thử sync workflow & kiểm tra không gọi HTTP trong transaction."""

    def __init__(self, jobs, orgs=None, memberships=None, expected_atomic_depth=None):
        self.jobs = jobs
        self.orgs = orgs or []
        self.memberships = memberships or {}
        self.expected_atomic_depth = expected_atomic_depth
        self.pushed = []
        self.http_calls = []

    def _check_not_in_nested_atomic(self, label):
        self.http_calls.append(label)
        if self.expected_atomic_depth is not None:
            assert len(connection.atomic_blocks) == self.expected_atomic_depth, (
                f"CVAT HTTP call {label} ran inside nested transaction.atomic()"
            )

    def list_organizations(self):
        self._check_not_in_nested_atomic("list_organizations")
        return self.orgs

    def list_memberships(self, org_id):
        self._check_not_in_nested_atomic("list_memberships")
        return self.memberships.get(org_id, [])

    def list_org_projects(self, org_id):
        self._check_not_in_nested_atomic("list_org_projects")
        return [{"id": 900, "name": "Synced Project"}]

    def list_project_tasks(self, project_id):
        self._check_not_in_nested_atomic("list_project_tasks")
        return [{"id": 5, "name": "Synced Task"}]

    def list_task_jobs(self, task_id):
        self._check_not_in_nested_atomic("list_task_jobs")
        return self.jobs

    def count_job_objects(self, job_id):
        self._check_not_in_nested_atomic("count_job_objects")
        return 12

    def set_job_assignee(self, job_id, cvat_user_id):
        self._check_not_in_nested_atomic("set_job_assignee")
        self.pushed.append((job_id, cvat_user_id))


class CvatSyncWorkflowSafetyTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.f.project.cvat_org_id = 7
        self.f.project.cvat_org_slug = "acme"
        self.f.project.save()
        self.f.dataset.cvat_project_id = 900
        self.f.dataset.save()
        self.f.batch.cvat_task_id = 5
        self.f.batch.save()

    def test_rework_job_not_teleported_to_pending_qc2(self):
        """P0: Job bị QC2 reject về REWORK không bị CVAT kéo ngược lên PENDING_QC2."""
        job_val = self.f.job(status=JobStatus.REWORK, rework_round=1, cvat_job_id=401)
        job_acc = self.f.job(status=JobStatus.REWORK, rework_round=1, cvat_job_id=402)
        client = _FakeSyncClient([
            {"id": 401, "stage": "validation", "state": "completed"},
            {"id": 402, "stage": "acceptance", "state": "completed"},
        ])
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        job_val.refresh_from_db()
        job_acc.refresh_from_db()
        self.assertEqual((job_val.status, job_val.rework_round), (JobStatus.REWORK, 1))
        self.assertEqual((job_acc.status, job_acc.rework_round), (JobStatus.REWORK, 1))
        self.assertEqual(job_val.audit_samples.count(), 0)
        self.assertEqual(job_acc.audit_samples.count(), 0)

    def test_pending_qc1_and_qc1_reviewing_not_rolled_back_to_annotating(self):
        """P0: Job đang ở PENDING_QC1/QC1_REVIEWING không bị CVAT kéo lùi về ANNOTATING."""
        j_pending = self.f.job(status=JobStatus.PENDING_QC1, cvat_job_id=411)
        j_reviewing = self.f.job(status=JobStatus.QC1_REVIEWING, cvat_job_id=412)
        client = _FakeSyncClient([
            {"id": 411, "stage": "annotation", "state": "in progress"},
            {"id": 412, "stage": "annotation", "state": "in progress"},
        ])
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        j_pending.refresh_from_db()
        j_reviewing.refresh_from_db()
        self.assertEqual(j_pending.status, JobStatus.PENDING_QC1)
        self.assertEqual(j_reviewing.status, JobStatus.QC1_REVIEWING)

    def test_stale_cvat_rejection_does_not_double_increment_rework_round(self):
        """P0: CVAT giữ nguyên ('validation', 'rejected') cũ không được tăng rework_round lần 2."""
        j_rework = self.f.job(
            status=JobStatus.REWORK,
            rework_round=1,
            cvat_job_id=415,
            cvat_stage="validation",
            cvat_state="rejected",
        )
        j_resubmitted = self.f.job(
            status=JobStatus.QC1_REVIEWING,
            rework_round=1,
            cvat_job_id=416,
            cvat_stage="validation",
            cvat_state="rejected",
        )
        client = _FakeSyncClient([
            {"id": 415, "stage": "validation", "state": "rejected"},
            {"id": 416, "stage": "validation", "state": "rejected"},
        ])
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        j_rework.refresh_from_db()
        j_resubmitted.refresh_from_db()
        self.assertEqual((j_rework.status, j_rework.rework_round), (JobStatus.REWORK, 1))
        self.assertEqual((j_resubmitted.status, j_resubmitted.rework_round), (JobStatus.QC1_REVIEWING, 1))

    def test_locked_escalated_and_locked_batch_jobs_not_mutated_in_status(self):
        """P0: Job is_locked / is_escalated / batch bị khoá không bị sync đổi trạng thái."""
        j_locked = self.f.job(status=JobStatus.PENDING_ANNOTATION, is_locked=True, cvat_job_id=421)
        j_escalated = self.f.job(status=JobStatus.ANNOTATING, is_escalated=True, cvat_job_id=422)
        client = _FakeSyncClient([
            {"id": 421, "stage": "annotation", "state": "in progress"},
            {"id": 422, "stage": "annotation", "state": "completed"},
        ])
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        j_locked.refresh_from_db()
        j_escalated.refresh_from_db()
        self.assertEqual(j_locked.status, JobStatus.PENDING_ANNOTATION)
        self.assertEqual(j_escalated.status, JobStatus.ANNOTATING)

        # Khoá batch → job trong batch không đổi trạng thái khi sync
        self.f.batch.status = DataStatus.LOCKED
        self.f.batch.save(update_fields=["status"])
        j_in_locked_batch = self.f.job(status=JobStatus.PENDING_ANNOTATION, cvat_job_id=423)
        sync.sync_organization(
            self.f.project,
            self.f.pm,
            client=_FakeSyncClient([{"id": 423, "stage": "annotation", "state": "in progress"}]),
        )
        j_in_locked_batch.refresh_from_db()
        self.assertEqual(j_in_locked_batch.status, JobStatus.PENDING_ANNOTATION)

    def test_cvat_http_calls_run_outside_transaction_atomic(self):
        """P0: Toàn bộ lệnh gọi HTTP tới CVAT chạy ngoài transaction.atomic()."""
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="a1")
        self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, cvat_job_id=430)
        client = _FakeSyncClient(
            [{"id": 430, "stage": "annotation", "state": "in progress"}],
            memberships={7: [{"user": {"id": 11}, "is_active": True}]},
            expected_atomic_depth=len(connection.atomic_blocks),
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client, count_objects=True)
        self.assertIn("list_org_projects", client.http_calls)
        self.assertIn("count_job_objects", client.http_calls)
        self.assertIn("set_job_assignee", client.http_calls)

    def test_new_job_ignores_non_annotator_cvat_assignee(self):
        CvatAccount.objects.create(user=self.f.pm, cvat_user_id=50, cvat_username="pm_cvat")
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="ann_cvat")
        client = _FakeSyncClient([
            {"id": 440, "stage": "annotation", "state": "in progress", "assignee": {"id": 50}},
            {"id": 441, "stage": "annotation", "state": "in progress", "assignee": {"id": 11}},
        ])
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        self.assertIsNone(Job.objects.get(cvat_job_id=440).annotator)
        self.assertEqual(Job.objects.get(cvat_job_id=441).annotator, self.f.ann1)

    def test_sync_organizations_seeds_default_error_categories_for_existing_org(self):
        CvatAccount.objects.create(user=self.f.pm, cvat_user_id=50, cvat_username="pm_cvat")
        ErrorCategory.objects.filter(project=self.f.project).delete()
        self.assertEqual(ErrorCategory.objects.filter(project=self.f.project).count(), 0)
        client = _FakeSyncClient(
            jobs=[],
            orgs=[{"id": 7, "slug": "acme", "name": self.f.project.name}],
            memberships={7: [{"user": {"id": 50}, "role": "owner", "is_active": True}]},
        )
        sync.sync_organizations(actor=self.f.pm, client=client)
        self.assertGreater(ErrorCategory.objects.filter(project=self.f.project).count(), 0)


class JobsHeldByAndSyncOrgsRbacTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()

    def test_jobs_held_by_excludes_rejected_prior_qc2_samples(self):
        """P1: Auditor có mẫu QC2 đã reject trong audit in_progress không còn giữ job."""
        other_qc2 = User.objects.create_user("qc2_new", password="pw")
        RoleAssignment.objects.create(user=other_qc2, role=Role.QC2, project=self.f.project)
        CvatAccount.objects.create(user=self.f.qc2, cvat_user_id=22, cvat_username="q2_old")
        CvatAccount.objects.create(user=other_qc2, cvat_user_id=23, cvat_username="q2_new")

        job = self.f.job(status=JobStatus.PENDING_QC2, cvat_job_id=601)
        audit = Audit.objects.create(
            project=self.f.project,
            batch=self.f.batch,
            method="random",
            sampling_rate=50,
            seed=1,
            eligible_count=1,
            created_by=self.f.pm,
        )
        AuditSample.objects.create(audit=audit, job=job, auditor=self.f.qc2, result=AuditSample.Result.REJECT)
        AuditSample.objects.create(audit=audit, job=job, auditor=other_qc2, result=AuditSample.Result.PENDING)

        self.assertEqual(list(jobs_held_by(self.f.qc2)), [])
        held = list(jobs_held_by(other_qc2))
        self.assertEqual([j.pk for j in held], [job.pk])
        self.assertTrue(hasattr(held[0], "_pending_samples"))

    @mock.patch("cvat_integration.views.sync_organizations")
    def test_sync_organizations_view_blocks_outsider_and_annotator(self, mock_sync):
        outsider = User.objects.create_user("outsider", password="pw")
        for user in (outsider, self.f.ann1, self.f.qc1, self.f.qc2):
            res = self.f.client(user).post("/api/cvat/sync-organizations/", {}, format="json")
            self.assertEqual(res.status_code, 403, f"Expected 403 for {user.username}")
        mock_sync.assert_not_called()

    @mock.patch("cvat_integration.views.sync_organizations")
    def test_sync_organizations_view_filters_result_for_pm_and_shows_all_for_superuser(self, mock_sync):
        other = Project.objects.create(name="Secret Org")
        mock_sync.return_value = {
            "created": [self.f.project.name, other.name],
            "updated": [other.name],
            "pm_added": [
                {"organization": self.f.project.name, "user": self.f.pm.username},
                {"organization": other.name, "user": "other_pm"},
            ],
            "members_added": [
                {"organization": self.f.project.name, "user": self.f.ann1.username},
                {"organization": other.name, "user": "other_ann"},
            ],
            "waiting": [{"cvat_org_id": 99, "name": "Unlinked Org", "reason": "No PM"}],
        }

        pm_res = self.f.client(self.f.pm).post("/api/cvat/sync-organizations/", {}, format="json")
        self.assertEqual(pm_res.status_code, 200, pm_res.data)
        self.assertEqual(pm_res.data["created"], [self.f.project.name])
        self.assertEqual(pm_res.data["updated"], [])
        self.assertEqual(pm_res.data["pm_added"], [{"organization": self.f.project.name, "user": self.f.pm.username}])
        self.assertEqual(
            pm_res.data["members_added"], [{"organization": self.f.project.name, "user": self.f.ann1.username}]
        )
        self.assertEqual(pm_res.data["waiting"], [])

        admin = User.objects.create_superuser("super_admin", "super@example.com", "pw")
        admin_res = self.f.client(admin).post("/api/cvat/sync-organizations/", {}, format="json")
        self.assertEqual(admin_res.status_code, 200, admin_res.data)
        self.assertEqual(admin_res.data["created"], [self.f.project.name, other.name])
        self.assertEqual(len(admin_res.data["waiting"]), 1)
