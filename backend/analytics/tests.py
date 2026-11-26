from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from cvat_integration.sync import sync_batch
from jobs.models import Job, JobStatus, ReworkScope
from projects.models import ActivityLog, Batch, Dataset
from quality.models import Audit, ErrorVerdict, ReviewError, ReviewStage, Severity


class AnnotatorAndQc1AnalyticsTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.ann1 = self.f.client(self.f.ann1)
        self.qc1 = self.f.client(self.f.qc1)
        self.pm = self.f.client(self.f.pm)

    def test_annotator_dashboard_stats_and_permissions(self):
        self.assertEqual(self.qc1.get(self.f.url("annotator/dashboard/")).status_code, 403)

        j1 = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1)
        j2 = self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, object_count=30)
        self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2)  # không tính vào ann1

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

    def test_annotator_dashboard_daily_actual_does_not_mix_lifetime_done(self):
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, object_count=500)
        res = self.ann1.get(self.f.url("annotator/dashboard/?period=week"))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["kpi_summary"]["actual_objects"], 0)

    def test_annotator_personal_analytics_p2_and_private_ranking(self):
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
        # KPI10: ann2 = 1000 > ann1 = 600 → ann1 hạng 2/2, không lộ tên hay điểm của ann2
        self.assertEqual(res.data["ranking"]["rank"], 2)
        self.assertEqual(res.data["ranking"]["total_annotators"], 2)
        self.assertNotIn("leaderboard", res.data["ranking"])
        self.assertEqual(len(res.data["daily_productivity"]), 7)
        self.assertEqual(len(res.data["weekly_forecast_series"]), 7)

    def test_qc1_summary_metrics_trend_and_escape_errors(self):
        self.assertEqual(self.ann1.get(self.f.url("qc1-summary/")).status_code, 403)

        j_pass = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)
        j_rej = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)

        self.qc1.post(self.f.url(f"qc1/jobs/{j_pass.id}/pass/"), {}, format="json")
        self.qc1.post(
            self.f.url(f"qc1/jobs/{j_rej.id}/reject/"),
            {"errors": [{"category": self.f.category.id, "description": "thieu"}]},
            format="json",
        )
        # Giả lập QC2 bắt được 1 lỗi sót trên job đã qua QC1
        ReviewError.objects.create(
            job=j_pass, stage=ReviewStage.QC2, rework_round=0, category=self.f.category, severity="major"
        )

        res = self.qc1.get(self.f.url("qc1-summary/?period=week"))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["scope"], "mine")
        self.assertEqual(res.data["stats"]["passed"], 1)
        self.assertEqual(res.data["stats"]["rejected"], 1)
        self.assertEqual(res.data["pass_rate"], 50.0)
        self.assertEqual(res.data["kpi"]["current"]["reviewed"], 2)
        self.assertEqual(res.data["kpi"]["current"]["errors"], 1)
        self.assertEqual(res.data["qc2_escape_errors"], 1)
        self.assertEqual(len(res.data["trend"]), 7)
        self.assertEqual(res.data["trend"][-1]["reviewed"], 2)

        # PM xem scope=project được
        pm_res = self.pm.get(self.f.url("qc1-summary/?period=week"))
        self.assertEqual(pm_res.status_code, 200, pm_res.data)
        self.assertEqual(pm_res.data["scope"], "project")
        self.assertEqual(pm_res.data["stats"]["passed"], 1)


