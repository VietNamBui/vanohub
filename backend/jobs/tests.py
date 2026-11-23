from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from projects.models import ActivityLog

from .models import JobStatus


class JobManagementTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.job = self.f.job(status=JobStatus.ANNOTATING)
        self.pm = self.f.client(self.f.pm)

    def test_qc2_only_cannot_list_project_jobs(self):
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("jobs/")).status_code, 403)

    def test_pm_lists_and_filters_jobs(self):
        self.f.job(status=JobStatus.PENDING_QC2)
        data = self.pm.get(self.f.url("jobs/?stage=qc2")).data
        self.assertEqual(data["count"], 1)

    def test_reassign_logs_history(self):
        response = self.pm.post(self.f.url(f"jobs/{self.job.id}/assign/"), {"annotator": self.f.ann2.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["annotator"]["id"], self.f.ann2.id)
        self.assertTrue(ActivityLog.objects.filter(job=self.job, action="job.assign").exists())
        self.assertEqual(response.data["timeline"][-1]["action"], "job.assign")

    def test_annotator_must_have_annotator_role(self):
        response = self.pm.post(self.f.url(f"jobs/{self.job.id}/assign/"), {"annotator": self.f.qc2.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_four_eyes_qc1_cannot_be_annotator(self):
        both = make_user("both", Role.ANNOTATOR, Role.QC1, project=self.f.project)
        body = {"annotator": both.id, "qc1_reviewer": both.id}
        response = self.pm.post(self.f.url(f"jobs/{self.job.id}/assign/"), body, format="json")
        self.assertEqual(response.status_code, 400)

    def test_locked_job_cannot_be_reassigned(self):
        self.pm.post(self.f.url(f"jobs/{self.job.id}/lock/"))
        response = self.pm.post(self.f.url(f"jobs/{self.job.id}/assign/"), {"annotator": self.f.ann2.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_bulk_deadline_and_overdue_filter(self):
        other = self.f.job(status=JobStatus.PENDING_QC1)
        past = (timezone.now() - timedelta(hours=1)).isoformat()
        body = {"ids": [self.job.id, other.id], "deadline": past}
        self.assertEqual(self.pm.post(self.f.url("jobs/bulk-deadline/"), body, format="json").status_code, 200)
        self.assertEqual(self.pm.get(self.f.url("jobs/?overdue=1")).data["count"], 2)

    def test_resolve_escalation(self):
        self.job.is_escalated, self.job.rework_round = True, 3
        self.job.save()
        response = self.pm.post(self.f.url(f"jobs/{self.job.id}/resolve-escalation/"),
                                {"annotator": self.f.ann2.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["is_escalated"])
        self.assertEqual(response.data["rework_round"], 0)

    def test_job_queue_counts_by_stage(self):
        self.f.job(status=JobStatus.PENDING_QC2)
        data = self.pm.get(self.f.url("job-queue/")).data
        stages = {s["stage"]: s["total"] for s in data["stages"]}
        self.assertEqual(stages, {"annotation": 1, "qc1": 0, "qc2": 1})


class JobQc2ColumnTests(TestCase):
    def test_job_list_exposes_open_audit_sample_auditor(self):
        from accounts.testing import ProjectFixture

        f = ProjectFixture()
        jobs = [f.job() for _ in range(4)]
        pm = f.client(f.pm)
        audit = pm.post(f.url("audits/"), {"batch": f.batch.id, "auditors": [f.qc2.id]}, format="json")
        self.assertEqual(audit.status_code, 201, audit.data)
        rows = {r["id"]: r for r in pm.get(f.url("jobs/")).data["results"]}
        sampled = [r for r in rows.values() if r["qc2"]]
        self.assertEqual(len(sampled), 2)  # 50% của 4
        self.assertEqual(sampled[0]["qc2"]["auditor"]["id"], f.qc2.id)
        self.assertEqual(len([j for j in jobs if rows[j.id]["qc2"] is None]), 2)
