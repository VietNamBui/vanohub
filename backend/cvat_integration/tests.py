from unittest import mock

from django.test import TestCase

from accounts.testing import ProjectFixture
from jobs.models import JobStatus
from projects.models import ActivityLog
from quality.models import Audit, AuditSample

from .assignee import push_assignees
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
        with mock.patch.object(FakeCvatClient, "set_job_assignee", side_effect=CvatError("down")):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.f.client(self.f.pm).post(self.f.url(f"jobs/{job.id}/assign/"),
                                                         {"annotator": self.f.ann1.id}, format="json")
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
