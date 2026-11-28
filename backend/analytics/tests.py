from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from jobs.models import DailyOutputRecord, Job, JobStatus, ReworkScope, record_daily_output
from projects.models import ActivityLog, Batch, Dataset, DataStatus, Delivery
from quality.models import AuditSample, ErrorVerdict, ReviewError, ReviewStage, Severity
from quality.qc2 import ensure_qc2_sample
from teams.models import Team, TeamMember


class AnnotatorAndQc1AnalyticsTests(TestCase):
    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.ann1 = self.f.client(self.f.ann1)
        self.qc1 = self.f.client(self.f.qc1)
        self.pm = self.f.client(self.f.pm)

    def test_annotator_dashboard_stats_and_permissions(self) -> None:
        self.assertEqual(self.qc1.get(self.f.url("annotator/dashboard/")).status_code, 403)

        j1 = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1)
        j2 = self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, object_count=30)
        self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2)

        self.ann1.post(self.f.url(f"annotator/jobs/{j1.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{j1.id}/submit/"), {}, format="json")
        ReviewError.objects.create(job=j2, stage=ReviewStage.QC1, rework_round=0, category=self.f.category, severity="minor")

        res = self.ann1.get(self.f.url("annotator/dashboard/?period=week"))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["counts"]["total"], 2)
        self.assertEqual(res.data["counts"]["waiting_review"], 1)
        self.assertEqual(res.data["counts"]["done"], 1)
        self.assertEqual(res.data["objects_done"], 30)
        self.assertEqual(res.data["submitted_in_period"]["value"], 1)
        self.assertEqual(res.data["errors_by_category"][0]["count"], 1)
        self.assertIn("meta", res.data)
        self.assertIn("kpi_summary", res.data)
        self.assertIn("next_jobs", res.data)
        self.assertEqual(len(res.data["daily_results"]), 7)
        self.assertIn("recent_requests", res.data)

    def test_annotator_dashboard_daily_actual_does_not_mix_lifetime_done(self) -> None:
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, object_count=500)
        res = self.ann1.get(self.f.url("annotator/dashboard/?period=week"))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["kpi_summary"]["actual_objects"], 0)

    def test_annotator_personal_analytics_p2_and_private_ranking(self) -> None:
        self.assertEqual(self.qc1.get(self.f.url("annotator/analytics/")).status_code, 403)

        j1 = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, object_count=600)
        j2 = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2, object_count=1000)
        self.ann1.post(self.f.url(f"annotator/jobs/{j1.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{j1.id}/submit/"), {"object_count": 600}, format="json")
        ann2 = self.f.client(self.f.ann2)
        ann2.post(self.f.url(f"annotator/jobs/{j2.id}/start/"), {}, format="json")
        ann2.post(self.f.url(f"annotator/jobs/{j2.id}/submit/"), {"object_count": 1000}, format="json")

        res = self.ann1.get(self.f.url("annotator/analytics/?range=7d"))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["avg_productivity"]["total_objects"], 600)
        self.assertEqual(res.data["ranking"]["rank"], 2)
        self.assertEqual(res.data["ranking"]["total_annotators"], 2)
        self.assertNotIn("leaderboard", res.data["ranking"])
        self.assertEqual(len(res.data["daily_productivity"]), 7)
        self.assertEqual(len(res.data["weekly_forecast_series"]), 7)

    def test_qc1_summary_metrics_trend_escape_errors_and_on_time(self) -> None:
        self.assertEqual(self.ann1.get(self.f.url("qc1-summary/")).status_code, 403)

        now = timezone.now()
        j_pass = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, deadline=now + timedelta(hours=2))
        j_rej = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2, deadline=now - timedelta(hours=1))

        self.qc1.post(self.f.url(f"qc1/jobs/{j_pass.id}/pass/"), {}, format="json")
        self.qc1.post(
            self.f.url(f"qc1/jobs/{j_rej.id}/reject/"),
            {"errors": [{"category": self.f.category.id, "description": "thieu"}]},
            format="json",
        )
        # QC2 bắt được 1 lỗi FAIL, 1 lỗi EDGE và 1 lỗi đã huỷ (chỉ FAIL chưa huỷ tính là escape)
        fail_err = ReviewError.objects.create(
            job=j_pass,
            stage=ReviewStage.QC2,
            rework_round=0,
            category=self.f.category,
            severity=Severity.MAJOR,
            verdict=ErrorVerdict.FAIL,
            frame_number=14,
            cvat_object_id=88,
            location="Làn trái",
            description="Lệch hướng cuboid",
            reported_by=self.f.qc2,
        )
        ReviewError.objects.create(
            job=j_pass,
            stage=ReviewStage.QC2,
            rework_round=0,
            category=self.f.category,
            severity=Severity.MINOR,
            verdict=ErrorVerdict.EDGE,
        )
        ReviewError.objects.create(
            job=j_pass,
            stage=ReviewStage.QC2,
            rework_round=0,
            category=self.f.category,
            severity=Severity.CRITICAL,
            verdict=ErrorVerdict.FAIL,
            is_voided=True,
        )

        res = self.qc1.get(self.f.url("qc1-summary/?period=week"))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["scope"], "mine")
        self.assertEqual(res.data["stats"]["passed"], 1)
        self.assertEqual(res.data["stats"]["rejected"], 1)
        self.assertEqual(res.data["stats"]["reviewed_today"], 2)
        self.assertEqual(res.data["pass_rate"], 50.0)
        self.assertEqual(res.data["on_time_pct"], 50.0)
        self.assertEqual(res.data["on_time_count"], 1)
        self.assertEqual(res.data["on_time_total"], 2)
        self.assertEqual(res.data["kpi"]["current"]["reviewed"], 2)
        self.assertEqual(res.data["kpi"]["current"]["errors"], 1)
        self.assertEqual(res.data["qc2_escape_errors"], 1)
        self.assertEqual(res.data["escaped_jobs"], 1)
        self.assertEqual(len(res.data["escape_errors"]), 1)
        self.assertEqual(res.data["escape_errors"][0]["id"], fail_err.id)
        self.assertEqual(res.data["escape_errors"][0]["job_id"], j_pass.id)
        self.assertEqual(res.data["escape_errors"][0]["frame_number"], 14)
        self.assertEqual(res.data["escape_errors"][0]["cvat_object_id"], 88)
        self.assertEqual(res.data["escape_errors"][0]["reported_by"]["id"], self.f.qc2.id)
        self.assertEqual(len(res.data["trend"]), 7)
        self.assertEqual(res.data["trend"][-1]["reviewed"], 2)

        pm_res = self.pm.get(self.f.url("qc1-summary/?period=week"))
        self.assertEqual(pm_res.status_code, 200, pm_res.data)
        self.assertEqual(pm_res.data["scope"], "project")
        self.assertEqual(pm_res.data["stats"]["passed"], 1)


