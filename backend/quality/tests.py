from types import SimpleNamespace

from django.test import TestCase

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from jobs.models import Job, JobStatus

from . import sampling
from .models import Audit, AuditSample, ReviewError


class SamplingTests(TestCase):
    def test_sample_size_rounds_up_and_has_minimum_one(self):
        self.assertEqual(sampling.sample_size(10, 10), 1)
        self.assertEqual(sampling.sample_size(11, 10), 2)
        self.assertEqual(sampling.sample_size(3, 1), 1)
        self.assertEqual(sampling.sample_size(0, 50), 0)

    def test_same_seed_gives_same_sample(self):
        items = list(range(100))
        self.assertEqual(sampling.random_sample(items, 10, 42), sampling.random_sample(items, 10, 42))

    def test_stratified_covers_every_stratum(self):
        items = [("a", i) for i in range(10)] + [("b", i) for i in range(2)]
        picked = sampling.stratified_sample(items, 10, 1, key=lambda x: x[0])
        self.assertEqual({stratum for _, stratum in picked}, {"a", "b"})

    def test_assign_auditors_respects_four_eyes(self):
        a, b = SimpleNamespace(pk=1), SimpleNamespace(pk=2)
        result = sampling.assign_auditors(["x", "y"], [a, b], conflicts=lambda item: {1} if item == "x" else set())
        self.assertEqual(result["x"].pk, 2)
        only_conflicted = sampling.assign_auditors(["x"], [a], conflicts=lambda item: {1})
        self.assertIsNone(only_conflicted["x"])


class AuditFlowTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.jobs = [self.f.job() for _ in range(6)]
        self.pm = self.f.client(self.f.pm)
        self.qc2 = self.f.client(self.f.qc2)

    def _create_audit(self, **data):
        body = {"batch": self.f.batch.id, "auditors": [self.f.qc2.id], **data}
        response = self.pm.post(self.f.url("audits/"), body, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return Audit.objects.get(pk=response.data["id"])

    def test_qc2_only_cannot_create_audit(self):
        response = self.qc2.post(self.f.url("audits/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_preview_seed_reproduces_created_sample(self):
        preview = self.pm.post(self.f.url("audits/preview/"), {"batch": self.f.batch.id}, format="json").data
        audit = self._create_audit(seed=preview["seed"])
        self.assertEqual(
            sorted(s["job"]["id"] for s in preview["samples"]),
            sorted(audit.samples.values_list("job_id", flat=True)),
        )
        self.assertEqual(audit.eligible_count, 6)
        self.assertEqual(audit.samples.count(), 3)  # 50% của 6

    def test_qc2_sees_only_own_samples_and_can_pass(self):
        audit = self._create_audit()
        sample = audit.samples.first()
        listed = self.qc2.get(self.f.url("audit-samples/")).data
        self.assertEqual(len(listed), 3)
        response = self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        sample.job.refresh_from_db()
        self.assertEqual(sample.job.status, JobStatus.APPROVED)

    def test_reject_records_errors_and_sends_job_to_rework(self):
        audit = self._create_audit()
        sample = audit.samples.first()
        body = {"errors": [{"category": self.f.category.id, "location": "frame 12 / obj 3"}], "comment": "x"}
        response = self.qc2.post(self.f.url(f"audit-samples/{sample.id}/reject/"), body, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        job = Job.objects.get(pk=sample.job_id)
        self.assertEqual(job.status, JobStatus.REWORK)
        self.assertEqual(job.rework_round, 1)
        self.assertEqual(ReviewError.objects.filter(job=job, stage="qc2").count(), 1)

    def test_reject_without_errors_is_refused(self):
        sample = self._create_audit().samples.first()
        response = self.qc2.post(self.f.url(f"audit-samples/{sample.id}/reject/"), {"errors": []}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_exceeding_max_rework_rounds_escalates(self):
        Job.objects.filter(pk__in=[j.pk for j in self.jobs]).update(rework_round=2)
        sample = self._create_audit().samples.first()
        body = {"errors": [{"category": self.f.category.id}]}
        self.qc2.post(self.f.url(f"audit-samples/{sample.id}/reject/"), body, format="json")
        self.assertTrue(Job.objects.get(pk=sample.job_id).is_escalated)

    def test_four_eyes_blocks_auditing_own_annotation(self):
        # PM vừa là annotator của job → không được audit job đó.
        make_user("dual", Role.ANNOTATOR, project=self.f.project)
        audit = self._create_audit()
        sample = audit.samples.first()
        Job.objects.filter(pk=sample.job_id).update(annotator=self.f.pm)
        response = self.pm.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_qc2_cannot_review_sample_assigned_to_someone_else(self):
        other = make_user("qc2_other", Role.QC2, project=self.f.project)
        sample = self._create_audit().samples.first()
        AuditSample.objects.filter(pk=sample.pk).update(auditor=other)
        response = self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json")
        self.assertIn(response.status_code, (403, 404))

    def test_complete_requires_all_samples_and_approves_unsampled(self):
        audit = self._create_audit()
        self.assertEqual(self.pm.post(self.f.url(f"audits/{audit.id}/complete/")).status_code, 400)
        for sample in audit.samples.all():
            self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json")
        late_job = self.f.job()  # vào hàng chờ QC2 SAU khi tạo audit
        response = self.pm.post(self.f.url(f"audits/{audit.id}/complete/"))
        self.assertEqual(response.status_code, 200, response.data)
        statuses = set(Job.objects.filter(pk__in=[j.pk for j in self.jobs]).values_list("status", flat=True))
        self.assertEqual(statuses, {JobStatus.APPROVED})
        late_job.refresh_from_db()
        self.assertEqual(late_job.status, JobStatus.PENDING_QC2)

    def test_cannot_open_two_audits_on_same_batch(self):
        self._create_audit()
        response = self.pm.post(self.f.url("audits/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_qc2_only_can_read_error_categories_but_not_edit(self):
        self.assertEqual(self.qc2.get(self.f.url("error-categories/")).status_code, 200)
        response = self.qc2.post(self.f.url("error-categories/"), {"name": "X"}, format="json")
        self.assertEqual(response.status_code, 403)


class DeletionRulesTests(TestCase):
    """Loại lỗi đang được dùng không xoá riêng được, nhưng xoá cả dự án thì được."""

    def setUp(self):
        self.f = ProjectFixture()
        job = self.f.job()
        ReviewError.objects.create(job=job, stage="qc2", rework_round=0, category=self.f.category, severity="minor")

    def test_category_in_use_cannot_be_deleted(self):
        from django.db.models import RestrictedError

        with self.assertRaises(RestrictedError):
            self.f.category.delete()

    def test_project_with_review_errors_can_be_deleted(self):
        self.f.project.delete()
        self.assertFalse(ReviewError.objects.exists())


class Qc2ScreensTests(TestCase):
    """Mọi tài khoản QC2 có Tổng quan (số liệu của mình). Trong mục Chất lượng, QC2 chuyên trách chỉ có
    danh sách job được PM phân công — chiến thuật audit / xem trước mẫu chỉ dành cho PM."""

    def setUp(self):
        self.f = ProjectFixture()
        self.jobs = [self.f.job() for _ in range(6)]
        self.pm = self.f.client(self.f.pm)
        self.qc2 = self.f.client(self.f.qc2)

    def test_qc2_only_sees_own_dashboard_but_no_strategy_or_preview(self):
        summary = self.qc2.get(self.f.url("qc2-summary/"))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["scope"], "mine")
        self.assertEqual(self.qc2.get(self.f.url("audit-strategy/")).status_code, 403)
        response = self.qc2.post(self.f.url("audits/preview/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_qc2_only_still_lists_assigned_samples(self):
        self.pm.post(self.f.url("audits/"), {"batch": self.f.batch.id, "auditors": [self.f.qc2.id]}, format="json")
        response = self.qc2.get(self.f.url("audit-samples/?open=1&result=pending"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 3)

    def test_pm_strategy_with_history(self):
        self.pm.patch(self.f.url("settings/"), {"sampling_rate": 20}, format="json")
        data = self.pm.get(self.f.url("audit-strategy/")).data
        self.assertTrue(data["can_edit"])
        self.assertEqual(data["history"][0]["after"], {"sampling_rate": 20})
        self.assertEqual(data["history"][0]["before"], {"sampling_rate": 50})
        self.assertEqual([b["id"] for b in data["preview_batches"]], [self.f.batch.id])

    def test_pm_summary_has_kpi_comparison_and_trend(self):
        response = self.pm.post(self.f.url("audits/"), {"batch": self.f.batch.id, "auditors": [self.f.qc2.id]}, format="json")
        sample = Audit.objects.get(pk=response.data["id"]).samples.first()
        self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json")
        data = self.pm.get(self.f.url("qc2-summary/?period=week")).data
        self.assertEqual(data["kpi"]["current"]["passed"], 1)
        self.assertEqual(data["kpi"]["previous"]["audited"], 0)
        self.assertEqual(len(data["trend"]), 7)
        self.assertEqual(data["trend"][-1]["audited"], 1)
        self.assertEqual(data["audit_speed"]["status"], "pending_definition")
