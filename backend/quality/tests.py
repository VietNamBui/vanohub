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


class Qc1WorkflowTests(TestCase):
    """Kiểm thử Level 1 QC: phân quyền, luật bốn mắt, pool tự nhận, pass/reject nguyên tử và escalation."""

    def setUp(self):
        self.f = ProjectFixture()
        self.job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)
        self.qc1 = self.f.client(self.f.qc1)
        self.ann1 = self.f.client(self.f.ann1)

    def test_annotator_and_qc2_only_cannot_use_qc1_api(self):
        self.assertEqual(self.ann1.get(self.f.url("qc1/jobs/")).status_code, 403)
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("qc1/jobs/")).status_code, 403)

    def test_team_leader_has_implied_qc1_capability(self):
        tl = make_user("tl_qc1", Role.TEAM_LEADER, project=self.f.project)
        pool_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)
        Job.objects.filter(pk=pool_job.pk).update(qc1_reviewer=None)

        client = self.f.client(tl)
        listed = client.get(self.f.url("qc1/jobs/?scope=pool")).data
        self.assertEqual([r["id"] for r in listed["results"]], [pool_job.id])

        passed = client.post(self.f.url(f"qc1/jobs/{pool_job.id}/pass/"), {"comment": "ok"}, format="json")
        self.assertEqual(passed.status_code, 200, passed.data)
        self.assertEqual(passed.data["status"], JobStatus.PENDING_QC2)
        self.assertEqual(passed.data["qc1_reviewer"]["id"], tl.id)

    def test_qc1_start_then_pass_transitions_to_pending_qc2(self):
        started = self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/start/"), {}, format="json")
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["status"], JobStatus.QC1_REVIEWING)

        passed = self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/pass/"), {"comment": "dat chuan"}, format="json")
        self.assertEqual(passed.status_code, 200, passed.data)
        self.assertEqual(passed.data["status"], JobStatus.PENDING_QC2)
        self.assertEqual([e["action"] for e in passed.data["timeline"]], ["qc1.start", "qc1.pass"])

    def test_qc1_reject_records_errors_increments_rework_and_escalates(self):
        from .models import ErrorCategory, ReviewStage

        qc2_only_cat = ErrorCategory.objects.create(
            project=self.f.project, name="Chi QC2", applies_to=ErrorCategory.AppliesTo.QC2
        )
        # Bị từ chối nếu rỗng errors hoặc dùng danh mục chỉ dành cho QC2
        self.assertEqual(
            self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/reject/"), {"errors": []}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.qc1.post(
                self.f.url(f"qc1/jobs/{self.job.id}/reject/"),
                {"errors": [{"category": qc2_only_cat.id}]},
                format="json",
            ).status_code,
            400,
        )

        # Reject vòng 1 (rework_round: 0 -> 1, chưa escalate vì max_rework_rounds=2)
        body = {
            "errors": [{"category": self.f.category.id, "location": "frame 5", "description": "lech box"}],
            "comment": "sua lai",
        }
        r1 = self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/reject/"), body, format="json")
        self.assertEqual(r1.status_code, 200, r1.data)
        self.assertEqual(r1.data["status"], JobStatus.REWORK)
        self.assertEqual(r1.data["rework_round"], 1)
        self.assertFalse(r1.data["is_escalated"])
        self.assertEqual(ReviewError.objects.filter(job=self.job, stage=ReviewStage.QC1, rework_round=0).count(), 1)

        # Vòng 2 -> 3 (vượt max_rework_rounds=2 → tự bật is_escalated)
        Job.objects.filter(pk=self.job.pk).update(status=JobStatus.QC1_REVIEWING, rework_round=2)
        r2 = self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/reject/"), body, format="json")
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertEqual(r2.data["rework_round"], 3)
        self.assertTrue(r2.data["is_escalated"])
        self.assertEqual(ReviewError.objects.filter(job=self.job, stage=ReviewStage.QC1).count(), 2)

    def test_four_eyes_blocks_qc1_on_own_annotated_job(self):
        dual = make_user("dual_ann_qc1", Role.ANNOTATOR, Role.QC1, project=self.f.project)
        own_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=dual)
        Job.objects.filter(pk=own_job.pk).update(qc1_reviewer=None)

        client = self.f.client(dual)
        # Không xuất hiện trong danh sách pool hoặc mine
        self.assertEqual(client.get(self.f.url("qc1/jobs/?scope=all")).data["count"], 0)
        # Gọi thẳng endpoint bị chặn 403 Luật bốn mắt
        self.assertEqual(client.post(self.f.url(f"qc1/jobs/{own_job.id}/start/"), {}, format="json").status_code, 403)
        self.assertEqual(client.post(self.f.url(f"qc1/jobs/{own_job.id}/pass/"), {}, format="json").status_code, 403)

    def test_qc1_cannot_review_job_assigned_to_another_qc1(self):
        other_qc1 = make_user("qc1_other", Role.QC1, project=self.f.project)
        client = self.f.client(other_qc1)
        self.assertEqual(client.get(self.f.url(f"qc1/jobs/{self.job.id}/")).status_code, 404)
        self.assertEqual(client.post(self.f.url(f"qc1/jobs/{self.job.id}/pass/"), {}, format="json").status_code, 403)

    def test_end_to_end_annotator_qc1_rework_qc2_pipeline(self):
        """Toàn luồng: PENDING_ANNOTATION -> start -> submit -> QC1 reject -> rework -> resubmit -> QC1 pass -> QC2 pass."""
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1)
        pm = self.f.client(self.f.pm)
        qc2 = self.f.client(self.f.qc2)

        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json").status_code, 200)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(
            self.qc1.post(
                self.f.url(f"qc1/jobs/{job.id}/reject/"),
                {"errors": [{"category": self.f.category.id, "description": "sai"}]},
                format="json",
            ).status_code,
            200,
        )

        # Annotator thấy lỗi trong chi tiết job và làm lại
        detail = self.ann1.get(self.f.url(f"annotator/jobs/{job.id}/")).data
        self.assertEqual(detail["status"], JobStatus.REWORK)
        self.assertEqual(len(detail["errors"]), 1)

        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json").status_code, 200)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 200)

        # Sang QC2 audit
        audit = pm.post(self.f.url("audits/"), {"batch": self.f.batch.id, "sampling_rate": 100, "auditors": [self.f.qc2.id]}, format="json")
        self.assertEqual(audit.status_code, 201, audit.data)
        sample = Audit.objects.get(pk=audit.data["id"]).samples.get(job=job)
        self.assertEqual(qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 200)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.APPROVED)

    def test_qc1_reject_rolls_back_atomically_on_failure(self):
        from unittest.mock import patch

        from projects.models import ActivityLog

        body = {"errors": [{"category": self.f.category.id, "description": "loi"}]}
        with patch.object(ActivityLog, "record", side_effect=RuntimeError("db failure")):
            with self.assertRaises(RuntimeError):
                self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/reject/"), body, format="json")

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.PENDING_QC1)
        self.assertEqual(self.job.rework_round, 0)
        self.assertEqual(ReviewError.objects.filter(job=self.job).count(), 0)