class FormulaAndDailyOutputTests(TestCase):
    """Kiểm thử đầy đủ công thức đã chốt: SL01–SL06, KPI02–KPI09, NS03, CL01–CL11, RW02/RW04, TD05–TD13."""

    def setUp(self):
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

    def test_daily_output_counts_before_qc_and_unchanged_after_qc_pass_and_partial_vs_full_rework(self):
        self.f.batch.cvat_task_id = 900
        self.f.batch.save(update_fields=["cvat_task_id"])
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=901, object_count=0)

        class SyncClient:
            def __init__(self, cnt):
                self.cnt = cnt

            def list_task_jobs(self, task_id):
                return [{"id": 901, "type": "annotation", "stage": "annotation", "state": "in progress"}]

            def count_job_objects(self, job_id):
                return self.cnt

        # 1. Trước khi QC: đồng bộ thấy 80 cuboid → tính ngay 80 vào sản lượng hôm nay
        sync_batch(self.f.batch, self.f.pm, client=SyncClient(80), count_objects=True)
        d1 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(d1["kpi_summary"]["actual_objects"], 80)
        self.assertEqual(d1["kpi_summary"]["shortfall"], 20)
        self.assertEqual(d1["kpi_summary"]["surplus"], 0)
        self.assertEqual(d1["daily_results"][-1]["first_pass_objects"], 80)

        # 2. Nộp bài với 120 cuboid → chỉ cộng thêm delta +40 (tổng 120, surplus=20, không cộng đúp 80)
        self.assertEqual(
            self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {"object_count": 120}, format="json").status_code,
            200,
        )
        d2 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(d2["kpi_summary"]["actual_objects"], 120)
        self.assertEqual(d2["kpi_summary"]["achievement_pct"], 120.0)
        self.assertEqual(d2["kpi_summary"]["shortfall"], 0)
        self.assertEqual(d2["kpi_summary"]["surplus"], 20)

        # 3. Sau khi QC1 Pass → sản lượng hôm nay giữ nguyên 120 (không cộng đúp, không mất)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 200)
        d3 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(d3["kpi_summary"]["actual_objects"], 120)

        # 4. Partial rework trên job 120 cuboid có 2 lỗi duy nhất → nộp lại KHÔNG cộng lại 120, chỉ cộng +2 rework
        job_rw = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, object_count=0)
        self.ann1.post(self.f.url(f"annotator/jobs/{job_rw.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job_rw.id}/submit/"), {"object_count": 100}, format="json")
        self.qc1.post(
            self.f.url(f"qc1/jobs/{job_rw.id}/reject/"),
            {
                "rework_scope": ReworkScope.PARTIAL,
                "errors": [
                    {"category": self.f.category.id, "frame_number": 1, "cvat_object_id": 10},
                    {"category": self.f.category.id, "frame_number": 1, "cvat_object_id": 10},  # trùng cuboid
                    {"category": self.f.category.id, "frame_number": 2, "cvat_object_id": 11},
                ],
            },
            format="json",
        )
        self.ann1.post(self.f.url(f"annotator/jobs/{job_rw.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job_rw.id}/submit/"), {"object_count": 100}, format="json")
        d4 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(d4["daily_results"][-1]["first_pass_objects"], 220)  # 120 + 100
        self.assertEqual(d4["daily_results"][-1]["rework_objects"], 2)  # chỉ 2 cuboid lỗi duy nhất!
        self.assertEqual(d4["kpi_summary"]["actual_objects"], 222)

    def test_fpy_cl01_uses_immutable_first_qc1_result_across_rework_qc2_and_resolve_escalation(self):
        j1 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)
        j2 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)

        # j1 Pass QC1 lần đầu → sau đó bị QC2 Reject → vẫn là FPY Pass tại QC1
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{j1.id}/pass/"), {}, format="json").status_code, 200)
        Job.objects.filter(pk=j1.pk).update(status=JobStatus.PENDING_QC2)
        audit = self.pm.post(
            self.f.url("audits/"), {"batch": self.f.batch.id, "sampling_rate": 100, "auditors": [self.f.qc2.id]}, format="json"
        ).data
        sample = Audit.objects.get(pk=audit["id"]).samples.get(job=j1)
        self.qc2.post(
            self.f.url(f"audit-samples/{sample.id}/reject/"),
            {"errors": [{"category": self.f.category.id}]},
            format="json",
        )

        # j2 trượt QC1 lần đầu, đang nằm ở REWORK (chưa từng tới QC2) và bị escalate rồi PM gỡ escalation
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

        # FPY = 1 pass (j1) / 2 (j1 + j2) = 50.0% trên cả Overview, Annotator và QC1!
        ov = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov["metrics"]["first_pass_yield"]["value"], 50.0)
        self.assertEqual(ov["metrics"]["first_pass_yield"]["passed"], 1)
        self.assertEqual(ov["metrics"]["first_pass_yield"]["total"], 2)
        # RW02: cả j1 (bị QC2 reject) và j2 (dù rework_round bị reset = 0) vẫn có total_rework_rounds > 0 => 100%
        self.assertEqual(ov["metrics"]["rework_rate"]["value"], 100.0)

        ann_dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(ann_dash["kpi_summary"]["fpy_pct"], 50.0)
        qc1_sum = self.qc1.get(self.f.url("qc1-summary/")).data
        self.assertEqual(qc1_sum["first_pass_yield"]["value"], 50.0)
        self.assertEqual(qc1_sum["qc1_escape_job_rate"], 100.0)

    def test_quality_cl11_defect_cl02_cl05_edge_verdict_missing_objects_and_dispute_voiding_cl09(self):
        job = self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann1, object_count=100, first_qc1_result="pass")
        # 2 lỗi trên cùng cuboid (1, 10) [minor + critical] => khử trùng thành 1 fail critical
        e_dup1 = ReviewError.objects.create(
            job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category,
            severity=Severity.MINOR, verdict=ErrorVerdict.FAIL, frame_number=1, cvat_object_id=10,
        )
        ReviewError.objects.create(
            job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category,
            severity=Severity.CRITICAL, verdict=ErrorVerdict.FAIL, frame_number=1, cvat_object_id=10,
        )
        # 1 cuboid Edge => tính vào Pass+Edge của CL11, không tính vào Fail của CL02
        ReviewError.objects.create(
            job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category,
            severity=Severity.MINOR, verdict=ErrorVerdict.EDGE, frame_number=2, cvat_object_id=11,
        )
        # 1 lỗi thiếu đối tượng tường minh (is_missing_object=True) => cộng +1 vào mẫu số (101)
        ReviewError.objects.create(
            job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category,
            severity=Severity.MAJOR, verdict=ErrorVerdict.FAIL, frame_number=5, cvat_object_id=None,
            is_missing_object=True,
        )
        # 1 lỗi trùng (frame=5, category) cũng is_missing_object=True => khử trùng, không cộng thành 2
        ReviewError.objects.create(
            job=job, stage=ReviewStage.QC2, rework_round=0, category=self.f.category,
            severity=Severity.MAJOR, verdict=ErrorVerdict.FAIL, frame_number=5, cvat_object_id=None,
            is_missing_object=True,
        )

        ov = self.pm.get(self.f.url("overview/")).data
        # fail=2 / (100 + 1) = 1.98%, quality_cl = 98.02%
        self.assertEqual(ov["metrics"]["defect_error_rate"]["value"], 1.98)
        self.assertEqual(ov["metrics"]["quality_cl"]["value"], 98.02)
        self.assertEqual(ov["metrics"]["quality_cl"]["edge_objects"], 1)
        self.assertEqual(ov["metrics"]["defect_rate_by_severity"]["value"][Severity.CRITICAL], 0.99)
        self.assertEqual(ov["metrics"]["defect_rate_by_severity"]["value"][Severity.MAJOR], 0.99)
        self.assertEqual(ov["errors_by_severity"][Severity.CRITICAL], 1)

        # Tạo 2 khiếu nại lỗi: 1 resolved (hủy e_dup1) + 1 rejected => CL09 = 50.0%
        d1 = self.ann1.post(
            self.f.url("annotator/requests/"),
            {"job": job.id, "review_error": e_dup1.id, "request_type": "error_dispute", "reason": "Không sai"},
            format="json",
        ).data
        d2 = self.ann1.post(
            self.f.url("annotator/requests/"),
            {"job": job.id, "request_type": "error_dispute", "reason": "Kiểm lại giúp"},
            format="json",
        ).data
        self.pm.post(self.f.url(f"annotator/requests/{d1['id']}/resolve/"), {"status": "resolved"}, format="json")
        self.pm.post(self.f.url(f"annotator/requests/{d2['id']}/resolve/"), {"status": "rejected"}, format="json")

        ov2 = self.pm.get(self.f.url("overview/")).data
        self.assertEqual(ov2["metrics"]["dispute_overturn_rate"]["value"], 50.0)
        self.assertEqual(ov2["errors_by_severity"][Severity.MINOR], 1)  # e_dup1 (minor) đã bị void

    def test_qc2_summary_no_cover_double_count_batch_id_grouping_and_kpis(self):
        other_qc2 = make_user("qc2_cover", Role.QC2, project=self.f.project)
        ds2 = Dataset.objects.create(project=self.f.project, name="D2")
        batch_same_name = Batch.objects.create(dataset=ds2, name=self.f.batch.name)
        j1 = self.f.job(status=JobStatus.PENDING_QC2, object_count=50)
        j2 = Job.objects.create(
            project=self.f.project, batch=batch_same_name, name="J-D2",
            status=JobStatus.PENDING_QC2, annotator=self.f.ann2, object_count=50,
        )

        a1 = self.pm.post(
            self.f.url("audits/"), {"batch": self.f.batch.id, "sampling_rate": 100, "auditors": [self.f.qc2.id]}, format="json"
        ).data
        a2 = self.pm.post(
            self.f.url("audits/"), {"batch": batch_same_name.id, "sampling_rate": 100, "auditors": [other_qc2.id]}, format="json"
        ).data
        s1 = Audit.objects.get(pk=a1["id"]).samples.get(job=j1)
        s2 = Audit.objects.get(pk=a2["id"]).samples.get(job=j2)

        # PM chấm hộ mẫu s1 vốn giao cho self.f.qc2 → KHÔNG cộng sản lượng cho self.f.qc2 (không cover hộ)
        self.assertEqual(self.pm.post(self.f.url(f"audit-samples/{s1.id}/pass/"), {}, format="json").status_code, 200)
        self.assertEqual(
            self.f.client(other_qc2).post(self.f.url(f"audit-samples/{s2.id}/pass/"), {}, format="json").status_code, 200
        )

        qc2_mine = self.qc2.get(self.f.url("qc2-summary/?scope=mine")).data
        self.assertEqual(qc2_mine["stats"]["passed"], 0)
        self.assertEqual(qc2_mine["kpi_summary"]["actual"], 0)

        pm_mine = self.pm.get(self.f.url("qc2-summary/?scope=mine")).data
        self.assertEqual(pm_mine["stats"]["passed"], 1)
        self.assertEqual(pm_mine["kpi_target"], 2)
        self.assertEqual(pm_mine["kpi_summary"]["achievement_pct"], 50.0)
        self.assertEqual(pm_mine["kpi"]["comparison"]["audited"]["delta"], 1)
        self.assertIsNone(pm_mine["kpi"]["comparison"]["audited"]["pct_change"])  # kỳ trước = 0

        # Hai batch trùng tên ở 2 dataset khác nhau phải tách riêng trong progress_by_batch
        pm_proj = self.pm.get(self.f.url("qc2-summary/")).data
        self.assertEqual(len(pm_proj["progress_by_batch"]), 2)
        self.assertEqual({r["dataset_name"] for r in pm_proj["progress_by_batch"]}, {"D1", "D2"})

    def test_annotator_analytics_no_lifetime_fallback_split_hours_and_reassignment_attribution(self):
        # Không có DailyOutputRecord trong kỳ dù có job APPROVED cũ → phải trả 0 (không fallback lifetime)
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, object_count=999)
        empty_res = self.ann1.get(self.f.url("annotator/analytics/?range=7d")).data
        self.assertEqual(empty_res["avg_productivity"]["total_objects"], 0)

        # Tách riêng giờ làm đầu (2h cho 200 cuboid = 100/h) và giờ rework (1h cho 10 cuboid = 10/h)
        now = timezone.now()
        j_fp = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, object_count=0)
        self.ann1.post(self.f.url(f"annotator/jobs/{j_fp.id}/start/"), {}, format="json")
        start_fp = ActivityLog.objects.filter(job=j_fp, action="job.status", after__status=JobStatus.ANNOTATING).first()
        assert start_fp is not None
        ActivityLog.objects.filter(pk=start_fp.pk).update(created_at=now - timedelta(hours=2))
        self.ann1.post(self.f.url(f"annotator/jobs/{j_fp.id}/submit/"), {"object_count": 200}, format="json")

        j_rw = self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1, rework_round=1, total_rework_rounds=1, rework_scope=ReworkScope.FULL, object_count=10)
        self.ann1.post(self.f.url(f"annotator/jobs/{j_rw.id}/start/"), {}, format="json")
        start_rw = ActivityLog.objects.filter(job=j_rw, action="job.status", after__status=JobStatus.ANNOTATING).first()
        assert start_rw is not None
        ActivityLog.objects.filter(pk=start_rw.pk).update(created_at=now - timedelta(hours=1))
        self.ann1.post(self.f.url(f"annotator/jobs/{j_rw.id}/submit/"), {"object_count": 10}, format="json")

        # Giao lại j_fp cho ann2 → sản lượng 200 cuboid vẫn giữ nguyên cho ann1 (SL04)
        self.pm.post(self.f.url(f"jobs/{j_fp.id}/assign/"), {"annotator": self.f.ann2.id}, format="json")

        analytics = self.ann1.get(self.f.url("annotator/analytics/?range=7d")).data
        today_row = analytics["daily_productivity"][-1]
        self.assertEqual(today_row["first_pass_objects"], 200)
        self.assertEqual(today_row["rework_objects"], 10)
        self.assertAlmostEqual(today_row["first_pass_per_hour"], 100.0, delta=2.0)
        self.assertAlmostEqual(today_row["rework_per_hour"], 10.0, delta=0.5)

        perf = {r["user"]["id"]: r for r in self.pm.get(self.f.url("member-performance/")).data}
        self.assertEqual(perf[self.f.ann1.id]["total_objects"], 210)
        self.assertEqual(perf[self.f.ann2.id]["total_objects"], 0)

    def test_overview_active_members_unions_all_roles_and_stage_progress_and_pending_decisions(self):
        # 1 job annotating (ann1), 1 job pending_qc1 (qc1), 1 job pending_qc2 in open audit (qc2)
        j_anno = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1)
        Job.objects.filter(pk=j_anno.pk).update(qc1_reviewer=None)
        self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)
        j_qc2 = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann2)
        self.pm.post(
            self.f.url("audits/"), {"batch": self.f.batch.id, "sampling_rate": 100, "auditors": [self.f.qc2.id]}, format="json"
        )
        self.assertEqual(j_qc2.status, JobStatus.PENDING_QC2)

        ov = self.pm.get(self.f.url("overview/")).data
        # ann1 (Anno) + qc1 (QC1) + qc2 (QC2) = 3 người duy nhất (ann2 không đang giữ job ở active anno!)
        self.assertEqual(ov["metrics"]["active_members"]["value"], 3)
        self.assertEqual(ov["counts"]["remaining_jobs"], 3)
        self.assertEqual(ov["stage_progress"]["annotation_passed"], 66.7)
        self.assertEqual(ov["stage_progress"]["qc1_passed"], 33.3)
        self.assertEqual(ov["stage_progress"]["qc2_approved"], 0.0)
        self.assertIn("pending_decisions", ov)

    def test_post_escalation_partial_rework_missing_and_bonus_cuboids_accuracy(self):
        # 1. Job trải qua escalation + resolve-escalation (rework_round reset -> 0), rồi bị reject lại 1 lỗi mới
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, object_count=0)
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {"object_count": 50}, format="json")
        # 3 lỗi vòng 0 -> vòng 1 -> giả lập escalate ở vòng 3
        self.qc1.post(
            self.f.url(f"qc1/jobs/{job.id}/reject/"),
            {
                "rework_scope": ReworkScope.PARTIAL,
                "errors": [
                    {"category": self.f.category.id, "frame_number": 1, "cvat_object_id": 1},
                    {"category": self.f.category.id, "frame_number": 2, "cvat_object_id": 2},
                    {"category": self.f.category.id, "frame_number": 3, "cvat_object_id": 3},
                ],
            },
            format="json",
        )
        Job.objects.filter(pk=job.pk).update(rework_round=3, total_rework_rounds=3, is_escalated=True)
        self.pm.post(self.f.url(f"jobs/{job.id}/resolve-escalation/"), {}, format="json")
        # Nộp lại vòng hậu escalation rồi QC1 reject mới với 2 lỗi có sẵn + 1 lỗi thiếu
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
        # Kiểm tra ReviewError mới có rework_round = 3 (> 0 cũ), nên rework_focus chỉ hiển thị 3 lỗi mới
        dash_before = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash_before["rework_focus"]["error_count"], 3)
        self.assertEqual(dash_before["rework_focus"]["pending_object_frames"], 3)

        # Annotator sửa 2 cuboid có sẵn + vẽ thêm 3 cuboid mới (gồm 1 missing + 2 bonus): 50 -> 53
        # Công thức chính xác: existing(2) + max(missing(1), added(3)) = 5!
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json")
        sub = self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {"object_count": 53}, format="json").data
        self.assertEqual(sub["timeline"][-1]["after"]["credited_objects"], 5)

    def test_multi_audit_qc2_quality_cl_and_qc1_escape_no_double_blame_and_reassigned_done_no_double_count(self):
        qc1_b = make_user("qc1_second", Role.QC1, project=self.f.project)
        qc1_b_client = self.f.client(qc1_b)

        # 1. Job 100 cuboid do ann1 làm, nộp, QC1-A duyệt pass → Audit #1 Pass (0 lỗi)
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, object_count=0)
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {"object_count": 100}, format="json")
        self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json")
        self.pm.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        a1 = self.pm.post(
            self.f.url("audits/"), {"batch": self.f.batch.id, "sampling_rate": 100, "auditors": [self.f.qc2.id]}, format="json"
        ).data
        s1 = Audit.objects.get(pk=a1["id"]).samples.get(job=job)
        self.qc2.post(self.f.url(f"audit-samples/{s1.id}/pass/"), {}, format="json")
        # PM trả cả batch để chạy vòng 2
        self.pm.post(self.f.url(f"audits/{a1['id']}/complete/"), {"decision": "reject", "reason": "chạy lại"}, format="json")

        # 2. Vòng 2 đổi QC1 sang qc1_b → qc1_b duyệt pass → Audit #2 Reject với 4 lỗi
        self.pm.post(self.f.url(f"jobs/{job.id}/assign/"), {"qc1_reviewer": qc1_b.id}, format="json")
        # Thay đổi object_count sau khi Audit #1 đã chấm (100 -> 150) không được làm méo snapshot của Audit #1 (100 + 150 = 250)
        Job.objects.filter(pk=job.pk).update(object_count=150)
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {"object_count": 150}, format="json")
        qc1_b_client.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json")
        self.pm.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        a2 = self.pm.post(
            self.f.url("audits/"), {"batch": self.f.batch.id, "sampling_rate": 100, "auditors": [self.f.qc2.id]}, format="json"
        ).data
        s2 = Audit.objects.get(pk=a2["id"]).samples.get(job=job)
        self.qc2.post(
            self.f.url(f"audit-samples/{s2.id}/reject/"),
            {
                "errors": [
                    {"category": self.f.category.id, "frame_number": i, "cvat_object_id": i + 1}
                    for i in range(5)
                ]
            },
            format="json",
        )

        # Qc2Summary: Audit #1 (snapshot 100) + Audit #2 (snapshot 150) = 250 checked cuboids, 5 fail => 2.0%, 98.0%!
        qc2_sum = self.qc2.get(self.f.url("qc2-summary/?scope=mine")).data
        self.assertEqual(qc2_sum["error_percent_in_job"]["checked_objects"], 250)
        self.assertEqual(qc2_sum["error_percent_in_job"]["value"], 2.0)
        self.assertEqual(qc2_sum["quality_cl"]["value"], 98.0)

        # Qc1Summary: KHÔNG đổ lỗi kép cho QC1-A (Audit #1 đạt 0 lỗi), chỉ tính lỗi sót cho QC1-B (Audit #2)
        qc1_a_sum = self.qc1.get(self.f.url("qc1-summary/?scope=mine")).data
        qc1_b_sum = qc1_b_client.get(self.f.url("qc1-summary/?scope=mine")).data
        self.assertEqual(qc1_a_sum["qc2_escape_errors"], 0)
        self.assertEqual(qc1_a_sum["qc1_escape_job_rate"], 0.0)
        self.assertEqual(qc1_b_sum["qc2_escape_errors"], 5)
        self.assertEqual(qc1_b_sum["qc1_escape_job_rate"], 100.0)

        # Đổi annotator của job đã APPROVED sang ann2 → MemberPerformance không được cộng đúp cho ann2
        Job.objects.filter(pk=job.pk).update(status=JobStatus.APPROVED, annotator=self.f.ann2)
        perf = {r["user"]["id"]: r for r in self.pm.get(self.f.url("member-performance/")).data}
        self.assertEqual(perf[self.f.ann1.id]["objects_done"], 250)  # 100 fp + 150 full rw
        self.assertEqual(perf[self.f.ann2.id]["objects_done"], 0)

    def test_dh06_deadline_snapshot_and_ns03_mixed_sync_submit_day_and_unchecked_error_exclusion(self):
        now = timezone.now()
        # 1. DH06: nộp TRỄ hạn gốc, sau đó PM gia hạn deadline mới -> vẫn phải tính là trễ (0%)
        j_late = self.f.job(
            status=JobStatus.PENDING_ANNOTATION,
            annotator=self.f.ann1,
            deadline=now - timedelta(hours=2),
            object_count=0,
        )
        self.ann1.post(self.f.url(f"annotator/jobs/{j_late.id}/start/"), {}, format="json")
        self.ann1.post(self.f.url(f"annotator/jobs/{j_late.id}/submit/"), {"object_count": 20}, format="json")
        # PM gia hạn thêm 2 ngày sau khi đã nộp trễ
        self.pm.post(
            self.f.url(f"jobs/{j_late.id}/deadline/"),
            {"deadline": (now + timedelta(days=2)).isoformat().replace("+00:00", "Z"), "note": "gia han"},
            format="json",
        )
        dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash["kpi_summary"]["on_time_pct"], 0.0)

        # 2. Lỗi nằm trên job chưa qua QC (ANNOTATING, first_qc1_result="") không được rò vào CL02/CL11
        j_uncheck = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann2, object_count=0)
        ReviewError.objects.create(
            job=j_uncheck, stage=ReviewStage.QC1, rework_round=0, category=self.f.category,
            severity=Severity.CRITICAL, frame_number=1, cvat_object_id=None,
        )
        ov = self.pm.get(self.f.url("overview/")).data
        self.assertIsNone(ov["metrics"]["defect_error_rate"]["value"])
        self.assertIsNone(ov["metrics"]["quality_cl"]["value"])

        # 3. NS03: không bịa 7.5h cho ngày đồng bộ trước QC và hợp nhất giờ song song khi WIP=2
        from jobs.models import DailyOutputRecord, record_daily_output

        record_daily_output(
            job=j_uncheck, user=self.f.ann2, object_count=100, is_rework=False,
            rework_round=0, source=DailyOutputRecord.Source.CVAT_SYNC,
        )
        # Hai job rework chạy song song cùng 1 khung giờ [now-1h, now] -> hợp nhất chỉ tính 1.0h (không phải 2.0h!)
        j_rw2 = self.f.job(
            status=JobStatus.REWORK, annotator=self.f.ann2,
            rework_round=1, total_rework_rounds=1, rework_scope=ReworkScope.FULL, object_count=10,
        )
        j_rw3 = self.f.job(
            status=JobStatus.REWORK, annotator=self.f.ann2,
            rework_round=1, total_rework_rounds=1, rework_scope=ReworkScope.FULL, object_count=20,
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
        self.assertEqual(today_row["first_pass_per_hour"], 0)  # không bịa giờ cho nhánh chưa có phiên đo
        self.assertAlmostEqual(today_row["rework_per_hour"], 30.0, delta=1.5)  # 30 cuboid / 1.0h hợp nhất
        self.assertAlmostEqual(today_row["hours"], 1.0, delta=0.1)  # không cộng đúp thành 2.0h và không bịa 7.5h
        # avg_productivity chỉ chia measured_objects (30) / 1.0h = 30 (không chia nhầm 130 / 1.0h!)
        self.assertEqual(ann2_ana["avg_productivity"]["total_objects"], 130)
        self.assertAlmostEqual(ann2_ana["avg_productivity"]["objects_per_hour"], 30, delta=2)
