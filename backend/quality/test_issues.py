from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from accounts.testing import ProjectFixture
from cvat_integration.client import CvatClient, CvatError
from cvat_integration.models import CvatAccount
from cvat_integration.schemas import CvatCommentPayload, CvatIssuePayload
from cvat_integration.sync import import_task_jobs, sync_batch, sync_organization
from jobs.models import AnnotatorRequest, Job, JobStatus
from jobs.views import submit_annotation
from projects.models import Batch, Dataset, Project, UserNotification

from .issues import CvatIssueSnapshot, import_job_issues
from .models import (
    DEFAULT_ERROR_CATEGORIES,
    AuditSample,
    ErrorCategory,
    JobIssue,
    PrimaryCategory,
    ReviewError,
    Severity,
    seed_default_error_categories,
)


class _FakeIssueClient:
    """In-memory CVAT fake supporting issues, comments, and optional org/task/job sync endpoints."""

    def __init__(
        self,
        *,
        issues_by_job: dict[int, list[dict[str, Any]]] | None = None,
        comments_by_job: dict[int, list[dict[str, Any]]] | None = None,
        issue_error_jobs: set[int] | None = None,
        projects: list[dict[str, Any]] | None = None,
        tasks_by_project: dict[int, list[dict[str, Any]]] | None = None,
        jobs_by_task: dict[int, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.issues_by_job = issues_by_job or {}
        self.comments_by_job = comments_by_job or {}
        self.issue_error_jobs = issue_error_jobs or set()
        self.projects = projects or []
        self.tasks_by_project = tasks_by_project or {}
        self.jobs_by_task = jobs_by_task or {}

    def list_job_issues(self, cvat_job_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        if cvat_job_id in self.issue_error_jobs:
            raise CvatError(f"Simulated CVAT failure for issues on job {cvat_job_id}")
        return list(self.issues_by_job.get(cvat_job_id, []))

    def list_job_comments(self, cvat_job_id: int, **kwargs: Any) -> list[dict[str, Any]]:
        if cvat_job_id in self.issue_error_jobs:
            raise CvatError(f"Simulated CVAT failure for comments on job {cvat_job_id}")
        return list(self.comments_by_job.get(cvat_job_id, []))

    def list_org_projects(self, org_id: int) -> list[dict[str, Any]]:
        return list(self.projects)

    def list_project_tasks(self, project_id: int) -> list[dict[str, Any]]:
        return list(self.tasks_by_project.get(project_id, []))

    def list_task_jobs(self, task_id: int) -> list[dict[str, Any]]:
        return list(self.jobs_by_task.get(task_id, []))

    def get_task(self, task_id: int) -> dict[str, Any]:
        for tasks in self.tasks_by_project.values():
            for t in tasks:
                if t["id"] == task_id:
                    return t
        return {"id": task_id, "name": f"Task {task_id}", "project_id": None}

    def count_job_objects(self, job_id: int, **kwargs: Any) -> int:
        return 0

    def set_job_assignee(self, job_id: int, cvat_user_id: int | None) -> None:
        return None


def _raw_issue(
    issue_id: int,
    *,
    job_id: int,
    owner_id: int | None = None,
    frame: int = 5,
    position: list[float] | None = None,
    resolved: bool = False,
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "job": job_id,
        "frame": frame,
        "position": position if position is not None else [1.0, 2.0, 3.0, 4.0],
        "resolved": resolved,
        "owner": {"id": owner_id, "username": f"u{owner_id}"} if owner_id is not None else None,
        "assignee": None,
        "created_date": "2026-11-28T01:00:00Z",
        "updated_date": "2026-11-28T01:05:00Z",
    }


def _raw_comment(
    comment_id: int,
    *,
    issue_id: int,
    message: str,
    owner_id: int | None = None,
) -> dict[str, Any]:
    return {
        "id": comment_id,
        "issue": issue_id,
        "message": message,
        "owner": {"id": owner_id, "username": f"u{owner_id}"} if owner_id is not None else None,
        "created_date": "2026-11-28T01:00:00Z",
        "updated_date": "2026-11-28T01:00:00Z",
    }


class CvatIssueClientAndSchemaTests(TestCase):
    def test_strict_pydantic_schemas_reject_invalid_payloads(self) -> None:
        with self.assertRaises(PydanticValidationError):
            CvatIssuePayload.model_validate(
                {
                    "id": 1,
                    "job": 2,
                    "frame": True,  # bool must fail strict=True
                    "position": [1.0, 2.0],
                    "resolved": False,
                }
            )
        with self.assertRaises(PydanticValidationError):
            CvatIssuePayload.model_validate(
                {
                    "id": 1,
                    "job": 2,
                    "frame": 0,
                    "position": [float("nan"), 1.0],
                    "resolved": False,
                }
            )
        with self.assertRaises(PydanticValidationError):
            CvatCommentPayload.model_validate({"id": 0, "issue": 1, "message": "x"})

    def test_client_list_job_issues_paginates_dedupes_and_checks_job_id(self) -> None:
        client = CvatClient(base_url="http://cvat.test", token="tok")
        responses = [
            {
                "results": [_raw_issue(1, job_id=50), _raw_issue(2, job_id=50)],
                "next": "http://cvat.test/api/issues?job_id=50&page=2&sort=id",
            },
            {
                "results": [_raw_issue(2, job_id=50), _raw_issue(3, job_id=50)],
                "next": None,
            },
        ]
        with patch.object(client, "_request", side_effect=responses) as req_mock:
            out = client.list_job_issues(50)
        self.assertEqual([i["id"] for i in out], [1, 2, 3])
        self.assertEqual(req_mock.call_count, 2)
        self.assertEqual(req_mock.call_args_list[0].kwargs["params"]["sort"], "id")
        self.assertEqual(req_mock.call_args_list[0].kwargs["params"]["job_id"], 50)

        with (
            patch.object(client, "_request", return_value={"results": [_raw_issue(9, job_id=99)], "next": None}),
            self.assertRaises(CvatError),
        ):
            client.list_job_issues(50)

        with patch.object(
            client,
            "_request",
            return_value={"results": [_raw_comment(10, issue_id=1, message="[E1] Missed")], "next": None},
        ):
            comments = client.list_job_comments(50)
        self.assertEqual([c["id"] for c in comments], [10])


class JobIssueWorkflowTests(TestCase):
    def setUp(self) -> None:
        self.f = ProjectFixture("ISS")
        self.f.project.issue_gate_enabled = True
        self.f.project.cvat_org_id = 101
        self.f.project.cvat_org_slug = "iss-org"
        self.f.project.save(update_fields=["issue_gate_enabled", "cvat_org_id", "cvat_org_slug"])

        self.pm = self.f.client(self.f.pm)
        self.qc1 = self.f.client(self.f.qc1)
        self.qc2 = self.f.client(self.f.qc2)
        self.ann1 = self.f.client(self.f.ann1)
        self.ann2 = self.f.client(self.f.ann2)
        self.outsider = self.f.client(self.f.outsider)

        CvatAccount.objects.create(user=self.f.pm, cvat_user_id=9001, cvat_username="pm")
        CvatAccount.objects.create(user=self.f.qc2, cvat_user_id=9002, cvat_username="qc2")
        CvatAccount.objects.create(user=self.f.qc1, cvat_user_id=9003, cvat_username="qc1")
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=9004, cvat_username="ann1")
        CvatAccount.objects.create(user=self.f.ann2, cvat_user_id=9005, cvat_username="ann2")

    def test_seed_default_categories_and_unique_code_error(self) -> None:
        fresh_proj = Project.objects.create(name="Seeded")
        seed_default_error_categories(fresh_proj)
        cats = list(ErrorCategory.objects.filter(project=fresh_proj).order_by("code"))
        self.assertEqual(len(cats), len(DEFAULT_ERROR_CATEGORIES))
        self.assertTrue(any(c.code == "E6" and c.primary_category == PrimaryCategory.E6 for c in cats))

        dup = self.pm.post(
            self.f.url("error-categories/"),
            {"name": "Unique Track Name", "code": "E1", "primary_category": "E1"},
            format="json",
        )
        self.assertEqual(dup.status_code, 201, dup.data)
        dup2 = self.pm.post(
            self.f.url("error-categories/"),
            {"name": "Another Name", "code": "E1", "primary_category": "E1"},
            format="json",
        )
        self.assertEqual(dup2.status_code, 400)
        self.assertIn("code", dup2.data)

    def test_import_envelope_3d_authority_preqc_skip_and_tamper_defenses(self) -> None:
        job = self.f.job(status=JobStatus.QC1_REVIEWING, annotator=self.f.ann1, cvat_job_id=7001, frame_count=20)
        pos_3d = [0.0] * 16
        pos_3d[10] = 43.0  # track_id = 42

        fake = _FakeIssueClient(
            issues_by_job={
                7001: [
                    _raw_issue(101, job_id=7001, owner_id=9003, frame=5, position=pos_3d),  # QC1 typed 3D
                    _raw_issue(102, job_id=7001, owner_id=9003, frame=6),  # vanilla untyped
                    _raw_issue(103, job_id=7001, owner_id=9003, frame=7),  # preqc skipped
                    _raw_issue(104, job_id=7001, owner_id=9005, frame=8),  # ann2 unauthorized non-clar
                    _raw_issue(105, job_id=7001, owner_id=9004, frame=9),  # ann1 clarification
                ]
            },
            comments_by_job={
                7001: [
                    _raw_comment(1, issue_id=101, message="[E6][critical] Track swapped [FRAMES:5-10]", owner_id=9003),
                    _raw_comment(2, issue_id=102, message="Just a plain note", owner_id=9003),
                    _raw_comment(3, issue_id=103, message="[E1][REF:preqc:99] Auto", owner_id=9003),
                    _raw_comment(4, issue_id=104, message="[E1] Unauthorized", owner_id=9005),
                    _raw_comment(5, issue_id=105, message="[CLS-UNK] Ambiguous van", owner_id=9004),
                ]
            },
        )
        res = import_job_issues(job.pk, project=self.f.project, client=fake)
        self.assertEqual(res["created"], 4)
        self.assertFalse(JobIssue.objects.filter(job=job, cvat_issue_id=103).exists())

        ji_101 = JobIssue.objects.get(job=job, cvat_issue_id=101)
        self.assertEqual(ji_101.track_id, 42)
        self.assertIsNone(ji_101.shape_id)
        self.assertEqual(ji_101.frame_start, 5)
        self.assertEqual(ji_101.frame_end, 10)
        self.assertEqual(ji_101.primary_category, PrimaryCategory.E6)
        self.assertEqual(ji_101.severity, Severity.CRITICAL)
        self.assertEqual(ji_101.author_stage, JobIssue.AuthorStage.QC1)
        self.assertEqual(ji_101.authority_status, JobIssue.AuthorityStatus.VALID)

        ji_102 = JobIssue.objects.get(job=job, cvat_issue_id=102)
        self.assertEqual(ji_102.defect_code, "")
        self.assertEqual(ji_102.primary_category, "")
        self.assertEqual(ji_102.severity, Severity.MINOR)

        ji_104 = JobIssue.objects.get(job=job, cvat_issue_id=104)
        self.assertEqual(ji_104.authority_status, JobIssue.AuthorityStatus.REJECTED_AUTHOR)

        ji_105 = JobIssue.objects.get(job=job, cvat_issue_id=105)
        self.assertTrue(ji_105.is_clarification)
        self.assertEqual(ji_105.author_stage, JobIssue.AuthorStage.ANNOTATOR)
        self.assertEqual(ji_105.status, JobIssue.Status.UNCLEAR)

        ov = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov["pending_decisions"]["pending_issue_rulings"], 1)

        # Tamper detection: first comment deleted + 3D position wiped
        fake.issues_by_job[7001] = [_raw_issue(101, job_id=7001, owner_id=9003, frame=5, position=[1.0, 2.0])]
        fake.comments_by_job[7001] = [_raw_comment(99, issue_id=101, message="[E4][minor] Downgraded", owner_id=9003)]
        import_job_issues(job.pk, project=self.f.project, client=fake)
        ji_101.refresh_from_db()
        self.assertTrue(ji_101.tampered)
        self.assertEqual(ji_101.tamper_reason, "position_3d_wiped")
        self.assertEqual(ji_101.severity, Severity.CRITICAL)

        # Source missing when issue disappears completely from later snapshot
        ji_102.created_at = timezone.now() - timedelta(minutes=1)
        ji_102.cvat_synced_at = timezone.now() - timedelta(minutes=1)
        ji_102.save(update_fields=["created_at", "cvat_synced_at"])
        fake.issues_by_job[7001] = [_raw_issue(101, job_id=7001, owner_id=9003, frame=5)]
        import_job_issues(job.pk, project=self.f.project, client=fake)
        ji_102.refresh_from_db()
        self.assertTrue(ji_102.source_missing)

    def test_four_eyes_and_rbac_404_isolation(self) -> None:
        unassigned = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=None, qc1_reviewer=None)
        unassigned.annotator = self.f.ann1
        unassigned.save(update_fields=["annotator"])
        # QC2 logs a valid issue on job; QC1 must NOT see/review that job under four-eyes
        ji_qc2 = JobIssue.objects.create(
            project=self.f.project,
            job=unassigned,
            cvat_issue_id=201,
            author=self.f.qc2,
            author_stage=JobIssue.AuthorStage.QC2,
            authority_status=JobIssue.AuthorityStatus.VALID,
            severity=Severity.MAJOR,
            frame_number=1,
        )
        # QC1 tries to inspect job issues -> 403 because QC2 authored a valid issue? Wait: _qc1_visible_jobs excludes QC2 issue authors if user == author;
        # specifically if QC1 authored a valid issue, QC2/Annotator cannot claim/audit:
        claimable_job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, qc1_reviewer=None)
        JobIssue.objects.filter(job=claimable_job).delete()
        claimable_job.annotator = None
        claimable_job.save(update_fields=["annotator"])
        JobIssue.objects.create(
            project=self.f.project,
            job=claimable_job,
            cvat_issue_id=202,
            author=self.f.ann2,  # suppose ann2 also authored QC1 issue previously on job
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
        )
        res_claim = self.ann2.post(self.f.url("annotator/jobs/claim/"), {}, format="json")
        self.assertEqual(res_claim.status_code, 400)

        # QC2 user logs valid issue on j_qc -> QC2 user cannot audit; and dual-role QC1=author excluded from QC1 queue
        dual = self.f.pm  # PM implies QC2
        dual_job = self.f.job(status=JobStatus.PENDING_QC1, qc1_reviewer=None)
        JobIssue.objects.create(
            project=self.f.project,
            job=dual_job,
            cvat_issue_id=203,
            author=self.f.qc1,
            author_stage=JobIssue.AuthorStage.QC2,
            authority_status=JobIssue.AuthorityStatus.VALID,
        )
        qc1_queue = self.qc1.get(self.f.url("qc1/jobs/")).data
        qc1_items = qc1_queue.get("results", qc1_queue) if isinstance(qc1_queue, dict) else qc1_queue
        qc1_ids = [r["id"] for r in qc1_items]
        self.assertNotIn(dual_job.id, qc1_ids)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{dual_job.id}/start/"), {}, format="json").status_code, 403)

        # Outsider gets 404 everywhere on issues API
        self.assertEqual(self.outsider.get(self.f.url("issues/")).status_code, 404)
        self.assertEqual(self.outsider.post(self.f.url(f"issues/{ji_qc2.id}/address/"), {}, format="json").status_code, 404)

        # PM is allowed to import/rule; annotator is forbidden from resolving/ruling; QC1 is forbidden from ruling
        self.assertEqual(self.ann1.post(self.f.url(f"issues/{ji_qc2.id}/resolve/"), {}, format="json").status_code, 403)
        self.assertEqual(
            self.qc1.post(self.f.url(f"issues/{ji_qc2.id}/rule/"), {"decision": "resolved"}, format="json").status_code,
            403,
        )
        self.assertTrue(dual.pk)

    @override_settings(CVAT_URL="http://cvat.test", CVAT_ACCESS_TOKEN="tok")
    def test_submit_gate_address_dispute_fail_open_and_acceptance_gates(self) -> None:
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=7010, frame_count=12)
        blocker = JobIssue.objects.create(
            project=self.f.project,
            job=job,
            cvat_issue_id=301,
            author=self.f.qc1,
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
            defect_code="E1",
            primary_category=PrimaryCategory.E1,
            severity=Severity.MAJOR,
            status=JobIssue.Status.OPEN,
            frame_number=4,
            message="Missed cyclist",
        )
        clar = JobIssue.objects.create(
            project=self.f.project,
            job=job,
            cvat_issue_id=302,
            author=self.f.ann1,
            author_stage=JobIssue.AuthorStage.ANNOTATOR,
            authority_status=JobIssue.AuthorityStatus.VALID,
            defect_code="CLS-UNK",
            primary_category=PrimaryCategory.E2,
            severity=Severity.MAJOR,
            is_clarification=True,
            status=JobIssue.Status.UNCLEAR,
            frame_number=5,
            message="Unclear scooter",
        )

        # Submit fails when CVAT refresh returns empty? Wait: mock fake client preserving 301 & 302 as OPEN/UNCLEAR!
        fake = _FakeIssueClient(
            issues_by_job={
                7010: [
                    _raw_issue(301, job_id=7010, owner_id=9003, frame=4),
                    _raw_issue(302, job_id=7010, owner_id=9004, frame=5),
                ]
            },
            comments_by_job={
                7010: [
                    _raw_comment(11, issue_id=301, message="[E1] Missed cyclist", owner_id=9003),
                    _raw_comment(12, issue_id=302, message="[CLS-UNK] Unclear scooter", owner_id=9004),
                ]
            },
        )
        with patch("cvat_integration.client.CvatClient.list_job_issues", side_effect=fake.list_job_issues), patch(
            "cvat_integration.client.CvatClient.list_job_comments", side_effect=fake.list_job_comments
        ):
            blocked_res = self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json")
            self.assertEqual(blocked_res.status_code, 400)
            self.assertIn("blocking_issue_ids", blocked_res.data)
            self.assertTrue(all(isinstance(i, int) for i in blocked_res.data["blocking_issue_ids"]))

            # Clarification cannot be addressed before PM ruling
            self.assertEqual(
                self.ann1.post(self.f.url(f"issues/{clar.id}/address/"), {}, format="json").status_code,
                400,
            )

            # Annotator addresses blocker 301 -> clar (UNCLEAR) does NOT block submit!
            addr_res = self.ann1.post(self.f.url(f"issues/{blocker.id}/address/"), {"note": "Added box"}, format="json")
            self.assertEqual(addr_res.status_code, 200, addr_res.data)
            self.assertEqual(addr_res.data["status"], JobIssue.Status.ADDRESSED)

        # Fail-open submit when CVAT is unreachable: still succeeds using cached ADDRESSED state + issue_sync_warning=True
        with patch("cvat_integration.client.CvatClient.list_job_issues", side_effect=CvatError("CVAT down")):
            sub_res = self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json")
        self.assertEqual(sub_res.status_code, 200, sub_res.data)
        self.assertTrue(sub_res.data["issue_sync_warning"])
        self.assertEqual(sub_res.data["status"], JobStatus.PENDING_QC1)

        # Acceptance Gate: qc1_pass blocked while 301 is ADDRESSED and 302 is UNCLEAR
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 400)

        # Resolve 301 via QC1; still blocked by 302 UNCLEAR
        self.assertEqual(
            self.qc1.post(self.f.url(f"issues/{blocker.id}/resolve/"), {"note": "Verified"}, format="json").status_code,
            200,
        )
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 400)

        # PM rules on 302 -> resolved / ruling
        rule_res = self.pm.post(
            self.f.url(f"issues/{clar.id}/rule/"),
            {
                "decision": "ruling",
                "ruling_label": "motorcycle",
                "ruling_attributes": {"rider": "yes"},
                "ruling_note": "Label as motorcycle",
            },
            format="json",
        )
        self.assertEqual(rule_res.status_code, 200, rule_res.data)
        self.assertEqual(rule_res.data["status"], JobIssue.Status.OPEN)
        self.assertEqual(rule_res.data["ruling_label"], "motorcycle")
        self.assertEqual(rule_res.data["ruled_by"]["id"], self.f.pm.id)
        # Re-resolved after PM ruling:
        self.assertEqual(self.qc1.post(self.f.url(f"issues/{clar.id}/resolve/"), {}, format="json").status_code, 200)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 200)

        # Even if a QC2 issue appears while QC1_PASSED, confirm-qc2 is blocked until resolved
        qc2_blocker = JobIssue.objects.create(
            project=self.f.project,
            job=job,
            cvat_issue_id=303,
            author=self.f.qc2,
            author_stage=JobIssue.AuthorStage.QC2,
            authority_status=JobIssue.AuthorityStatus.VALID,
            severity=Severity.MAJOR,
            status=JobIssue.Status.OPEN,
            frame_number=2,
        )
        self.assertEqual(self.pm.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code, 400)
        self.assertEqual(self.qc2.post(self.f.url(f"issues/{qc2_blocker.id}/resolve/"), {}, format="json").status_code, 200)
        self.assertEqual(self.pm.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json").status_code, 200)

        sample = AuditSample.objects.get(job=job, result=AuditSample.Result.PENDING)
        # Reopen blocks audit-sample pass; resolve unblocks; new blocker on APPROVED blocks delivery
        self.assertEqual(self.qc2.post(self.f.url(f"issues/{qc2_blocker.id}/reopen/"), {}, format="json").status_code, 200)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 400)
        self.assertEqual(self.qc2.post(self.f.url(f"issues/{qc2_blocker.id}/resolve/"), {}, format="json").status_code, 200)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 200)

        JobIssue.objects.filter(pk=qc2_blocker.pk).update(status=JobIssue.Status.UNCLEAR)
        self.assertEqual(
            self.pm.post(
                self.f.url("deliveries/"),
                {"batch": self.f.batch.id, "recipient": "Client", "output_path": "s3://out/b1"},
                format="json",
            ).status_code,
            400,
        )
        JobIssue.objects.filter(pk=qc2_blocker.pk).update(status=JobIssue.Status.NOT_AN_ISSUE)
        self.assertEqual(
            self.pm.post(
                self.f.url("deliveries/"),
                {"batch": self.f.batch.id, "recipient": "Client", "output_path": "s3://out/b1"},
                format="json",
            ).status_code,
            201,
        )

    def test_dispute_ruling_reject_materialization_reopen_watermark_and_lock_order(self) -> None:
        job = self.f.job(status=JobStatus.QC1_REVIEWING, annotator=self.f.ann1, frame_count=15)
        cat_e1 = ErrorCategory.objects.create(
            project=self.f.project, name="Missing Object", code="E1", primary_category="E1"
        )
        ji = JobIssue.objects.create(
            project=self.f.project,
            job=job,
            cvat_issue_id=401,
            author=self.f.qc1,
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
            defect_code="EXI-MISS",
            primary_category=PrimaryCategory.E1,
            severity=Severity.MAJOR,
            status=JobIssue.Status.OPEN,
            frame_number=7,
            message="Missing car at frame 7",
        )
        ji_qc2 = JobIssue.objects.create(
            project=self.f.project,
            job=job,
            cvat_issue_id=402,
            author=self.f.qc2,
            author_stage=JobIssue.AuthorStage.QC2,
            authority_status=JobIssue.AuthorityStatus.VALID,
            severity=Severity.MAJOR,
            status=JobIssue.Status.OPEN,
            frame_number=7,
        )
        # QC1 reject using QC2-authored issue fails (400)
        bad_rej = self.qc1.post(
            self.f.url(f"qc1/jobs/{job.id}/reject/"),
            {"errors": [{"category": cat_e1.id, "location": "f7", "description": "x", "job_issue": ji_qc2.id}]},
            format="json",
        )
        self.assertEqual(bad_rej.status_code, 400)

        # QC1 reject referencing ji materializes ReviewError with is_missing_object=True and job_issue link
        rej = self.qc1.post(
            self.f.url(f"qc1/jobs/{job.id}/reject/"),
            {"errors": [{"category": cat_e1.id, "location": "", "description": "", "job_issue": ji.id}]},
            format="json",
        )
        self.assertEqual(rej.status_code, 200, rej.data)
        err = ReviewError.objects.get(job=job, job_issue=ji)
        self.assertEqual(err.cvat_issue_id, 401)
        self.assertTrue(err.is_missing_object)

        # Annotator disputes issue via /issues/{id}/dispute/ -> creates AnnotatorRequest and sets UNCLEAR
        disp = self.ann1.post(
            self.f.url(f"issues/{ji.id}/dispute/"),
            {"reason": "Occlusion > 95% per guideline"},
            format="json",
        )
        self.assertEqual(disp.status_code, 200, disp.data)
        req_id = disp.data["request_id"]
        self.assertEqual(disp.data["issue"]["status"], JobIssue.Status.UNCLEAR)
        req_list = self.ann1.get(self.f.url("annotator/requests/")).data
        req_items = req_list.get("results", req_list) if isinstance(req_list, dict) else req_list
        req_item = next(r for r in req_items if r["id"] == req_id)
        self.assertEqual(req_item["job_issue"], ji.id)
        self.assertEqual(req_item["job_issue_cvat_id"], 401)

        # Canonical lock order check on resolve_annotator_request_atomic: Job FOR UPDATE before ReviewError/Request
        with CaptureQueriesContext(connection) as ctx:
            res_req = self.pm.post(
                self.f.url(f"annotator/requests/{req_id}/resolve/"),
                {"status": AnnotatorRequest.Status.RESOLVED, "resolution_note": "Valid occlusion"},
                format="json",
            )
        self.assertEqual(res_req.status_code, 200, res_req.data)
        for_update_tables = [
            q["sql"] for q in ctx.captured_queries if "FOR UPDATE" in q["sql"]
        ]
        self.assertGreaterEqual(len(for_update_tables), 3)
        self.assertIn("jobs_job", for_update_tables[0])

        ji.refresh_from_db()
        err.refresh_from_db()
        self.assertEqual(ji.status, JobIssue.Status.NOT_AN_ISSUE)
        self.assertTrue(err.is_voided)

        # CVAT [REOPENED] comment on NOT_AN_ISSUE sets cvat_reopen_drift=True without dropping NOT_AN_ISSUE
        fake = _FakeIssueClient(
            issues_by_job={9999: [_raw_issue(401, job_id=9999, owner_id=9003, frame=7)]},
            comments_by_job={
                9999: [
                    _raw_comment(1, issue_id=401, message="[E1] Missing car", owner_id=9003),
                    _raw_comment(2, issue_id=401, message="[REOPENED] Check again", owner_id=9003),
                ]
            },
        )
        job.cvat_job_id = 9999
        job.save(update_fields=["cvat_job_id"])
        import_job_issues(job.pk, project=self.f.project, client=fake)
        ji.refresh_from_db()
        self.assertEqual(ji.status, JobIssue.Status.NOT_AN_ISSUE)
        self.assertTrue(ji.cvat_reopen_drift)

    def test_reopen_comment_watermark_ignores_old_addressed_comment(self) -> None:
        job = self.f.job(status=JobStatus.QC1_REVIEWING, annotator=self.f.ann1, cvat_job_id=7020)
        fake = _FakeIssueClient(
            issues_by_job={7020: [_raw_issue(601, job_id=7020, owner_id=9003, frame=1)]},
            comments_by_job={
                7020: [
                    _raw_comment(10, issue_id=601, message="[E2] Wrong class", owner_id=9003),
                    _raw_comment(20, issue_id=601, message="[ADDRESSED] Fixed class", owner_id=9004),
                ]
            },
        )
        import_job_issues(job.pk, project=self.f.project, client=fake)
        ji = JobIssue.objects.get(job=job, cvat_issue_id=601)
        self.assertEqual(ji.status, JobIssue.Status.ADDRESSED)
        self.assertEqual(ji.cvat_last_comment_id, 20)

        # PM/QC1 reopens via API -> sets watermark reopened_after_comment_id >= 20
        self.assertEqual(self.qc1.post(self.f.url(f"issues/{ji.id}/reopen/"), {}, format="json").status_code, 200)
        ji.refresh_from_db()
        self.assertEqual(ji.status, JobIssue.Status.REOPENED)
        self.assertGreaterEqual(ji.reopened_after_comment_id, 20)

        # Re-importing the SAME comment #20 must NOT revert REOPENED -> ADDRESSED
        import_job_issues(job.pk, project=self.f.project, client=fake)
        ji.refresh_from_db()
        self.assertEqual(ji.status, JobIssue.Status.REOPENED)

        # Posting a NEWER comment #30 -> transitions REOPENED -> ADDRESSED cleanly
        fake.comments_by_job[7020].append(_raw_comment(30, issue_id=601, message="[ADDRESSED] Re-fixed", owner_id=9004))
        import_job_issues(job.pk, project=self.f.project, client=fake)
        ji.refresh_from_db()
        self.assertEqual(ji.status, JobIssue.Status.ADDRESSED)

    @override_settings(CVAT_SYNC_COOLDOWN_SECONDS=0)
    def test_cvat_sync_gates_preqc1_and_postqc1_and_fails_closed_per_job(self) -> None:
        # Prepare CVAT fake org tree: one healthy pre-QC job held by issue #1, one job failing issue fetch (CvatError),
        # one post-QC job held at QC1_REVIEWING with first_qc1_result="" until issue resolved.
        client = _FakeIssueClient(
            projects=[{"id": 500, "name": "DS Sync"}],
            tasks_by_project={
                500: [{"id": 600, "name": "Task Sync", "project_id": 500, "size": 30}],
            },
            jobs_by_task={
                600: [
                    {
                        "id": 8001,
                        "stage": "annotation",
                        "state": "completed",
                        "type": "annotation",
                        "assignee": {"id": 9004},
                        "start_frame": 0,
                        "stop_frame": 9,
                    },
                    {
                        "id": 8002,
                        "stage": "annotation",
                        "state": "completed",
                        "type": "annotation",
                        "assignee": {"id": 9004},
                        "start_frame": 10,
                        "stop_frame": 19,
                    },
                    {
                        "id": 8003,
                        "stage": "validation",
                        "state": "completed",
                        "type": "annotation",
                        "assignee": {"id": 9004},
                        "start_frame": 20,
                        "stop_frame": 29,
                    },
                ]
            },
            issues_by_job={
                8001: [_raw_issue(1, job_id=8001, owner_id=9003, frame=2)],
                8003: [_raw_issue(2, job_id=8003, owner_id=9003, frame=22)],
            },
            comments_by_job={
                8001: [_raw_comment(1, issue_id=1, message="[E1] Missing car", owner_id=9003)],
                8003: [_raw_comment(2, issue_id=2, message="[E1] Unresolved review", owner_id=9003)],
            },
            issue_error_jobs={8002},
        )
        sync_organization(self.f.project, self.f.pm, client=client, cooldown_seconds=0)

        j1 = Job.objects.get(cvat_job_id=8001)
        j2 = Job.objects.get(cvat_job_id=8002)
        j3 = Job.objects.get(cvat_job_id=8003)
        # All three imported cleanly; none advanced past their gate!
        self.assertEqual(j1.status, JobStatus.ANNOTATING)
        self.assertEqual(j2.status, JobStatus.ANNOTATING)
        self.assertEqual(j3.status, JobStatus.QC1_REVIEWING)
        self.assertEqual(j3.first_qc1_result, "")

        # Now address issue #1 on 8001, fix fetch error on 8002 (no issues), resolve issue #2 on 8003
        client.comments_by_job[8001].append(_raw_comment(11, issue_id=1, message="[ADDRESSED] Added", owner_id=9004))
        client.issue_error_jobs.clear()
        client.comments_by_job[8003].append(_raw_comment(12, issue_id=2, message="[RESOLVED] Confirmed", owner_id=9003))

        sync_batch(j1.batch, self.f.pm, client=client)
        j1.refresh_from_db()
        j2.refresh_from_db()
        j3.refresh_from_db()
        self.assertEqual(j1.status, JobStatus.PENDING_QC1)
        self.assertEqual(j2.status, JobStatus.PENDING_QC1)
        self.assertEqual(j3.status, JobStatus.QC1_PASSED)
        self.assertEqual(j3.first_qc1_result, "pass")

        # Test import_task_jobs on post-QC2 batch creates AuditSample only once unblocked
        ds2 = Dataset.objects.create(project=self.f.project, name="DS2", cvat_project_id=501)
        batch2 = Batch.objects.create(
            project=self.f.project,
            dataset=ds2,
            name="B2",
            qc2_confirmed_at=timezone.now(),
            qc2_confirmed_by=self.f.pm,
        )
        client.tasks_by_project[501] = [{"id": 601, "name": "Task 601", "project_id": 501, "size": 10}]
        client.jobs_by_task[601] = [
            {
                "id": 8004,
                "stage": "validation",
                "state": "completed",
                "type": "annotation",
                "assignee": {"id": 9004},
                "start_frame": 0,
                "stop_frame": 9,
            }
        ]
        client.issues_by_job[8004] = []
        import_task_jobs(batch2, 601, self.f.pm, client=client)
        j4 = Job.objects.get(cvat_job_id=8004)
        self.assertEqual(j4.status, JobStatus.PENDING_QC2)
        self.assertTrue(AuditSample.objects.filter(job=j4, result=AuditSample.Result.PENDING).exists())

    def test_submit_annotation_preserves_fail_open_and_unblocks_on_addressed(self) -> None:
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=7099)
        fake = _FakeIssueClient(
            issues_by_job={7099: [_raw_issue(901, job_id=7099, owner_id=9003, frame=2)]},
            comments_by_job={
                7099: [
                    _raw_comment(1, issue_id=901, message="[E1] Missed", owner_id=9003),
                    _raw_comment(2, issue_id=901, message="[ADDRESSED] Added", owner_id=9004),
                ]
            },
        )
        out = submit_annotation(job.pk, project=self.f.project, actor=self.f.ann1, client=fake)
        self.assertEqual(out.status, JobStatus.PENDING_QC1)
        self.assertFalse(getattr(out, "_issue_sync_warning", True))
        self.assertEqual(UserNotification.objects.filter(job=job, is_pinned_pending=True).count(), 1)

    @override_settings(CVAT_URL="http://cvat.test", CVAT_ACCESS_TOKEN="tok")
    def test_api_import_filters_bidirectional_request_stale_guard_and_qc2_reject(self) -> None:
        job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, cvat_job_id=7120, frame_count=10)
        no_cvat = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann2, cvat_job_id=None, frame_count=10)
        cat_e2 = ErrorCategory.objects.create(
            project=self.f.project, name="Wrong Label", code="E2", primary_category="E2"
        )

        self.assertEqual(self.pm.post(self.f.url("issues/import/"), {"job": no_cvat.id}, format="json").status_code, 400)

        fake = _FakeIssueClient(
            issues_by_job={7120: [_raw_issue(910, job_id=7120, owner_id=9002, frame=3)]},
            comments_by_job={7120: [_raw_comment(1, issue_id=910, message="[E2] Wrong box class", owner_id=9002)]},
        )
        with patch("cvat_integration.client.CvatClient.list_job_issues", side_effect=fake.list_job_issues), patch(
            "cvat_integration.client.CvatClient.list_job_comments", side_effect=fake.list_job_comments
        ):
            imp_res = self.pm.post(self.f.url("issues/import/"), {"job": job.id}, format="json")
        self.assertEqual(imp_res.status_code, 200, imp_res.data)
        self.assertEqual(imp_res.data["created"], 1)
        self.assertEqual(imp_res.data["total"], 1)
        ji = JobIssue.objects.get(job=job, cvat_issue_id=910)

        # Stale snapshot fetched BEFORE existing.cvat_synced_at must not overwrite or mark source_missing
        stale_snap = CvatIssueSnapshot(
            fetched_at=timezone.now() - timedelta(hours=2),
            issues=[],
            comments=[],
        )
        import_job_issues(job.pk, project=self.f.project, prefetched=stale_snap)
        ji.refresh_from_db()
        self.assertFalse(ji.source_missing)

        # Filter query check
        list_res = self.pm.get(self.f.url(f"issues/?job={job.id}&severity=major&primary_category=E2"))
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.data["count"], 1)

        # Bidirectional sync: creating AnnotatorRequest(ERROR_DISPUTE) with job_issue updates JobIssue to UNCLEAR
        req_res = self.ann1.post(
            self.f.url("annotator/requests/"),
            {
                "job": job.id,
                "job_issue": ji.id,
                "request_type": AnnotatorRequest.RequestType.ERROR_DISPUTE,
                "reason": "Label matches annotation spec",
            },
            format="json",
        )
        self.assertEqual(req_res.status_code, 201, req_res.data)
        ji.refresh_from_db()
        self.assertTrue(ji.is_disputed)
        self.assertEqual(ji.status, JobIssue.Status.UNCLEAR)

        # Rejecting the dispute request via /annotator/requests/{id}/resolve/ reopens issue
        rej_req = self.pm.post(
            self.f.url(f"annotator/requests/{req_res.data['id']}/resolve/"),
            {"status": AnnotatorRequest.Status.REJECTED, "resolution_note": "Fix label"},
            format="json",
        )
        self.assertEqual(rej_req.status_code, 200, rej_req.data)
        ji.refresh_from_db()
        self.assertFalse(ji.is_disputed)
        self.assertEqual(ji.status, JobIssue.Status.REOPENED)

        # AuditSample reject rejects out-of-sample frame, accepts in-sample frame idempotently
        from .qc2 import ensure_qc2_sample

        sample = ensure_qc2_sample(job)
        assert sample is not None
        out_frame = next(f for f in range(10) if f not in set(sample.frames or []))
        JobIssue.objects.filter(pk=ji.pk).update(frame_number=out_frame)
        self.assertEqual(
            self.qc2.post(
                self.f.url(f"audit-samples/{sample.id}/reject/"),
                {"errors": [{"category": cat_e2.id, "job_issue": ji.id}]},
                format="json",
            ).status_code,
            400,
        )
        in_frame = (sample.frames or [0])[0]
        JobIssue.objects.filter(pk=ji.pk).update(frame_number=in_frame)
        # Out-of-sample frame_number override on QC2 reject must be rejected (400)
        self.assertEqual(
            self.qc2.post(
                self.f.url(f"audit-samples/{sample.id}/reject/"),
                {"errors": [{"category": cat_e2.id, "job_issue": ji.id, "frame_number": out_frame}]},
                format="json",
            ).status_code,
            400,
        )
        ok_qc2 = self.qc2.post(
            self.f.url(f"audit-samples/{sample.id}/reject/"),
            {"errors": [{"category": cat_e2.id, "job_issue": ji.id}]},
            format="json",
        )
        self.assertEqual(ok_qc2.status_code, 200, ok_qc2.data)
        self.assertTrue(ReviewError.objects.filter(job=job, job_issue=ji, audit_sample=sample).exists())

    def test_audit_p0_p1_p2_hardening_regressions(self) -> None:
        from accounts.models import Role, RoleAssignment, User
        from quality.models import Audit, AuditSample, ReviewStage

        def _pos3d(*, track_id: int | None = None, shape_id: int | None = None) -> list[float]:
            pos = [0.0] * 16
            if track_id is not None:
                pos[10] = float(track_id + 1)
            if shape_id is not None:
                pos[11] = float(shape_id + 1)
            return pos

        cat = ErrorCategory.objects.create(project=self.f.project, name="Audit Cat", code="EXI-MISS", primary_category="E1")

        # P0-1a: Standalone QC2 without assigned pending AuditSample & not author CANNOT resolve/reopen QC1 issue
        job_qc1 = self.f.job(status=JobStatus.QC1_REVIEWING, annotator=self.f.ann1, qc1_reviewer=self.f.qc1, cvat_job_id=8101)
        ji_qc1 = JobIssue.objects.create(
            project=self.f.project,
            job=job_qc1,
            cvat_issue_id=81011,
            defect_code="EXI-MISS",
            primary_category="E1",
            severity="critical",
            frame_number=0,
            author=self.f.qc1,
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.ADDRESSED,
        )
        # P0-1a: Standalone QC2 without assigned AuditSample & not author gets 404 (PQ01 isolation, matching GET)
        self.assertEqual(self.qc2.post(self.f.url(f"issues/{ji_qc1.id}/resolve/"), {}, format="json").status_code, 404)
        self.assertEqual(self.qc2.post(self.f.url(f"issues/{ji_qc1.id}/reopen/"), {}, format="json").status_code, 404)

        # P0-1b: Dual QC1+QC2 who was qc1_reviewer on a job CANNOT bypass PENDING_QC2 stage lock
        dual_qc = User.objects.create_user(username="dual_qc_audit", password="x")
        RoleAssignment.objects.create(project=self.f.project, user=dual_qc, role=Role.QC1)
        RoleAssignment.objects.create(project=self.f.project, user=dual_qc, role=Role.QC2)
        dual_qc_client = self.f.client(dual_qc)
        job_pqc2 = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, qc1_reviewer=dual_qc, cvat_job_id=8102)
        ji_pqc2 = JobIssue.objects.create(
            project=self.f.project,
            job=job_pqc2,
            cvat_issue_id=81021,
            defect_code="DIM-SIZE",
            primary_category="E3",
            severity="major",
            frame_number=1,
            author=dual_qc,
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.ADDRESSED,
        )
        self.assertEqual(dual_qc_client.post(self.f.url(f"issues/{ji_pqc2.id}/resolve/"), {}, format="json").status_code, 403)

        # P0-2: Dual PM+Annotator cannot self-void unlinked ERROR_DISPUTE (403) and DELIVERED unlinked dispute blocked (400)
        RoleAssignment.objects.create(project=self.f.project, user=self.f.pm, role=Role.ANNOTATOR)
        pm_ann_job = self.f.job(status=JobStatus.REWORK, annotator=self.f.pm, qc1_reviewer=self.f.qc1)
        manual_err = ReviewError.objects.create(
            job=pm_ann_job,
            stage=ReviewStage.QC1,
            rework_round=0,
            category=cat,
            severity="major",
            reported_by=self.f.qc1,
        )
        unlinked_req = AnnotatorRequest.objects.create(
            project=self.f.project,
            job=pm_ann_job,
            review_error=manual_err,
            request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
            title="Self dispute",
            reason="Dispute manual error",
            created_by=self.f.pm,
        )
        self.assertEqual(
            self.pm.post(
                self.f.url(f"annotator/requests/{unlinked_req.id}/resolve/"),
                {"status": AnnotatorRequest.Status.RESOLVED, "resolution_note": "Self void"},
                format="json",
            ).status_code,
            403,
        )
        delivered_job = self.f.job(status=JobStatus.DELIVERED, annotator=self.f.ann1, qc1_reviewer=self.f.qc1)
        deliv_err = ReviewError.objects.create(
            job=delivered_job,
            stage=ReviewStage.QC1,
            rework_round=0,
            category=cat,
            severity="major",
            reported_by=self.f.qc1,
        )
        deliv_req = AnnotatorRequest.objects.create(
            project=self.f.project,
            job=delivered_job,
            review_error=deliv_err,
            request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
            title="Delivered dispute",
            reason="Late dispute",
            created_by=self.f.ann1,
        )
        self.assertEqual(
            self.pm.post(
                self.f.url(f"annotator/requests/{deliv_req.id}/resolve/"),
                {"status": AnnotatorRequest.Status.RESOLVED, "resolution_note": "Post-delivery void"},
                format="json",
            ).status_code,
            400,
        )

        # P1-1 & P1-4: Inactive user [UNCLEAR] on unassigned job ignored; [ADDRESSED] Dispute on ADDRESSED creates dispute;
        # late opening comment backfill & 3D position swap tamper detection
        inactive_u = User.objects.create_user(username="inactive_cvat", password="x", is_active=False)
        CvatAccount.objects.create(user=inactive_u, cvat_user_id=9999, cvat_username="inactive_cvat")
        unassigned_job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=None, cvat_job_id=8103)
        snap_no_comment = CvatIssueSnapshot(
            fetched_at=timezone.now(),
            issues=[CvatIssuePayload.model_validate(_raw_issue(81031, job_id=8103, owner_id=9001, position=_pos3d(track_id=7)))],
            comments=[],
        )
        import_job_issues(unassigned_job.pk, project=self.f.project, prefetched=snap_no_comment)
        ji_late = JobIssue.objects.get(job=unassigned_job, cvat_issue_id=81031)
        self.assertIsNone(ji_late.first_comment_id)

        # Late opening comment + inactive [UNCLEAR] comment + 3D track swap
        snap_backfill = CvatIssueSnapshot(
            fetched_at=timezone.now() + timedelta(seconds=2),
            issues=[CvatIssuePayload.model_validate(_raw_issue(81031, job_id=8103, owner_id=9001, position=_pos3d(track_id=7)))],
            comments=[
                CvatCommentPayload.model_validate(_raw_comment(10, issue_id=81031, message="[EXI-MISS][critical] Missing", owner_id=9001)),
                CvatCommentPayload.model_validate(_raw_comment(11, issue_id=81031, message="[UNCLEAR] inactive spoof", owner_id=9999)),
            ],
        )
        import_job_issues(unassigned_job.pk, project=self.f.project, prefetched=snap_backfill)
        ji_late.refresh_from_db()
        self.assertEqual(ji_late.first_comment_id, 10)
        self.assertEqual(ji_late.defect_code, "EXI-MISS")
        self.assertEqual(ji_late.severity, "critical")
        self.assertEqual(ji_late.status, JobIssue.Status.OPEN)  # inactive [UNCLEAR] ignored!

        snap_swap = CvatIssueSnapshot(
            fetched_at=timezone.now() + timedelta(seconds=4),
            issues=[CvatIssuePayload.model_validate(_raw_issue(81031, job_id=8103, owner_id=9001, position=_pos3d(track_id=88)))],
            comments=[
                CvatCommentPayload.model_validate(_raw_comment(10, issue_id=81031, message="[EXI-MISS][critical] Missing", owner_id=9001)),
            ],
        )
        import_job_issues(unassigned_job.pk, project=self.f.project, prefetched=snap_swap)
        ji_late.refresh_from_db()
        self.assertTrue(ji_late.tampered)
        self.assertEqual(ji_late.tamper_reason, "position_3d_swapped")

        # [ADDRESSED] Dispute on already-ADDRESSED issue still creates dispute (9003=qc1, 9004=ann1)
        job_disp = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, qc1_reviewer=self.f.qc1, cvat_job_id=8104)
        snap_d1 = CvatIssueSnapshot(
            fetched_at=timezone.now(),
            issues=[CvatIssuePayload.model_validate(_raw_issue(81041, job_id=8104, owner_id=9003))],
            comments=[
                CvatCommentPayload.model_validate(_raw_comment(20, issue_id=81041, message="[DIM-SIZE][major] Box", owner_id=9003)),
                CvatCommentPayload.model_validate(_raw_comment(21, issue_id=81041, message="[ADDRESSED] Fixed", owner_id=9004)),
            ],
        )
        import_job_issues(job_disp.pk, project=self.f.project, prefetched=snap_d1)
        ji_d = JobIssue.objects.get(job=job_disp, cvat_issue_id=81041)
        self.assertEqual(ji_d.status, JobIssue.Status.ADDRESSED)
        snap_d2 = CvatIssueSnapshot(
            fetched_at=timezone.now() + timedelta(seconds=2),
            issues=[CvatIssuePayload.model_validate(_raw_issue(81041, job_id=8104, owner_id=9003))],
            comments=[
                CvatCommentPayload.model_validate(_raw_comment(20, issue_id=81041, message="[DIM-SIZE][major] Box", owner_id=9003)),
                CvatCommentPayload.model_validate(_raw_comment(21, issue_id=81041, message="[ADDRESSED] Fixed", owner_id=9004)),
                CvatCommentPayload.model_validate(_raw_comment(22, issue_id=81041, message="[ADDRESSED] Dispute: size ok", owner_id=9004)),
            ],
        )
        import_job_issues(job_disp.pk, project=self.f.project, prefetched=snap_d2)
        ji_d.refresh_from_db()
        self.assertTrue(ji_d.is_disputed)
        self.assertEqual(ji_d.status, JobIssue.Status.UNCLEAR)

        # P1-2: DATA_ISSUE rejects job_issue; PM ruling does NOT close DATA_ISSUE; cannot dispute RESOLVED issue
        self.assertEqual(
            self.ann1.post(
                self.f.url("annotator/requests/"),
                {
                    "job": job_disp.id,
                    "job_issue": ji_d.id,
                    "request_type": AnnotatorRequest.RequestType.DATA_ISSUE,
                    "reason": "Corrupt PCD file",
                },
                format="json",
            ).status_code,
            400,
        )
        data_req = AnnotatorRequest.objects.create(
            project=self.f.project,
            job=job_disp,
            request_type=AnnotatorRequest.RequestType.DATA_ISSUE,
            title="Corrupt PCD",
            reason="Corrupt PCD file",
            created_by=self.f.ann1,
        )
        # P2-6: PM decision='ruling' on disputed issue without dispute_outcome closes dispute cleanly & leaves DATA_ISSUE untouched
        self.assertEqual(
            self.pm.post(
                self.f.url(f"issues/{ji_d.id}/rule/"),
                {"decision": "ruling", "ruling_label": "car", "ruling_note": "Keep car"},
                format="json",
            ).status_code,
            200,
        )
        ji_d.refresh_from_db()
        data_req.refresh_from_db()
        self.assertFalse(ji_d.is_disputed)
        self.assertEqual(ji_d.status, JobIssue.Status.OPEN)
        self.assertEqual(data_req.status, AnnotatorRequest.Status.PENDING_PM)

        # Resolve ji_d then ensure annotator cannot dispute a RESOLVED issue via /annotator/requests/
        self.assertEqual(self.pm.post(self.f.url(f"issues/{ji_d.id}/resolve/"), {}, format="json").status_code, 200)
        self.assertEqual(
            self.ann1.post(
                self.f.url("annotator/requests/"),
                {
                    "job": job_disp.id,
                    "job_issue": ji_d.id,
                    "request_type": AnnotatorRequest.RequestType.ERROR_DISPUTE,
                    "reason": "Disputing already resolved issue",
                },
                format="json",
            ).status_code,
            400,
        )

        # P1-1 & P1-5: Non-PM QC1 cannot resolve unruled clarification & QC1 reject cannot cite unruled clarification
        job_clar = self.f.job(status=JobStatus.QC1_REVIEWING, annotator=self.f.ann1, qc1_reviewer=self.f.qc1, cvat_job_id=8105)
        ji_clar = JobIssue.objects.create(
            project=self.f.project,
            job=job_clar,
            cvat_issue_id=81051,
            defect_code="CLS-UNK",
            primary_category="E2",
            severity="major",
            is_clarification=True,
            frame_number=0,
            author=self.f.ann1,
            author_stage=JobIssue.AuthorStage.ANNOTATOR,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.UNCLEAR,
        )
        self.assertEqual(self.qc1.post(self.f.url(f"issues/{ji_clar.id}/resolve/"), {}, format="json").status_code, 400)
        self.assertEqual(self.qc1.post(self.f.url(f"issues/{ji_clar.id}/reopen/"), {}, format="json").status_code, 400)
        self.assertEqual(
            self.qc1.post(
                self.f.url(f"qc1/jobs/{job_clar.id}/reject/"),
                {"errors": [{"category": cat.id, "job_issue": ji_clar.id}]},
                format="json",
            ).status_code,
            400,
        )

        # P1-3: Qc1SummaryView pool_pending excludes jobs where user authored valid QC2 JobIssue
        pool_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2, qc1_reviewer=None, cvat_job_id=8106)
        before_sum = dual_qc_client.get(self.f.url("qc1-summary/?scope=mine")).data["stats"]["pool_pending"]
        JobIssue.objects.create(
            project=self.f.project,
            job=pool_job,
            cvat_issue_id=81061,
            defect_code="GEO-HDG",
            primary_category="E3",
            severity="major",
            frame_number=0,
            author=dual_qc,
            author_stage=JobIssue.AuthorStage.QC2,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.OPEN,
        )
        after_sum = dual_qc_client.get(self.f.url("qc1-summary/?scope=mine")).data["stats"]["pool_pending"]
        self.assertEqual(after_sum, before_sum - 1)

        # P2-1 & P2-3: DeliveryViewSet.candidates reflects blocking_issues & primary_category actually filters issues
        from projects.models import Batch

        cand_batch = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="Cand-Batch")
        cand_job = self.f.job(batch=cand_batch, status=JobStatus.APPROVED, annotator=self.f.ann1, qc1_reviewer=self.f.qc1)
        Audit.objects.create(
            project=self.f.project,
            batch=cand_batch,
            status=Audit.Status.IN_PROGRESS,
            method="random",
            sampling_rate=20,
            seed=1,
            eligible_count=1,
        )
        cand_ji = JobIssue.objects.create(
            project=self.f.project,
            job=cand_job,
            cvat_issue_id=81071,
            defect_code="EXI-MISS",
            primary_category="E1",
            severity="critical",
            frame_number=0,
            author=self.f.qc2,
            author_stage=JobIssue.AuthorStage.QC2,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.OPEN,
        )
        cands = self.pm.get(self.f.url("deliveries/candidates/")).data
        cand_row = next(r for r in cands if r["batch"] == cand_batch.id)
        self.assertFalse(cand_row["ready"])
        self.assertEqual(cand_row["blocking_issues"], 1)
        # primary_category filter check: E1 returns 1, E2 returns 0 for cand_job
        self.assertEqual(self.pm.get(self.f.url(f"issues/?job={cand_job.id}&primary_category=E1")).data["count"], 1)
        self.assertEqual(self.pm.get(self.f.url(f"issues/?job={cand_job.id}&primary_category=E2")).data["count"], 0)
        # Suppress unused variable lint
        self.assertIsNotNone(AuditSample.objects)
        self.assertIsNotNone(cand_ji.pk)

    def test_slice4_issue_rule_pq01_scoping_and_import_error_paths(self) -> None:
        from unittest.mock import patch

        from accounts.models import Role, RoleAssignment
        from cvat_integration.client import CvatError

        # 1. PM rule direct not_an_issue, resolved, DELIVERED (400), invalid ruling_attributes (400), dual PM+Anno (403)
        job_active = self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1, qc1_reviewer=self.f.qc1, cvat_job_id=9201)
        ji_na = JobIssue.objects.create(
            project=self.f.project,
            job=job_active,
            cvat_issue_id=92011,
            defect_code="LBL-01",
            severity="major",
            frame_number=0,
            author=self.f.qc1,
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.OPEN,
        )
        r_bad_attrs = self.pm.post(
            self.f.url(f"issues/{ji_na.id}/rule/"),
            {"decision": "ruling", "ruling_label": "Car", "ruling_attributes": {"nested": {"bad": 1}}},
            format="json",
        )
        self.assertEqual(r_bad_attrs.status_code, 400)

        r_na = self.pm.post(
            self.f.url(f"issues/{ji_na.id}/rule/"),
            {"decision": "not_an_issue", "ruling_note": "False positive"},
            format="json",
        )
        self.assertEqual(r_na.status_code, 200, r_na.data)
        self.assertEqual(r_na.data["status"], JobIssue.Status.NOT_AN_ISSUE)

        ji_res = JobIssue.objects.create(
            project=self.f.project,
            job=job_active,
            cvat_issue_id=92012,
            defect_code="LBL-01",
            severity="major",
            frame_number=1,
            author=self.f.qc1,
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.OPEN,
        )
        r_res = self.pm.post(
            self.f.url(f"issues/{ji_res.id}/rule/"),
            {"decision": "resolved", "ruling_note": "Confirmed fixed"},
            format="json",
        )
        self.assertEqual(r_res.status_code, 200, r_res.data)
        self.assertEqual(r_res.data["status"], JobIssue.Status.RESOLVED)

        job_deliv = self.f.job(status=JobStatus.DELIVERED, annotator=self.f.ann1, qc1_reviewer=self.f.qc1, cvat_job_id=9202)
        ji_deliv = JobIssue.objects.create(
            project=self.f.project,
            job=job_deliv,
            cvat_issue_id=92021,
            defect_code="LBL-01",
            severity="major",
            frame_number=0,
            author=self.f.qc1,
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.OPEN,
        )
        self.assertEqual(
            self.pm.post(self.f.url(f"issues/{ji_deliv.id}/rule/"), {"decision": "resolved"}, format="json").status_code,
            400,
        )

        # Dual PM+Annotator blocked 403 on rule not_an_issue for own annotated job
        RoleAssignment.objects.create(project=self.f.project, user=self.f.pm, role=Role.ANNOTATOR)
        job_pm_ann = self.f.job(status=JobStatus.REWORK, annotator=self.f.pm, qc1_reviewer=self.f.qc1, cvat_job_id=9203)
        ji_pm_ann = JobIssue.objects.create(
            project=self.f.project,
            job=job_pm_ann,
            cvat_issue_id=92031,
            defect_code="LBL-01",
            severity="major",
            frame_number=0,
            author=self.f.qc1,
            author_stage=JobIssue.AuthorStage.QC1,
            authority_status=JobIssue.AuthorityStatus.VALID,
            status=JobIssue.Status.OPEN,
        )
        self.assertEqual(
            self.pm.post(self.f.url(f"issues/{ji_pm_ann.id}/rule/"), {"decision": "not_an_issue"}, format="json").status_code,
            403,
        )

        # 2. PQ01 scoping on GET /issues/ for Ann / QC1 / QC2
        ann2_ids = [r["id"] for r in self.f.client(self.f.ann2).get(self.f.url("issues/")).data["results"]]
        self.assertNotIn(ji_na.id, ann2_ids)
        ann1_ids = [r["id"] for r in self.ann1.get(self.f.url("issues/")).data["results"]]
        self.assertIn(ji_na.id, ann1_ids)
        self.assertNotIn(ji_pm_ann.id, ann1_ids)
        qc2_ids = [r["id"] for r in self.qc2.get(self.f.url("issues/")).data["results"]]
        self.assertNotIn(ji_na.id, qc2_ids)

        # 3. import_ 403 (unauthorized job), 400 (unlinked CVAT job), 502 (CvatError)
        self.assertEqual(
            self.f.client(self.f.ann2).post(self.f.url("issues/import/"), {"job": job_active.id}, format="json").status_code,
            403,
        )
        unlinked_job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=None)
        self.assertEqual(
            self.pm.post(self.f.url("issues/import/"), {"job": unlinked_job.id}, format="json").status_code,
            400,
        )
        with patch("quality.views.import_job_issues", side_effect=CvatError("cvat timeout")):
            res_502 = self.pm.post(self.f.url("issues/import/"), {"job": job_active.id}, format="json")
        self.assertEqual(res_502.status_code, 502)
