from django.test import TestCase

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from jobs.models import Job, JobStatus

from .models import Audit, AuditSample, ReviewError
from .qc2 import ensure_qc2_sample, pick_frames


class FrameSamplingTests(TestCase):
    """QC2 kiểm MỌI job qua QC1, mỗi job sampling_rate % số frame (làm tròn lên, ít nhất 1)."""

    def setUp(self):
        self.f = ProjectFixture()
        self.f.project.sampling_rate = 20
        self.f.project.save()

    def test_frame_count_rounds_up_with_minimum_one(self):
        job = self.f.job(frame_count=10, cvat_start_frame=100)
        frames = pick_frames(job, 20)
        self.assertEqual(len(frames), 2)
        self.assertTrue(all(100 <= f < 110 for f in frames))  # đánh số theo task, như trên CVAT
        self.assertEqual(len(pick_frames(self.f.job(frame_count=11), 20)), 3)
        self.assertEqual(len(pick_frames(self.f.job(frame_count=1), 20)), 1)

    def test_same_job_and_round_gives_same_frames(self):
        job = self.f.job(frame_count=50)
        self.assertEqual(pick_frames(job, 20), pick_frames(job, 20))

    def test_every_pending_qc2_job_gets_one_open_sample_in_task_audit(self):
        jobs = [self.f.job(frame_count=10) for _ in range(3)]
        for job in jobs:
            ensure_qc2_sample(job)
            ensure_qc2_sample(job)  # gọi lại không tạo trùng
        self.assertEqual(AuditSample.objects.count(), 3)
        self.assertEqual(Audit.objects.filter(batch=self.f.batch).count(), 1)
        self.assertEqual(AuditSample.objects.first().auditor, self.f.qc2)  # tự giao QC2 chuyên trách

    def test_jobs_not_waiting_for_qc2_get_no_sample(self):
        self.assertIsNone(ensure_qc2_sample(self.f.job(status=JobStatus.PENDING_QC1)))

    def test_auto_assign_respects_four_eyes(self):
        job = self.f.job(annotator=self.f.qc2, frame_count=5)
        self.assertIsNone(ensure_qc2_sample(job).auditor)  # QC2 duy nhất đã annotate → để trống cho PM phân


class Qc2ReviewTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.qc2 = self.f.client(self.f.qc2)
        self.job = self.f.job(frame_count=10)
        self.sample = ensure_qc2_sample(self.job)

    def test_audits_are_read_only(self):
        response = self.pm.post(self.f.url("audits/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(response.status_code, 405)
        listed = self.pm.get(self.f.url("audits/")).data
        self.assertEqual((len(listed), listed[0]["sample_count"]), (1, 1))

    def test_qc2_passes_job(self):
        listed = self.qc2.get(self.f.url("audit-samples/?result=pending")).data
        self.assertEqual([s["id"] for s in listed], [self.sample.id])
        self.assertEqual(len(listed[0]["frames"]), 5)  # fixture: sampling_rate 50% của 10 frame
        response = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/pass/"), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.APPROVED)

    def test_reject_sends_job_to_rework_and_next_round_gets_new_sample(self):
        body = {"errors": [{"category": self.f.category.id, "location": "frame 3"}], "comment": "x"}
        response = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/reject/"), body, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        job = Job.objects.get(pk=self.job.pk)
        self.assertEqual((job.status, job.rework_round), (JobStatus.REWORK, 1))
        self.assertEqual(ReviewError.objects.filter(job=job, stage="qc2").count(), 1)
        # Sửa xong, qua QC1 lại → vào Chờ QC2 → lượt QC2 mới
        job.status = JobStatus.PENDING_QC2
        job.save()
        second = ensure_qc2_sample(job)
        self.assertNotEqual(second.pk, self.sample.pk)
        self.assertEqual(second.rework_round, 1)

    def test_reject_without_errors_is_refused(self):
        response = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/reject/"), {"errors": []}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_exceeding_max_rework_rounds_escalates(self):
        Job.objects.filter(pk=self.job.pk).update(rework_round=2)
        body = {"errors": [{"category": self.f.category.id}]}
        self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/reject/"), body, format="json")
        self.assertTrue(Job.objects.get(pk=self.job.pk).is_escalated)

    def test_four_eyes_blocks_auditing_own_annotation(self):
        Job.objects.filter(pk=self.job.pk).update(annotator=self.f.pm)
        response = self.pm.post(self.f.url(f"audit-samples/{self.sample.id}/pass/"), {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_qc2_cannot_review_sample_assigned_to_someone_else(self):
        other = make_user("qc2_other", Role.QC2, project=self.f.project)
        AuditSample.objects.filter(pk=self.sample.pk).update(auditor=other)
        response = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/pass/"), {}, format="json")
        self.assertIn(response.status_code, (403, 404))

    def test_qc2_only_can_read_error_categories_but_not_edit(self):
        self.assertEqual(self.qc2.get(self.f.url("error-categories/")).status_code, 200)
        response = self.qc2.post(self.f.url("error-categories/"), {"name": "X"}, format="json")
        self.assertEqual(response.status_code, 403)


class DeletionRulesTests(TestCase):
    """Loại lỗi đang được dùng không xoá riêng được, nhưng xoá cả organization thì được."""

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
    """Mọi tài khoản QC2 có Tổng quan (số liệu của mình). Quy tắc QC2 (tỉ lệ frame) chỉ PM xem."""

    def setUp(self):
        self.f = ProjectFixture()
        self.jobs = [self.f.job(frame_count=10) for _ in range(3)]
        self.samples = [ensure_qc2_sample(job) for job in self.jobs]
        self.pm = self.f.client(self.f.pm)
        self.qc2 = self.f.client(self.f.qc2)

    def test_qc2_only_sees_own_dashboard_but_no_strategy(self):
        summary = self.qc2.get(self.f.url("qc2-summary/"))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["scope"], "mine")
        self.assertEqual(self.qc2.get(self.f.url("audit-strategy/")).status_code, 403)

    def test_pm_strategy_with_history_and_stats(self):
        self.pm.patch(self.f.url("settings/"), {"sampling_rate": 30}, format="json")
        data = self.pm.get(self.f.url("audit-strategy/")).data
        self.assertTrue(data["can_edit"])
        self.assertEqual(data["sampling_rate"], 30)
        self.assertEqual(data["history"][0]["after"], {"sampling_rate": 30})
        self.assertEqual(data["stats"]["pending"], 3)

    def test_pm_summary_has_kpi_comparison_and_trend(self):
        self.qc2.post(self.f.url(f"audit-samples/{self.samples[0].id}/pass/"), {}, format="json")
        data = self.pm.get(self.f.url("qc2-summary/?period=week")).data
        self.assertEqual(data["kpi"]["current"]["passed"], 1)
        self.assertEqual(data["kpi"]["previous"]["audited"], 0)
        self.assertEqual(len(data["trend"]), 7)
        self.assertEqual(data["trend"][-1]["audited"], 1)
        self.assertEqual(data["audit_speed"]["status"], "pending_definition")
