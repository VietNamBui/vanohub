from django.test import TestCase

from accounts.testing import ProjectFixture
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
