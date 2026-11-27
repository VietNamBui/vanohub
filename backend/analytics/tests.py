from accounts.testing import ProjectFixture
from django.test import TestCase
from jobs.models import JobStatus
from quality.models import ReviewError, ReviewStage


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


class AnalyticsBugFixTests(TestCase):
    """Kiểm thử hồi quy P1 cho analytics: múi giờ VN UTC+7, không bịa số fallback, FPY sau escalation, QC1/QC2 scope."""

    def setUp(self):
        self.f = ProjectFixture()
        self.f.project.kpi_annotation_target = 1000
        self.f.project.save(update_fields=["kpi_annotation_target"])
        self.ann1 = self.f.client(self.f.ann1)
        self.ann2 = self.f.client(self.f.ann2)
        self.qc1 = self.f.client(self.f.qc1)
        self.qc2 = self.f.client(self.f.qc2)
        self.pm = self.f.client(self.f.pm)

    def test_vietnam_timezone_cutoff_for_daily_buckets_and_alert_formatting(self):
        from datetime import UTC, datetime
        from unittest.mock import patch

        from projects.models import ActivityLog
        from quality.qc2 import ensure_qc2_sample

        # 2026-11-26 18:00 UTC == 2026-11-27 01:00 Asia/Ho_Chi_Minh (qua ngày mới ở VN nhưng vẫn 26/11 ở UTC)
        fixed_now = datetime(2026, 11, 26, 18, 0, tzinfo=UTC)
        job = self.f.job(
            status=JobStatus.PENDING_QC2,
            annotator=self.f.ann1,
            object_count=250,
            deadline=datetime(2026, 11, 26, 17, 30, tzinfo=UTC),  # 27/11 00:30 VN (quá hạn 30p)
        )
        ev = ActivityLog.record(
            project=self.f.project,
            actor=self.f.ann1,
            action="job.status",
            target=job,
            job=job,
            after={"status": JobStatus.PENDING_QC1, "event": "annotator.submit", "rework_round": 0, "object_count": 250},
        )
        ActivityLog.objects.filter(pk=ev.pk).update(created_at=fixed_now)

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
        sample.result = sample.Result.PASS
        sample.reviewed_by = self.f.qc2
        sample.reviewed_at = fixed_now
        sample.save(update_fields=["result", "reviewed_by", "reviewed_at"])

        with patch("django.utils.timezone.now", return_value=fixed_now):
            dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
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

            overview = self.pm.get(self.f.url("overview/")).data
            overdue_alerts = [a for a in overview["alerts"] if a["type"] == "overdue"]
            self.assertEqual(len(overdue_alerts), 1)
            self.assertIn("27/11 00:30", overdue_alerts[0]["message"])

    def test_annotator_dashboard_zero_today_no_all_time_fallback_and_rework_dedup(self):
        from datetime import timedelta

        from django.utils import timezone
        from jobs.models import Job
        from projects.models import ActivityLog

        now = timezone.now()
        self.f.project.cvat_synced_at = now - timedelta(minutes=5)
        self.f.project.save(update_fields=["cvat_synced_at"])

        # Job đã hoàn tất từ trước (500 objects) — không được rơi vào sản lượng hôm nay
        self.f.job(
            status=JobStatus.APPROVED,
            annotator=self.f.ann1,
            object_count=500,
            deadline=now + timedelta(days=1),
            submitted_at=now - timedelta(days=2),
        )
        # Job quá hạn đang giữ (active overdue) + job sắp hạn (trong 24h) + job đang chờ QC1 đã quá hạn (không tính active overdue)
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
            submitted_at=now - timedelta(hours=4),  # nộp trước hạn
        )

        dash = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash["kpi_summary"]["actual_objects"], 0)
        self.assertEqual(dash["kpi_summary"]["achievement_pct"], 0.0)
        self.assertEqual(dash["kpi_summary"]["shortfall"], 1000)
        # overdue & due_soon chỉ tính trên ACTIVE_ANNOTATOR_STATUSES và tách biệt nhau
        self.assertEqual(dash["counts"]["overdue"], 1)
        self.assertEqual(dash["counts"]["due_soon"], 1)
        # on_time: 2 job nộp đúng hạn + 1 job active quá hạn bị tính trễ → 2 / 3 = 66.7%
        self.assertEqual(dash["kpi_summary"]["on_time_count"], 2)
        self.assertEqual(dash["kpi_summary"]["submitted_total"], 3)
        self.assertEqual(dash["kpi_summary"]["on_time_pct"], 66.7)
        self.assertIsNotNone(dash["meta"]["last_cvat_sync_at"])

        # Nộp lại rework nhiều lần cùng ngày không thổi phồng actual_objects
        j_rw = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, object_count=300, rework_round=2)
        ActivityLog.record(
            project=self.f.project, actor=self.f.ann1, action="job.status", target=j_rw, job=j_rw,
            after={"status": JobStatus.PENDING_QC1, "event": "annotator.submit", "rework_round": 0, "object_count": 300},
        )
        for r in (1, 2):
            ActivityLog.record(
                project=self.f.project, actor=self.f.ann1, action="job.status", target=j_rw, job=j_rw,
                after={"status": JobStatus.PENDING_QC1, "event": "annotator.resubmit", "rework_round": r, "object_count": 300},
            )
        dash2 = self.ann1.get(self.f.url("annotator/dashboard/")).data
        self.assertEqual(dash2["kpi_summary"]["actual_objects"], 300)
        self.assertEqual(dash2["kpi_summary"]["today_first_pass"], 300)
        self.assertEqual(dash2["kpi_summary"]["today_rework"], 300)

        # rework_focus tìm trên toàn bộ active_qs (> 10 job) và chỉ đếm lỗi vòng mới nhất
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
        # 2 lỗi cũ vòng 0, 1 lỗi mới nhất vòng 1
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
        self.assertEqual(Job.objects.filter(project=self.f.project, annotator=self.f.ann1, status=JobStatus.REWORK).count(), 1)

    def test_annotator_analytics_zero_activity_no_fake_hours_and_no_rework_rank_inflation(self):
        from projects.models import ActivityLog

        # Có job APPROVED từ trước nhưng 0 hoạt động trong cửa sổ → không bịa 7.5h / sản lượng toàn thời gian
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, object_count=900)
        res = self.ann1.get(self.f.url("annotator/analytics/?range=7d")).data
        self.assertEqual(res["avg_productivity"]["total_objects"], 0)
        self.assertEqual(res["avg_productivity"]["total_hours"], 0)
        self.assertEqual(res["avg_productivity"]["objects_per_hour"], 0)
        self.assertEqual(res["forecast"]["avg_daily_objects"], 0)
        self.assertIsNone(res["ranking"]["previous_rank"])

        # Nộp bài thiếu started_at → không bịa 7.5 giờ
        j1 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, object_count=400, started_at=None)
        ActivityLog.record(
            project=self.f.project, actor=self.f.ann1, action="job.status", target=j1, job=j1,
            after={"status": JobStatus.PENDING_QC1, "event": "annotator.submit", "rework_round": 0, "object_count": 400},
        )
        # ann2 nộp lần đầu 300 nhưng nộp lại rework 3 lần (900) → chỉ tính 300 lần đầu, đứng sau ann1 (400)!
        j2 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2, object_count=300, started_at=None)
        ActivityLog.record(
            project=self.f.project, actor=self.f.ann2, action="job.status", target=j2, job=j2,
            after={"status": JobStatus.PENDING_QC1, "event": "annotator.submit", "rework_round": 0, "object_count": 300},
        )
        for r in (1, 2, 3):
            ActivityLog.record(
                project=self.f.project, actor=self.f.ann2, action="job.status", target=j2, job=j2,
                after={"status": JobStatus.PENDING_QC1, "event": "annotator.resubmit", "rework_round": r, "object_count": 300},
            )

        res2 = self.ann1.get(self.f.url("annotator/analytics/?range=7d")).data
        self.assertEqual(res2["avg_productivity"]["total_objects"], 400)
        self.assertEqual(res2["avg_productivity"]["total_hours"], 0.0)
        self.assertEqual(res2["avg_productivity"]["objects_per_hour"], 0)
        self.assertEqual(res2["ranking"]["rank"], 1)
        self.assertIsNone(res2["ranking"]["previous_rank"])

    def test_first_pass_yield_includes_rework_jobs_and_survives_escalation_reset(self):
        # 1 job pass lần đầu + 9 job đang REWORK → FPY = 1 / 10 = 10.0%
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

        # Thêm 1 job đã từng escalate và được reset rework_round=0 nhưng total_rework_rounds=3, giờ đạt APPROVED
        # → KHÔNG được tính là first_pass và VẪN tính là reworked!
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, rework_round=0, total_rework_rounds=3)
        ov2 = self.pm.get(self.f.url("overview/")).data
        # 1 first_pass / 11 fpy_total = 9.1%; 10 reworked / 11 total = 90.9%
        self.assertEqual(ov2["metrics"]["first_pass_yield"]["value"], 9.1)
        self.assertEqual(ov2["metrics"]["rework_rate"]["value"], 90.9)

        mp = self.pm.get(self.f.url("member-performance/")).data
        ann1_row = next(r for r in mp if r["user"]["id"] == self.f.ann1.id)
        self.assertEqual(ann1_row["rework_rate"], 90.9)

    def test_qc2_summary_mine_does_not_double_count_pm_override(self):
        from quality.qc2 import ensure_qc2_sample

        job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1)
        sample = ensure_qc2_sample(job)
        self.assertEqual(sample.auditor_id, self.f.qc2.id)

        # PM trực tiếp duyệt mẫu vốn được phân cho qc2
        res = self.pm.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)

        qc2_mine = self.qc2.get(self.f.url("qc2-summary/?scope=mine")).data
        pm_mine = self.pm.get(self.f.url("qc2-summary/?scope=mine")).data
        project_all = self.pm.get(self.f.url("qc2-summary/")).data

        # Chỉ người review thực tế (PM) được tính passed=1; qc2 không bị đếm trùng
        self.assertEqual(qc2_mine["stats"]["passed"], 0)
        self.assertEqual(qc2_mine["stats"]["pending"], 0)
        self.assertEqual(pm_mine["stats"]["passed"], 1)
        self.assertEqual(qc2_mine["stats"]["passed"] + pm_mine["stats"]["passed"], project_all["stats"]["passed"])

    def test_qc1_summary_mine_sees_pool_restricts_assigned_and_attributes_escapes_by_actor_and_period(self):
        from datetime import timedelta

        from accounts.models import Role
        from accounts.testing import make_user
        from django.utils import timezone
        from jobs.models import Job
        from projects.models import Batch, DataStatus

        other_qc1 = make_user("qc1_b", Role.QC1, project=self.f.project)

        # 1 job unassigned trong pool hợp lệ + 1 job unassigned trong batch đã khoá (không tính)
        pool_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)
        Job.objects.filter(pk=pool_job.pk).update(qc1_reviewer=None)
        locked_batch = Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="B_LOCK", status=DataStatus.LOCKED
        )
        locked_pool_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, batch=locked_batch)
        Job.objects.filter(pk=locked_pool_job.pk).update(qc1_reviewer=None)

        # 1 job đã pass bởi self.f.qc1 → sau đó đổi qc1_reviewer sang other_qc1
        passed_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{passed_job.id}/pass/"), {}, format="json").status_code, 200)
        Job.objects.filter(pk=passed_job.pk).update(qc1_reviewer=other_qc1)

        # Lỗi QC2 phát hiện hôm nay (trong kỳ week) và 1 lỗi quá cũ (20 ngày trước → ngoài kỳ week)
        ReviewError.objects.create(
            job=passed_job, stage=ReviewStage.QC2, rework_round=0, category=self.f.category, severity="major"
        )
        old_err = ReviewError.objects.create(
            job=passed_job, stage=ReviewStage.QC2, rework_round=0, category=self.f.category, severity="minor"
        )
        ReviewError.objects.filter(pk=old_err.pk).update(created_at=timezone.now() - timedelta(days=20))

        qc1_mine = self.qc1.get(self.f.url("qc1-summary/?period=week")).data
        other_mine = self.f.client(other_qc1).get(self.f.url("qc1-summary/?period=week")).data

        # qc1 thấy pool_job trong pending & pool_pending; assigned chỉ tính active QC1 statuses (=0 vì passed_job đã sang PENDING_QC2)
        self.assertEqual(qc1_mine["stats"]["assigned"], 0)
        self.assertEqual(qc1_mine["stats"]["pool_pending"], 1)
        self.assertEqual(qc1_mine["stats"]["pending"], 1)
        # Escape error thuộc về self.f.qc1 (người bấm qc1.pass), chỉ tính trong kỳ (=1, bỏ lỗi 20 ngày trước)
        self.assertEqual(qc1_mine["qc2_escape_errors"], 1)
        self.assertEqual(other_mine["qc2_escape_errors"], 0)

    def test_team_ranking_ranks_zero_output_below_real_output_without_n_plus_1(self):
        from teams.models import Team, TeamMember

        t_zero = Team.objects.create(project=self.f.project, name="Team Zero")
        t_real = Team.objects.create(project=self.f.project, name="Team Real")
        TeamMember.objects.create(team=t_zero, user=self.f.ann1)
        TeamMember.objects.create(team=t_real, user=self.f.ann2)

        # Team Real có 200 objects đã xong (dù có rework 50%); Team Zero có 0 objects đã xong
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann2, object_count=200, rework_round=1, total_rework_rounds=1)
        self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2, object_count=100)

        res = self.pm.get(self.f.url("team-ranking/"))
        self.assertEqual(res.status_code, 200, res.data)
        rows = res.data["rows"]
        self.assertEqual([r["team"]["name"] for r in rows], ["Team Real", "Team Zero"])
        self.assertEqual([r["rank"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["rework_rate"], 50.0)
