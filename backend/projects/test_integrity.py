from pathlib import Path

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from jobs.models import AnnotatorRequest, DailyOutputRecord, Job, JobStatus
from projects.models import Batch, Delivery, Project, SamplingMethod
from quality.models import (
    Audit,
    AuditSample,
    ErrorCategory,
    ErrorVerdict,
    JobIssue,
    PrimaryCategory,
    ReviewError,
    ReviewStage,
    Severity,
)
from teams.models import Team, TeamMember


class DatabaseIntegrityAndBoundaryTests(TestCase):
    """Layers 2–4: DRF boundary validation, application invariants, and DB CheckConstraints."""

    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)

    def test_db_rejects_invalid_project_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Project.objects.create(name="Bad Rate", sampling_rate=0)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Project.objects.create(name="Bad WIP", annotator_wip_limit=99)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Project.objects.create(name="Bad Rework", max_rework_rounds=0)

    def test_db_rejects_invalid_team_capacity_and_four_eyes_job(self):
        team = Team.objects.create(project=self.f.project, name="T1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMember.objects.create(team=team, user=self.f.ann1, capacity=0)

        dual = make_user("dual_constraint", Role.ANNOTATOR, Role.QC1, project=self.f.project)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Job.objects.create(
                project=self.f.project,
                dataset=self.f.dataset,
                batch=self.f.batch,
                name="FourEyesViolation",
                annotator=dual,
                qc1_reviewer=dual,
            )

    def test_db_enforces_unique_delivery_audit_and_pending_sample_constraints(self):
        Delivery.objects.create(
            project=self.f.project,
            batch=self.f.batch,
            recipient="Client A",
            output_path="s3://bucket/a",
            delivered_by=self.f.pm,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Delivery.objects.create(
                project=self.f.project,
                batch=self.f.batch,
                recipient="Client B",
                output_path="s3://bucket/b",
                delivered_by=self.f.pm,
            )

        audit = Audit.objects.create(
            project=self.f.project,
            batch=self.f.batch,
            status=Audit.Status.IN_PROGRESS,
            method=SamplingMethod.RANDOM,
            sampling_rate=20,
            seed=1,
            eligible_count=1,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Audit.objects.create(
                project=self.f.project,
                batch=self.f.batch,
                status=Audit.Status.IN_PROGRESS,
                method=SamplingMethod.RANDOM,
                sampling_rate=20,
                seed=2,
                eligible_count=1,
            )

        job = self.f.job(status=JobStatus.PENDING_QC2)
        AuditSample.objects.create(audit=audit, job=job, result=AuditSample.Result.PENDING, frames=[0])
        with self.assertRaises(IntegrityError), transaction.atomic():
            AuditSample.objects.create(audit=audit, job=job, result=AuditSample.Result.PENDING, frames=[1])

    def test_audit_clean_enforces_application_invariants(self):
        audit = Audit(
            project=self.f.project,
            batch=self.f.batch,
            status=Audit.Status.COMPLETED,
            method=SamplingMethod.RANDOM,
            sampling_rate=150,
            seed=1,
            eligible_count=1,
        )
        with self.assertRaises(DjangoValidationError) as ctx:
            audit.clean()
        self.assertIn("sampling_rate", ctx.exception.message_dict)

    def test_drf_boundaries_reject_invalid_payloads(self):
        # settings rejects max_rework_rounds=0
        r_settings = self.pm.patch(self.f.url("settings/"), {"max_rework_rounds": 0}, format="json")
        self.assertEqual(r_settings.status_code, 400)

        # project update rejects empty pm_ids
        r_pms = self.pm.patch(f"/api/projects/{self.f.project.id}/", {"pm_ids": []}, format="json")
        self.assertEqual(r_pms.status_code, 400)

        # notifications/mark-read rejects non-integer notification_id
        r_notif = self.pm.post(self.f.url("notifications/mark-read/"), {"notification_id": "abc"}, format="json")
        self.assertEqual(r_notif.status_code, 400)

        # member role endpoint rejects disallowed roles
        r_role = self.pm.post(self.f.url(f"members/{self.f.ann1.id}/roles/"), {"role": "project_manager"}, format="json")
        self.assertEqual(r_role.status_code, 400)

        # delivery requires recipient and output_path
        self.f.job(status=JobStatus.APPROVED)
        r_delivery = self.pm.post(self.f.url("deliveries/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(r_delivery.status_code, 400)

    def test_confirm_qc2_creates_samples_and_rejects_locked_jobs(self):
        j1 = self.f.job(status=JobStatus.QC1_PASSED, is_locked=True, frame_count=10)
        j2 = self.f.job(status=JobStatus.QC1_PASSED, is_locked=False, frame_count=10)

        blocked = self.pm.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        self.assertEqual(blocked.status_code, 400)

        Job.objects.filter(pk=j1.pk).update(is_locked=False)
        ok = self.pm.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {"note": "ready"}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(AuditSample.objects.filter(job=j1, result=AuditSample.Result.PENDING).count(), 1)
        self.assertEqual(AuditSample.objects.filter(job=j2, result=AuditSample.Result.PENDING).count(), 1)

    def test_db_enforces_unique_cvat_task_id_valid_verdict_missing_object_and_positive_daily_output(self):
        self.f.batch.cvat_task_id = 777
        self.f.batch.save(update_fields=["cvat_task_id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="Dup Task", cvat_task_id=777)

        job = self.f.job(status=JobStatus.REWORK)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewError.objects.create(
                job=job,
                stage=ReviewStage.QC1,
                rework_round=0,
                category=self.f.category,
                severity="minor",
                verdict="invalid",
            )

        # is_missing_object=True requires cvat_object_id=None and verdict=FAIL
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewError.objects.create(
                job=job,
                stage=ReviewStage.QC1,
                rework_round=0,
                category=self.f.category,
                severity="major",
                verdict=ErrorVerdict.FAIL,
                cvat_object_id=12,
                is_missing_object=True,
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewError.objects.create(
                job=job,
                stage=ReviewStage.QC1,
                rework_round=0,
                category=self.f.category,
                severity="major",
                verdict=ErrorVerdict.EDGE,
                cvat_object_id=None,
                is_missing_object=True,
            )

        with self.assertRaises(IntegrityError), transaction.atomic():
            DailyOutputRecord.objects.create(
                project=self.f.project,
                job=job,
                user=self.f.ann1,
                work_date=timezone.localdate(),
                object_count=0,
            )

    def test_db_enforces_error_category_job_issue_review_error_and_request_constraints(self):
        # Partial unique code allows multiple blank codes per project, rejects duplicate non-empty codes.
        c_blank_a = ErrorCategory.objects.create(project=self.f.project, name="Blank A", code="")
        c_blank_b = ErrorCategory.objects.create(project=self.f.project, name="Blank B", code="")
        self.assertNotEqual(c_blank_a.pk, c_blank_b.pk)
        ErrorCategory.objects.create(
            project=self.f.project,
            name="Missing",
            code="E1",
            primary_category=PrimaryCategory.E1,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ErrorCategory.objects.create(
                project=self.f.project,
                name="Duplicate E1",
                code="E1",
                primary_category=PrimaryCategory.E1,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ErrorCategory.objects.create(
                project=self.f.project,
                name="Bad Primary",
                primary_category="E9",
            )

        # Other project can still use code E1.
        other_project = Project.objects.create(name="Other P")
        other_cat = ErrorCategory.objects.create(
            project=other_project,
            name="Other E1",
            code="E1",
            primary_category=PrimaryCategory.E1,
        )
        self.assertEqual(other_cat.code, "E1")

        job1 = self.f.job(status=JobStatus.ANNOTATING)
        job2 = self.f.job(status=JobStatus.ANNOTATING)
        ji = JobIssue.objects.create(
            project=self.f.project,
            job=job1,
            cvat_issue_id=501,
            severity=Severity.MAJOR,
            primary_category=PrimaryCategory.E1,
            frame_number=10,
            frame_start=10,
            frame_end=15,
            message="Missing box",
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobIssue.objects.create(project=self.f.project, job=job1, cvat_issue_id=501)
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobIssue.objects.create(project=self.f.project, job=job2, cvat_issue_id=0)
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobIssue.objects.create(
                project=self.f.project,
                job=job2,
                cvat_issue_id=502,
                frame_start=20,
                frame_end=10,
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobIssue.objects.create(project=self.f.project, job=job2, cvat_issue_id=503, status="bogus")

        # JobIssue.clean() rejects cross-project job
        with self.assertRaises(DjangoValidationError):
            JobIssue(project=other_project, job=job1, cvat_issue_id=504).full_clean()

        # ReviewError unique per (job, stage, rework_round, cvat_issue_id) when not null
        ReviewError.objects.create(
            job=job1,
            stage=ReviewStage.QC1,
            rework_round=0,
            job_issue=ji,
            cvat_issue_id=ji.cvat_issue_id,
            category=self.f.category,
            severity=Severity.MAJOR,
            verdict=ErrorVerdict.FAIL,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            ReviewError.objects.create(
                job=job1,
                stage=ReviewStage.QC1,
                rework_round=0,
                category=self.f.category,
                severity=Severity.MAJOR,
                verdict=ErrorVerdict.FAIL,
                cvat_issue_id=ji.cvat_issue_id,
            )
        with self.assertRaises(DjangoValidationError):
            ReviewError(
                job=job2,
                stage=ReviewStage.QC1,
                rework_round=0,
                job_issue=ji,
                cvat_issue_id=ji.cvat_issue_id,
                category=self.f.category,
                severity=Severity.MAJOR,
                verdict=ErrorVerdict.FAIL,
            ).full_clean()

        with self.assertRaises(DjangoValidationError):
            AnnotatorRequest(
                project=self.f.project,
                job=job2,
                job_issue=ji,
                request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
                title="Cross-job dispute",
                reason="Invalid cross-job link",
                created_by=self.f.ann1,
            ).full_clean()


class ExternalCvatExtensionDecouplingTests(SimpleTestCase):
    """Enforce PV04 / D04 invariant: VanoHub stays completely decoupled from cvat-di-ext."""

    FORBIDDEN_TOKENS = ("cvat-di-ext", "cvat_ext")
    SCANNED_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".scss", ".css"})
    IGNORED_DIRS = frozenset({"__pycache__", "node_modules", "dist", ".venv", ".git"})

    def test_runtime_code_and_repo_exclude_cvat_di_ext(self):
        this_file = Path(__file__).resolve()
        repo_root = this_file.parents[2]

        self.assertFalse(
            (repo_root / "issue-logging-management" / "cvat-di-ext").exists(),
            "issue-logging-management/cvat-di-ext must not be vendored inside VanoHub.",
        )

        offenders: list[str] = []
        for root in (repo_root / "backend", repo_root / "frontend" / "src"):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.resolve() == this_file:
                    continue
                if any(part in self.IGNORED_DIRS for part in path.parts):
                    continue
                if path.suffix.lower() not in self.SCANNED_SUFFIXES:
                    continue
                content = path.read_text(encoding="utf-8", errors="ignore").lower()
                for token in self.FORBIDDEN_TOKENS:
                    if token in content:
                        offenders.append(f"{path.relative_to(repo_root)} ({token})")

        self.assertEqual(offenders, [], f"Forbidden external CVAT extension coupling detected: {offenders}")