class FormulaAndDailyOutputTests(TestCase):
    """Kiểm thử các công thức chốt Stage 2 + Hybrid QC2 theo frame."""

    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.f.project.kpi_annotation_target = 100
        self.f.project.kpi_qc1_target = 5
        self.f.project.kpi_qc2_target = 2
        self.f.project.save(update_fields=["kpi_annotation_target", "kpi_qc1_target", "kpi_qc2_target"])
        self.pm = self.f.client(self.f.pm)
        self.ann1 = self.f.client(self.f.ann1)
        self.ann2 = self.f.client(self.f.ann2)
        self.qc1 = self.f.client(self.f.qc1)
        self.qc2 = self.f.client(self.f.qc2)

    def test_daily_output_separates_submit_vs_cvat_sync_and_partial_rework(self) -> None:
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, object_count=80, last_counted_objects=80)
        record_daily_output(
            job=job,
            user=self.f.ann1,
            object_count=80,
            is_rework=False,
            rework_round=0,
            source=DailyOutputRecord.Source.CVAT_SYNC,
        )

        # 1. Trước khi nộp: 80 cuboid từ CVAT_SYNC được tách rõ vào unsubmitted_cvat_objects
        d1 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(d1["kpi_summary"]["actual_objects"], 80)
        self.assertEqual(d1["kpi_summary"]["today_submitted_objects"], 0)
        self.assertEqual(d1["kpi_summary"]["today_unsubmitted_cvat_objects"], 80)
        self.assertEqual(d1["kpi_summary"]["shortfall"], 20)
        self.assertEqual(d1["kpi_summary"]["surplus"], 0)
        self.assertEqual(d1["daily_results"][-1]["first_pass_objects"], 80)
        self.assertEqual(d1["daily_results"][-1]["unsubmitted_cvat_objects"], 80)

        # 2. Nộp bài với 120 cuboid → cộng delta +40 (SUBMIT), tổng 120, surplus=20
        self.assertEqual(
            self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {"object_count": 120}, format="json").status_code,
            200,
        )
        d2 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(d2["kpi_summary"]["actual_objects"], 120)
        self.assertEqual(d2["kpi_summary"]["today_submitted_objects"], 40)
        self.assertEqual(d2["kpi_summary"]["today_unsubmitted_cvat_objects"], 80)
        self.assertEqual(d2["kpi_summary"]["achievement_pct"], 120.0)
        self.assertEqual(d2["kpi_summary"]["surplus"], 20)

        # 3. Sau khi QC1 Pass → sản lượng hôm nay giữ nguyên 120
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 200)
        d3 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(d3["kpi_summary"]["actual_objects"], 120)

        # 4. Partial rework trên job 100 cuboid có 2 lỗi duy nhất → cộng +2 rework
        job_rw = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, object_count=0)
        self.ann1.post(self.f.url(f"annotator/jobs/{job_rw.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job_rw.id}/submit/"), {"object_count": 100}, format="json")
        self.qc1.post(
            self.f.url(f"qc1/jobs/{job_rw.id}/reject/"),
            {
                "rework_scope": ReworkScope.PARTIAL,
                "errors": [
                    {"category": self.f.category.id, "frame_number": 1, "cvat_object_id": 10},
                    {"category": self.f.category.id, "frame_number": 1, "cvat_object_id": 10},
                    {"category": self.f.category.id, "frame_number": 2, "cvat_object_id": 11},
                ],
            },
            format="json",
        )
        self.ann1.post(self.f.url(f"annotator/jobs/{job_rw.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job_rw.id}/submit/"), {"object_count": 100}, format="json")
        d4 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(d4["daily_results"][-1]["first_pass_objects"], 220)
        self.assertEqual(d4["daily_results"][-1]["rework_objects"], 2)
        self.assertEqual(d4["kpi_summary"]["actual_objects"], 222)

    def test_fpy_cl01_immutable_and_safe_fallback_for_legacy_qc2_reject(self) -> None:
        j1 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)
        j2 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)

        # j1 Pass QC1 lần đầu → QC2 Reject → vẫn là FPY Pass tại QC1
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{j1.id}/pass/"), {}, format="json").status_code, 200)
        Job.objects.filter(pk=j1.pk).update(status=JobStatus.PENDING_QC2)
        sample1 = ensure_qc2_sample(Job.objects.get(pk=j1.pk))
        assert sample1 is not None
        self.qc2.post(
            self.f.url(f"audit-samples/{sample1.id}/reject/"),
            {"errors": [{"category": self.f.category.id}]},
            format="json",
        )

        # j2 trượt QC1 lần đầu → escalate → PM gỡ escalation
        self.assertEqual(
            self.qc1.post(
                self.f.url(f"qc1/jobs/{j2.id}/reject/"),
                {"errors": [{"category": self.f.category.id}]},
                format="json",
            ).status_code,
            200,
        )
        Job.objects.filter(pk=j2.pk).update(is_escalated=True, rework_round=3)
        self.pm.post(self.f.url(f"jobs/{j2.id}/resolve-escalation/"), {}, format="json")

        # FPY = 1 pass (j1) / 2 = 50.0%
        ov = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov["metrics"]["first_pass_yield"]["value"], 50.0)
        self.assertEqual(ov["metrics"]["first_pass_yield"]["passed"], 1)
        self.assertEqual(ov["metrics"]["first_pass_yield"]["total"], 2)
        self.assertEqual(ov["metrics"]["rework_rate"]["value"], 100.0)

        ann_dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(ann_dash["kpi_summary"]["fpy_pct"], 50.0)
        qc1_sum = self.qc1.get(self.f.url("qc1-summary/")).data
        self.assertEqual(qc1_sum["first_pass_yield"]["value"], 50.0)
        self.assertEqual(qc1_sum["qc1_escape_job_rate"], 100.0)
        self.assertEqual(qc1_sum["escaped_jobs"], 1)

        # Legacy job (first_qc1_result="") qua QC1 vòng 0 rồi bị QC2 reject vòng 0 → KHÔNG đếm oan thành trượt QC1!
        j_legacy_qc2 = self.f.job(
            status=JobStatus.PENDING_QC2,
            annotator=self.f.ann1,
            first_qc1_result="",
            rework_round=0,
            total_rework_rounds=0,
        )
        sample_leg = ensure_qc2_sample(j_legacy_qc2)
        assert sample_leg is not None
        self.qc2.post(
            self.f.url(f"audit-samples/{sample_leg.id}/reject/"),
            {"errors": [{"category": self.f.category.id}]},
            format="json",
        )
        ov2 = self.pm.get(self.f.url("overview/")).data
        # 2 pass (j1 + j_legacy_qc2) / 3 = 66.7%
        self.assertEqual(ov2["metrics"]["first_pass_yield"]["passed"], 2)
        self.assertEqual(ov2["metrics"]["first_pass_yield"]["total"], 3)
        self.assertEqual(ov2["metrics"]["first_pass_yield"]["value"], 66.7)

    def test_cl02_cl05_cl11_are_pending_definition_and_voided_errors_excluded(self) -> None:
        job = self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1, rework_round=1, total_rework_rounds=1, object_count=100)
        e_active = ReviewError.objects.create(
            job=job,
            stage=ReviewStage.QC1,
            rework_round=0,
            category=self.f.category,
            severity=Severity.CRITICAL,
            verdict=ErrorVerdict.FAIL,
            frame_number=1,
            cvat_object_id=10,
        )
        ReviewError.objects.create(
            job=job,
            stage=ReviewStage.QC1,
            rework_round=0,
            category=self.f.category,
            severity=Severity.MINOR,
            verdict=ErrorVerdict.FAIL,
            is_voided=True,
        )

        ov = self.pm.get(self.f.url("overview/")).data
        for key in ("defect_error_rate", "defect_rate_by_severity", "quality_cl"):
            self.assertEqual(ov["metrics"][key]["status"], "pending_definition")
            self.assertIsNone(ov["metrics"][key]["value"])
        # Lỗi is_voided=True bị loại khỏi errors_by_severity & errors_by_category
        self.assertEqual(ov["errors_by_severity"][Severity.CRITICAL], 1)
        self.assertEqual(ov["errors_by_severity"][Severity.MINOR], 0)

        qc2_sum = self.pm.get(self.f.url("qc2-summary/")).data
        for key in ("error_percent_in_job", "defect_error_rate", "defect_rate_by_severity", "quality_cl"):
            self.assertEqual(qc2_sum[key]["status"], "pending_definition")
            self.assertIsNone(qc2_sum[key]["value"])

        # Khi void luôn lỗi cuối cùng của vòng hiện tại (round 1), KHÔNG hồi sinh lỗi vòng 0 cũ!
        Job.objects.filter(pk=job.pk).update(rework_round=2, total_rework_rounds=2)
        e_round1 = ReviewError.objects.create(
            job=job,
            stage=ReviewStage.QC1,
            rework_round=1,
            category=self.f.category,
            severity=Severity.MAJOR,
            is_voided=True,
        )
        self.assertTrue(e_round1.is_voided)
        self.assertFalse(e_active.is_voided)
        dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash["kpi_summary"]["pending_rework_errors"], 0)
        self.assertEqual(dash["rework_focus"]["error_count"], 0)

    def test_overview_ready_batches_with_open_audit_and_zero_pending_samples(self) -> None:
        # Batch có Audit IN_PROGRESS nhưng 0 mẫu pending và 100% job APPROVED, không khoá → ready_batches=1!
        j1 = self.f.job(status=JobStatus.PENDING_QC2, frame_count=10)
        sample = ensure_qc2_sample(j1)
        assert sample is not None
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 200)

        # Batch 2 sẵn sàng confirm-qc2 (100% QC1_PASSED)
        batch2 = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="B2")
        j2 = self.f.job(batch=batch2, status=JobStatus.QC1_PASSED)

        ov = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov["counts"]["ready_batches"], 1)
        self.assertEqual(ov["pending_decisions"]["batches_ready_for_qc2_confirm"], 1)
        self.assertEqual(ov["pending_decisions"]["pending_qc2_samples"], 0)
        self.assertNotIn("audits_ready_to_complete", ov["pending_decisions"])

        # Khoá j1 → ready_batches giảm về 0; khoá j2 → batches_ready_for_qc2_confirm giảm về 0
        Job.objects.filter(pk=j1.pk).update(is_locked=True)
        Job.objects.filter(pk=j2.pk).update(is_locked=True)
        ov2 = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov2["counts"]["ready_batches"], 0)
        self.assertEqual(ov2["pending_decisions"]["batches_ready_for_qc2_confirm"], 0)

    def test_overview_thresholds_strings_and_dh07_delivery_on_time(self) -> None:
        ov_empty = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov_empty["thresholds"], {"quality_cl": None, "defect_error_rate": None})
        self.assertIsNone(ov_empty["metrics"]["delivery_on_time_rate"]["value"])
        self.assertEqual(ov_empty["metrics"]["delivery_on_time_rate"]["due_deliveries"], 0)
        self.assertEqual(ov_empty["counts"]["overdue_batches"], 0)

        self.f.project.quality_cl_threshold = Decimal("95.5")
        self.f.project.defect_rate_threshold = Decimal("2")
        self.f.project.save(update_fields=["quality_cl_threshold", "defect_rate_threshold"])

        now = timezone.now()
        b_on_time = Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="B_ON_TIME", deadline=now + timedelta(days=1)
        )
        b_late = Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="B_LATE", deadline=now - timedelta(hours=3)
        )
        Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="B_OVERDUE_OPEN", deadline=now - timedelta(days=1)
        )
        Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="B_FUTURE_OPEN", deadline=now + timedelta(days=5)
        )
        b_no_deadline = Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="B_NO_DL", deadline=None
        )
        for batch in (b_on_time, b_late, b_no_deadline):
            Delivery.objects.create(
                project=self.f.project,
                batch=batch,
                recipient="Client",
                output_path=f"s3://out/{batch.name}",
                delivered_by=self.f.pm,
            )
            Batch.objects.filter(pk=batch.pk).update(status=DataStatus.DELIVERED)

        ov = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov["thresholds"], {"quality_cl": "95.50", "defect_error_rate": "2.00"})
        self.assertEqual(ov["counts"]["overdue_batches"], 1)
        dh07 = ov["metrics"]["delivery_on_time_rate"]
        self.assertEqual(dh07["value"], 33.3)
        self.assertEqual(dh07["on_time_deliveries"], 1)
        self.assertEqual(dh07["late_deliveries"], 1)
        self.assertEqual(dh07["overdue_undelivered"], 1)
        self.assertEqual(dh07["due_deliveries"], 3)

    def test_qc1_escape_anchored_on_sample_created_at_and_includes_cvat_synced_escapes(self) -> None:
        qc1_b = make_user("qc1_second", Role.QC1, project=self.f.project)
        qc1_b_client = self.f.client(qc1_b)
        self.f.batch.qc2_confirmed_by = self.f.pm
        self.f.batch.qc2_confirmed_at = timezone.now()
        self.f.batch.save(update_fields=["qc2_confirmed_by", "qc2_confirmed_at"])

        # Vòng 1: qc1 pass → sample1 (t1) Pass (0 lỗi)
        job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, frame_count=10)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 200)
        s1 = AuditSample.objects.get(job=job, result=AuditSample.Result.PENDING)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{s1.id}/pass/"), {}, format="json").status_code, 200)

        # Vòng 2 trong CÙNG 1 Audit: đổi sang qc1_b → qc1_b pass → sample2 (t2 > t1) Reject với 2 lỗi FAIL + 1 EDGE
        Job.objects.filter(pk=job.pk).update(status=JobStatus.PENDING_QC1, qc1_reviewer=qc1_b, rework_round=1, total_rework_rounds=1)
        self.assertEqual(qc1_b_client.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 200)
        s2 = AuditSample.objects.get(job=job, result=AuditSample.Result.PENDING)
        self.assertEqual(s1.audit_id, s2.audit_id)  # Cùng 1 Audit của batch!
        self.assertEqual(
            self.qc2.post(
                self.f.url(f"audit-samples/{s2.id}/reject/"),
                {
                    "errors": [
                        {"category": self.f.category.id, "frame_number": 1, "cvat_object_id": 1, "verdict": "fail"},
                        {"category": self.f.category.id, "frame_number": 2, "cvat_object_id": 2, "verdict": "fail"},
                        {"category": self.f.category.id, "frame_number": 3, "cvat_object_id": 3, "verdict": "edge"},
                    ]
                },
                format="json",
            ).status_code,
            200,
        )

        # Neo theo AuditSample.created_at: KHÔNG đổ lỗi cho qc1 (vòng 1), chỉ tính 2 FAIL cho qc1_b (vòng 2)!
        qc1_a_sum = self.qc1.get(self.f.url("qc1-summary/?scope=mine")).data
        qc1_b_sum = qc1_b_client.get(self.f.url("qc1-summary/?scope=mine")).data
        self.assertEqual(qc1_a_sum["qc2_escape_errors"], 0)
        self.assertEqual(qc1_a_sum["escaped_jobs"], 0)
        self.assertEqual(qc1_a_sum["qc1_escape_job_rate"], 0.0)
        self.assertEqual(qc1_b_sum["qc2_escape_errors"], 2)
        self.assertEqual(qc1_b_sum["escaped_jobs"], 1)
        self.assertEqual(qc1_b_sum["qc1_escape_job_rate"], 100.0)

        # Job đồng bộ CVAT sang QC1_PASSED (chỉ có job.status, không có qc1.pass) bị QC2 bắt lỗi cũng được tính!
        cvat_job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann2, qc1_reviewer=self.f.qc1, frame_count=10)
        ActivityLog.record(
            project=self.f.project,
            actor=self.f.pm,
            action="job.status",
            target=cvat_job,
            job=cvat_job,
            before={"status": JobStatus.QC1_REVIEWING},
            after={"status": JobStatus.QC1_PASSED},
            note="Đồng bộ từ CVAT",
        )
        s_cvat = ensure_qc2_sample(cvat_job)
        assert s_cvat is not None
        self.qc2.post(
            self.f.url(f"audit-samples/{s_cvat.id}/reject/"),
            {"errors": [{"category": self.f.category.id, "verdict": "fail"}]},
            format="json",
        )
        qc1_a_after = self.qc1.get(self.f.url("qc1-summary/?scope=mine")).data
        self.assertEqual(qc1_a_after["qc2_escape_errors"], 1)
        self.assertEqual(qc1_a_after["escaped_jobs"], 1)

    def test_qc2_summary_no_cover_double_count_and_batch_id_grouping(self) -> None:
        other_qc2 = make_user("qc2_cover", Role.QC2, project=self.f.project)
        ds2 = Dataset.objects.create(project=self.f.project, name="D2")
        batch_same_name = Batch.objects.create(project=self.f.project, dataset=ds2, name=self.f.batch.name)
        j1 = self.f.job(status=JobStatus.PENDING_QC2, object_count=50, frame_count=10)
        j2 = Job.objects.create(
            project=self.f.project,
            dataset=ds2,
            batch=batch_same_name,
            name="J-D2",
            status=JobStatus.PENDING_QC2,
            annotator=self.f.ann2,
            object_count=50,
            frame_count=10,
        )
        s1 = ensure_qc2_sample(j1)
        s2 = ensure_qc2_sample(j2)
        assert s1 is not None and s2 is not None
        AuditSample.objects.filter(pk=s1.pk).update(auditor=self.f.qc2)
        AuditSample.objects.filter(pk=s2.pk).update(auditor=other_qc2)

        # PM chấm hộ s1 vốn giao cho self.f.qc2 → KHÔNG đếm trùng cho self.f.qc2
        self.assertEqual(self.pm.post(self.f.url(f"audit-samples/{s1.id}/pass/"), {}, format="json").status_code, 200)
        self.assertEqual(
            self.f.client(other_qc2).post(self.f.url(f"audit-samples/{s2.id}/pass/"), {}, format="json").status_code, 200
        )

        qc2_mine = self.qc2.get(self.f.url("qc2-summary/?scope=mine")).data
        self.assertEqual(qc2_mine["stats"]["passed"], 0)
        self.assertEqual(qc2_mine["stats"]["audited_today"], 0)
        self.assertEqual(qc2_mine["kpi_summary"]["actual"], 0)

        pm_mine = self.pm.get(self.f.url("qc2-summary/?scope=mine")).data
        self.assertEqual(pm_mine["stats"]["passed"], 1)
        self.assertEqual(pm_mine["stats"]["audited_today"], 1)
        self.assertEqual(pm_mine["kpi_target"], 2)
        self.assertEqual(pm_mine["kpi_summary"]["achievement_pct"], 50.0)
        self.assertEqual(pm_mine["kpi"]["comparison"]["audited"]["delta"], 1)
        self.assertIsNone(pm_mine["kpi"]["comparison"]["audited"]["pct_change"])

        pm_proj = self.pm.get(self.f.url("qc2-summary/")).data
        self.assertEqual(pm_proj["stats"]["audited_today"], 2)
        self.assertEqual(len(pm_proj["progress_by_batch"]), 2)
        self.assertEqual({r["dataset_name"] for r in pm_proj["progress_by_batch"]}, {"D1", "D2"})

    def test_annotator_analytics_split_hours_merged_wip_and_reassignment_attribution(self) -> None:
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, object_count=999)
        empty_res = self.ann1.get(self.f.url("annotator/analytics/?range=7d")).data
        self.assertEqual(empty_res["avg_productivity"]["total_objects"], 0)
        self.assertEqual(empty_res["avg_productivity"]["measured_objects"], 0)
        self.assertIsNone(empty_res["avg_productivity"]["objects_per_hour"])
        self.assertEqual(empty_res["avg_productivity"]["status"], "unavailable")
        self.assertEqual(empty_res["avg_productivity"]["hours_provenance"]["source"], "workflow_elapsed_session")
        self.assertEqual(empty_res["avg_productivity"]["hours_provenance"]["status"], "unavailable")
        self.assertIsNone(empty_res["daily_productivity"][-1]["first_pass_per_hour"])
        self.assertIsNone(empty_res["daily_productivity"][-1]["rework_per_hour"])
        self.assertEqual(empty_res["daily_productivity"][-1]["hours_status"], "unavailable")
        self.assertIsNone(empty_res["ranking"]["previous_rank"])

        now = timezone.now()
        j_fp = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, object_count=0)
        self.ann1.post(self.f.url(f"annotator/jobs/{j_fp.id}/start/"), {}, format="json")
        start_fp = ActivityLog.objects.filter(job=j_fp, action="job.status", after__status=JobStatus.ANNOTATING).first()
        assert start_fp is not None
        ActivityLog.objects.filter(pk=start_fp.pk).update(created_at=now - timedelta(hours=2))
        self.ann1.post(self.f.url(f"annotator/jobs/{j_fp.id}/submit/"), {"object_count": 200}, format="json")

        j_rw = self.f.job(
            status=JobStatus.REWORK,
            annotator=self.f.ann1,
            rework_round=1,
            total_rework_rounds=1,
            rework_scope=ReworkScope.FULL,
            object_count=10,
        )
        self.ann1.post(self.f.url(f"annotator/jobs/{j_rw.id}/start/"), {}, format="json")
        start_rw = ActivityLog.objects.filter(job=j_rw, action="job.status", after__status=JobStatus.ANNOTATING).first()
        assert start_rw is not None
        ActivityLog.objects.filter(pk=start_rw.pk).update(created_at=now - timedelta(hours=1))
        self.ann1.post(self.f.url(f"annotator/jobs/{j_rw.id}/submit/"), {"object_count": 10}, format="json")

        # Giao lại j_fp cho ann2 → sản lượng 200 cuboid vẫn giữ nguyên cho ann1
        self.pm.post(self.f.url(f"jobs/{j_fp.id}/assign/"), {"annotator": self.f.ann2.id}, format="json")

        analytics = self.ann1.get(self.f.url("annotator/analytics/?range=7d")).data
        today_row = analytics["daily_productivity"][-1]
        self.assertEqual(today_row["first_pass_objects"], 200)
        self.assertEqual(today_row["rework_objects"], 10)
        self.assertEqual(today_row["measured_objects"], 210)
        self.assertEqual(today_row["hours_status"], "provisional")
        self.assertAlmostEqual(today_row["first_pass_per_hour"], 100.0, delta=2.0)
        self.assertAlmostEqual(today_row["rework_per_hour"], 10.0, delta=0.5)
        self.assertEqual(analytics["avg_productivity"]["measured_objects"], 210)
        self.assertEqual(analytics["avg_productivity"]["status"], "provisional")

        perf = {r["user"]["id"]: r for r in self.pm.get(self.f.url("member-performance/")).data}
        self.assertEqual(perf[self.f.ann1.id]["total_objects"], 210)
        self.assertEqual(perf[self.f.ann2.id]["total_objects"], 0)

    def test_dh06_deadline_snapshot_and_ns03_mixed_sync_submit_day(self) -> None:
        now = timezone.now()
        j_late = self.f.job(
            status=JobStatus.PENDING_ANNOTATION,
            annotator=self.f.ann1,
            deadline=now - timedelta(hours=2),
            object_count=0,
        )
        self.ann1.post(self.f.url(f"annotator/jobs/{j_late.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{j_late.id}/submit/"), {"object_count": 20}, format="json")
        self.pm.post(
            self.f.url(f"jobs/{j_late.id}/deadline/"),
            {"deadline": (now + timedelta(days=2)).isoformat().replace("+00:00", "Z"), "note": "gia han"},
            format="json",
        )
        dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash["kpi_summary"]["on_time_pct"], 0.0)

        # NS03: tách riêng CVAT_SYNC chưa nộp (100) với SUBMIT rework (10+20) trên 2 job chạy song song 1h
        j_uncheck = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann2, object_count=0)
        record_daily_output(
            job=j_uncheck,
            user=self.f.ann2,
            object_count=100,
            is_rework=False,
            rework_round=0,
            source=DailyOutputRecord.Source.CVAT_SYNC,
        )
        j_rw2 = self.f.job(
            status=JobStatus.REWORK,
            annotator=self.f.ann2,
            rework_round=1,
            total_rework_rounds=1,
            rework_scope=ReworkScope.FULL,
            object_count=10,
        )
        j_rw3 = self.f.job(
            status=JobStatus.REWORK,
            annotator=self.f.ann2,
            rework_round=1,
            total_rework_rounds=1,
            rework_scope=ReworkScope.FULL,
            object_count=20,
        )
        for j_r, cnt in ((j_rw2, 10), (j_rw3, 20)):
            self.ann2.post(self.f.url(f"annotator/jobs/{j_r.id}/start/"), {}, format="json")
            st = ActivityLog.objects.filter(job=j_r, action="job.status", after__status=JobStatus.ANNOTATING).first()
            assert st is not None
            ActivityLog.objects.filter(pk=st.pk).update(created_at=now - timedelta(hours=1))
            self.ann2.post(self.f.url(f"annotator/jobs/{j_r.id}/submit/"), {"object_count": cnt}, format="json")

        ann2_ana = self.ann2.get(self.f.url("annotator/analytics/?range=7d")).data
        today_row = ann2_ana["daily_productivity"][-1]
        self.assertEqual(today_row["first_pass_objects"], 100)
        self.assertEqual(today_row["submitted_objects"], 30)
        self.assertEqual(today_row["unsubmitted_cvat_objects"], 100)
        self.assertEqual(today_row["measured_objects"], 30)
        self.assertEqual(today_row["hours_status"], "provisional")
        self.assertIsNone(today_row["first_pass_per_hour"])
        self.assertAlmostEqual(today_row["rework_per_hour"], 30.0, delta=1.5)
        self.assertAlmostEqual(today_row["hours"], 1.0, delta=0.1)
        self.assertEqual(ann2_ana["avg_productivity"]["total_objects"], 130)
        self.assertEqual(ann2_ana["avg_productivity"]["measured_objects"], 30)
        self.assertEqual(ann2_ana["avg_productivity"]["submitted_objects"], 30)
        self.assertEqual(ann2_ana["avg_productivity"]["unsubmitted_cvat_objects"], 100)
        self.assertEqual(ann2_ana["avg_productivity"]["status"], "provisional")
        self.assertAlmostEqual(ann2_ana["avg_productivity"]["objects_per_hour"], 30, delta=2)

    def test_post_escalation_partial_rework_focus(self) -> None:
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, object_count=0)
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {"object_count": 50}, format="json")
        self.qc1.post(
            self.f.url(f"qc1/jobs/{job.id}/reject/"),
            {
                "rework_scope": ReworkScope.PARTIAL,
                "errors": [
                    {"category": self.f.category.id, "frame_number": 1, "cvat_object_id": 1},
                    {"category": self.f.category.id, "frame_number": 2, "cvat_object_id": 2},
                ],
            },
            format="json",
        )
        Job.objects.filter(pk=job.pk).update(rework_round=3, total_rework_rounds=3, is_escalated=True)
        self.pm.post(self.f.url(f"jobs/{job.id}/resolve-escalation/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {"object_count": 50}, format="json")
        self.qc1.post(
            self.f.url(f"qc1/jobs/{job.id}/reject/"),
            {
                "rework_scope": ReworkScope.PARTIAL,
                "errors": [
                    {"category": self.f.category.id, "frame_number": 10, "cvat_object_id": 10},
                    {"category": self.f.category.id, "frame_number": 11, "cvat_object_id": 11},
                    {
                        "category": self.f.category.id,
                        "frame_number": 12,
                        "cvat_object_id": None,
                        "is_missing_object": True,
                    },
                ],
            },
            format="json",
        )
        dash_before = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash_before["rework_focus"]["error_count"], 3)
        self.assertEqual(dash_before["rework_focus"]["pending_object_frames"], 3)


class AnalyticsBugFixTests(TestCase):
    """Kiểm thử hồi quy P1 cho analytics: múi giờ VN UTC+7, ?period=day 00:00 +07:00, FPY, QC1/QC2 scope."""

    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.f.project.kpi_annotation_target = 1000
        self.f.project.save(update_fields=["kpi_annotation_target"])
        self.ann1 = self.f.client(self.f.ann1)
        self.ann2 = self.f.client(self.f.ann2)
        self.qc1 = self.f.client(self.f.qc1)
        self.qc2 = self.f.client(self.f.qc2)
        self.pm = self.f.client(self.f.pm)

    def test_vietnam_timezone_cutoff_for_daily_buckets_period_day_and_alert_formatting(self) -> None:
        # 2026-11-26 18:00 UTC == 2026-11-27 01:00 Asia/Ho_Chi_Minh (qua ngày mới ở VN, 00:00 +07 == 17:00 UTC)
        fixed_now = datetime(2026, 11, 26, 18, 0, tzinfo=UTC)
        yesterday_vn = datetime(2026, 11, 26, 16, 30, tzinfo=UTC)  # 26/11 23:30 VN (trước mốc 00:00 +07)
        today_vn = datetime(2026, 11, 26, 17, 30, tzinfo=UTC)  # 27/11 00:30 VN (sau mốc 00:00 +07)

        job = self.f.job(
            status=JobStatus.PENDING_QC2,
            annotator=self.f.ann1,
            object_count=250,
            deadline=today_vn,
        )
        record_daily_output(
            job=job,
            user=self.f.ann1,
            object_count=250,
            is_rework=False,
            rework_round=0,
            source=DailyOutputRecord.Source.SUBMIT,
            at=fixed_now,
        )
        ev_old = ActivityLog.record(
            project=self.f.project,
            actor=self.f.ann1,
            action="job.status",
            target=job,
            job=job,
            after={"status": JobStatus.PENDING_QC1, "event": "annotator.submit", "rework_round": 0, "object_count": 100},
        )
        ActivityLog.objects.filter(pk=ev_old.pk).update(created_at=yesterday_vn)
        ev_new = ActivityLog.record(
            project=self.f.project,
            actor=self.f.ann1,
            action="job.status",
            target=job,
            job=job,
            after={"status": JobStatus.PENDING_QC1, "event": "annotator.submit", "rework_round": 0, "object_count": 250},
        )
        ActivityLog.objects.filter(pk=ev_new.pk).update(created_at=today_vn)

        qc1_ev = ActivityLog.record(
            project=self.f.project,
            actor=self.f.qc1,
            action="qc1.pass",
            target=job,
            job=job,
            after={"status": JobStatus.PENDING_QC2, "rework_round": 0},
        )
        ActivityLog.objects.filter(pk=qc1_ev.pk).update(created_at=fixed_now)

        sample = ensure_qc2_sample(job)
        assert sample is not None
        sample.result = sample.Result.PASS
        sample.reviewed_by = self.f.qc2
        sample.reviewed_at = fixed_now
        sample.save(update_fields=["result", "reviewed_by", "reviewed_at"])

        with patch("django.utils.timezone.now", return_value=fixed_now):
            # ?period=day cắt đúng 00:00:00 +07:00 → chỉ tính ev_new (17:30 UTC), loại ev_old (16:30 UTC)!
            dash = self.ann1.get(self.f.url("annotator/dashboard/?period=day")).data
            self.assertEqual(dash["submitted_in_period"]["value"], 1)
            self.assertEqual(dash["daily_results"][-1]["date"], "2026-11-27")
            self.assertEqual(dash["daily_results"][-1]["first_pass_objects"], 250)
            self.assertEqual(dash["kpi_summary"]["actual_objects"], 250)

            ana = self.ann1.get(self.f.url("annotator/analytics/?range=7d")).data
            self.assertEqual(ana["daily_productivity"][-1]["date"], "2026-11-27")
            self.assertEqual(ana["daily_productivity"][-1]["first_pass_objects"], 250)

            qc1_sum = self.qc1.get(self.f.url("qc1-summary/?period=week")).data
            self.assertEqual(qc1_sum["trend"][-1]["date"], "2026-11-27")
            self.assertEqual(qc1_sum["trend"][-1]["reviewed"], 1)

            qc2_sum = self.qc2.get(self.f.url("qc2-summary/?period=week")).data
            self.assertEqual(qc2_sum["trend"][-1]["date"], "2026-11-27")
            self.assertEqual(qc2_sum["trend"][-1]["audited"], 1)

            overview = self.pm.get(self.f.url("overview/?period=day")).data
            self.assertEqual(overview["metrics"]["submitted_in_period"]["value"], 1)
            overdue_alerts = [a for a in overview["alerts"] if a["type"] == "overdue"]
            self.assertEqual(len(overdue_alerts), 1)
            self.assertIn("27/11 00:30", overdue_alerts[0]["message"])

    def test_annotator_dashboard_zero_today_active_counts_and_rework_focus_beyond_top_10(self) -> None:
        now = timezone.now()
        self.f.project.cvat_synced_at = now - timedelta(minutes=5)
        self.f.project.save(update_fields=["cvat_synced_at"])

        self.f.job(
            status=JobStatus.APPROVED,
            annotator=self.f.ann1,
            object_count=500,
            deadline=now + timedelta(days=1),
            submitted_at=now - timedelta(days=2),
        )
        self.f.job(
            status=JobStatus.ANNOTATING,
            annotator=self.f.ann1,
            deadline=now - timedelta(hours=2),
            target_object_count=100,
        )
        self.f.job(
            status=JobStatus.PENDING_ANNOTATION,
            annotator=self.f.ann1,
            deadline=now + timedelta(hours=6),
            target_object_count=200,
        )
        self.f.job(
            status=JobStatus.PENDING_QC1,
            annotator=self.f.ann1,
            deadline=now - timedelta(hours=3),
            submitted_at=now - timedelta(hours=4),
        )

        dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash["kpi_summary"]["actual_objects"], 0)
        self.assertEqual(dash["kpi_summary"]["achievement_pct"], 0.0)
        self.assertEqual(dash["kpi_summary"]["shortfall"], 1000)
        self.assertEqual(dash["counts"]["overdue"], 1)
        self.assertEqual(dash["counts"]["due_soon"], 1)
        self.assertEqual(dash["kpi_summary"]["on_time_count"], 2)
        self.assertEqual(dash["kpi_summary"]["submitted_total"], 3)
        self.assertEqual(dash["kpi_summary"]["on_time_pct"], 66.7)
        self.assertIsNotNone(dash["meta"]["last_cvat_sync_at"])

        for idx in range(11):
            self.f.job(
                status=JobStatus.PENDING_ANNOTATION,
                annotator=self.f.ann1,
                deadline=now + timedelta(hours=1 + idx),
                target_object_count=50,
            )
        rw_job = self.f.job(
            status=JobStatus.REWORK,
            annotator=self.f.ann1,
            rework_round=2,
            total_rework_rounds=2,
            deadline=now + timedelta(days=5),
            target_object_count=80,
        )
        ReviewError.objects.create(job=rw_job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category, severity="minor")
        ReviewError.objects.create(job=rw_job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category, severity="minor")
        ReviewError.objects.create(job=rw_job, stage=ReviewStage.QC1, rework_round=1, category=self.f.category, severity="major")

        dash3 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash3["meta"]["active_jobs_count"], 14)
        self.assertEqual(dash3["meta"]["active_object_frames"], 100 + 200 + 11 * 50 + 80)
        self.assertEqual(dash3["kpi_summary"]["max_rework_round_active"], 2)
        self.assertIsNotNone(dash3["rework_focus"])
        self.assertEqual(dash3["rework_focus"]["job_id"], rw_job.id)
        self.assertEqual(dash3["rework_focus"]["error_count"], 1)
        self.assertEqual(len(dash3["next_jobs"]), 10)

    def test_first_pass_yield_includes_rework_jobs_and_survives_escalation_reset(self) -> None:
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, rework_round=0, total_rework_rounds=0)
        for _ in range(9):
            self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1, rework_round=1, total_rework_rounds=1)

        ov = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov["metrics"]["first_pass_yield"]["value"], 10.0)
        self.assertEqual(ov["metrics"]["rework_rate"]["value"], 90.0)

        dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash["first_pass_yield"]["value"], 10.0)
        self.assertEqual(dash["kpi_summary"]["fpy_passed"], 1)
        self.assertEqual(dash["kpi_summary"]["fpy_total"], 10)

        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, rework_round=0, total_rework_rounds=3)
        ov2 = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov2["metrics"]["first_pass_yield"]["value"], 9.1)
        self.assertEqual(ov2["metrics"]["rework_rate"]["value"], 90.9)

        mp = self.pm.get(self.f.url("member-performance/")).data
        ann1_row = next(r for r in mp if r["user"]["id"] == self.f.ann1.id)
        self.assertEqual(ann1_row["rework_rate"], 90.9)

    def test_qc1_summary_mine_sees_pool_restricts_assigned_and_attributes_escapes_by_actor_and_period(self) -> None:
        other_qc1 = make_user("qc1_b", Role.QC1, project=self.f.project)

        pool_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)
        Job.objects.filter(pk=pool_job.pk).update(qc1_reviewer=None)
        locked_batch = Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="B_LOCK", status=DataStatus.LOCKED
        )
        locked_pool_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, batch=locked_batch)
        Job.objects.filter(pk=locked_pool_job.pk).update(qc1_reviewer=None)

        passed_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{passed_job.id}/pass/"), {}, format="json").status_code, 200)
        Job.objects.filter(pk=passed_job.pk).update(qc1_reviewer=other_qc1)

        ReviewError.objects.create(
            job=passed_job, stage=ReviewStage.QC2, rework_round=0, category=self.f.category, severity="major"
        )
        old_err = ReviewError.objects.create(
            job=passed_job, stage=ReviewStage.QC2, rework_round=0, category=self.f.category, severity="minor"
        )
        ReviewError.objects.filter(pk=old_err.pk).update(created_at=timezone.now() - timedelta(days=20))

        qc1_mine = self.qc1.get(self.f.url("qc1-summary/?period=week")).data
        other_mine = self.f.client(other_qc1).get(self.f.url("qc1-summary/?period=week")).data

        self.assertEqual(qc1_mine["stats"]["assigned"], 0)
        self.assertEqual(qc1_mine["stats"]["pool_pending"], 1)
        self.assertEqual(qc1_mine["stats"]["pending"], 1)
        self.assertEqual(qc1_mine["qc2_escape_errors"], 1)
        self.assertEqual(qc1_mine["escaped_jobs"], 1)
        self.assertEqual(other_mine["qc2_escape_errors"], 0)
        self.assertEqual(other_mine["escaped_jobs"], 0)

        # scope=project: pool chưa giao KHÔNG bị tính vào assigned, và job thuộc batch khoá bị loại khỏi pending
        pm_proj_before = self.pm.get(self.f.url("qc1-summary/?period=week")).data
        self.assertEqual(pm_proj_before["stats"]["assigned"], 0)
        self.assertEqual(pm_proj_before["stats"]["pool_pending"], 1)
        self.assertEqual(pm_proj_before["stats"]["pending"], 1)

        self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, qc1_reviewer=other_qc1)
        pm_proj_after = self.pm.get(self.f.url("qc1-summary/?period=week")).data
        self.assertEqual(pm_proj_after["stats"]["assigned"], 1)
        self.assertEqual(pm_proj_after["stats"]["pool_pending"], 1)
        self.assertEqual(pm_proj_after["stats"]["pending"], 2)

    def test_team_ranking_ranks_zero_output_below_real_output_and_excludes_voided_errors(self) -> None:
        t_zero = Team.objects.create(project=self.f.project, name="Team Zero")
        t_real = Team.objects.create(project=self.f.project, name="Team Real")
        TeamMember.objects.create(team=t_zero, user=self.f.ann1)
        TeamMember.objects.create(team=t_real, user=self.f.ann2)

        done_job = self.f.job(
            status=JobStatus.APPROVED, annotator=self.f.ann2, object_count=200, rework_round=1, total_rework_rounds=1
        )
        self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2, object_count=100)
        ReviewError.objects.create(
            job=done_job, stage=ReviewStage.QC2, rework_round=0, category=self.f.category, severity="minor", is_voided=True
        )

        res = self.pm.get(self.f.url("team-ranking/"))
        self.assertEqual(res.status_code, 200, res.data)
        rows = res.data["rows"]
        self.assertEqual([r["team"]["name"] for r in rows], ["Team Real", "Team Zero"])
        self.assertEqual([r["rank"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["rework_rate"], 50.0)
        self.assertEqual(rows[0]["qc2_errors"], 0)

    def test_invalid_date_range_query_returns_400(self) -> None:
        self.assertEqual(self.pm.get(self.f.url("overview/?date_from=invalid")).status_code, 400)
        self.assertEqual(
            self.pm.get(self.f.url("overview/?date_from=2026-11-27&date_to=2026-11-20")).status_code,
            400,
        )
