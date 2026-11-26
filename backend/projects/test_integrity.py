from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from accounts.testing import ProjectFixture
from jobs.models import DailyOutputRecord, JobStatus
from projects.models import Batch, Project, SamplingMethod
from quality.models import Audit, ReviewError, ReviewStage
from teams.models import Team, TeamMember


class DatabaseIntegrityAndBoundaryTests(TestCase):
    """Layers 2–4: DRF boundary validation, application invariants, and DB CheckConstraints."""

    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)

    def test_db_rejects_invalid_project_sampling_rate_and_wip_limit(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Project.objects.create(name="Bad Rate", sampling_rate=0)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Project.objects.create(name="Bad WIP", annotator_wip_limit=99)

    def test_db_rejects_invalid_team_capacity_and_completed_audit_without_decision(self):
        team = Team.objects.create(project=self.f.project, name="T1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            TeamMember.objects.create(team=team, user=self.f.ann1, capacity=0)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Audit.objects.create(
                project=self.f.project,
                batch=self.f.batch,
                status=Audit.Status.COMPLETED,
                decision="",
                method=SamplingMethod.RANDOM,
                sampling_rate=20,
                seed=1,
                eligible_count=1,
            )

    def test_audit_clean_enforces_application_invariants(self):
        audit = Audit(
            project=self.f.project,
            batch=self.f.batch,
            status=Audit.Status.COMPLETED,
            decision="",
            method=SamplingMethod.RANDOM,
            sampling_rate=150,
            seed=1,
            eligible_count=1,
        )
        with self.assertRaises(DjangoValidationError) as ctx:
            audit.clean()
        self.assertIn("sampling_rate", ctx.exception.message_dict)

    def test_drf_boundaries_reject_invalid_payloads(self):
        # import-cvat rejects invalid/non-positive task IDs
        r1 = self.pm.post(self.f.url(f"batches/{self.f.batch.id}/import-cvat/"), {"cvat_task_id": 0}, format="json")
        self.assertEqual(r1.status_code, 400)

        # notifications/mark-read rejects non-integer notification_id
        r2 = self.pm.post(self.f.url("notifications/mark-read/"), {"notification_id": "abc"}, format="json")
        self.assertEqual(r2.status_code, 400)

        # member role endpoint rejects disallowed roles
        r3 = self.pm.post(self.f.url(f"members/{self.f.ann1.id}/roles/"), {"role": "project_manager"}, format="json")
        self.assertEqual(r3.status_code, 400)

    def test_db_enforces_unique_cvat_task_id_valid_verdict_and_positive_daily_output(self):
        from django.utils import timezone

        self.f.batch.cvat_task_id = 777
        self.f.batch.save(update_fields=["cvat_task_id"])
        with self.assertRaises(IntegrityError), transaction.atomic():
            Batch.objects.create(dataset=self.f.dataset, name="Dup Task", cvat_task_id=777)

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

        with self.assertRaises(IntegrityError), transaction.atomic():
            DailyOutputRecord.objects.create(
                project=self.f.project,
                job=job,
                user=self.f.ann1,
                work_date=timezone.localdate(),
                object_count=0,
            )
