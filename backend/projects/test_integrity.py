from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from jobs.models import DailyOutputRecord, Job, JobStatus
from projects.models import Batch, Delivery, Project, SamplingMethod
from quality.models import Audit, AuditSample, ErrorVerdict, ReviewError, ReviewStage
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
