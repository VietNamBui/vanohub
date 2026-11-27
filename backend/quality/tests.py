from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from django.test import TestCase
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

    def test_qc1_pool_claim_and_pass_auto_creates_qc2_sample(self):
        qc1_pool = make_user("qc1_pool_user", Role.QC1, project=self.f.project)
        pool_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2)
        Job.objects.filter(pk=pool_job.pk).update(qc1_reviewer=None)

        client = self.f.client(qc1_pool)
        listed = client.get(self.f.url("qc1/jobs/?scope=pool")).data
        self.assertEqual([r["id"] for r in listed["results"]], [pool_job.id])

        passed = client.post(self.f.url(f"qc1/jobs/{pool_job.id}/pass/"), {"comment": "ok"}, format="json")
        self.assertEqual(passed.status_code, 200, passed.data)
        self.assertEqual(passed.data["status"], JobStatus.PENDING_QC2)
        self.assertEqual(passed.data["qc1_reviewer"]["id"], qc1_pool.id)
        sample = AuditSample.objects.get(job=pool_job, result=AuditSample.Result.PENDING)
        self.assertTrue(sample.frames)
        self.assertEqual(sample.auditor_id, self.f.qc2.id)

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

        # QC1 pass tự tạo lượt QC2 theo frame (quality/qc2.py)
        sample = AuditSample.objects.get(job=job, result=AuditSample.Result.PENDING)
        self.assertEqual(qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 200)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.APPROVED)

    def test_qc1_reject_rolls_back_atomically_on_failure(self):
        from unittest.mock import patch

        from projects.models import ActivityLog

        body = {"errors": [{"category": self.f.category.id, "description": "loi"}]}
        with (
            patch.object(ActivityLog, "record", side_effect=RuntimeError("db failure")),
            self.assertRaises(RuntimeError),
        ):
            self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/reject/"), body, format="json")

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.PENDING_QC1)
        self.assertEqual(self.job.rework_round, 0)
        self.assertEqual(ReviewError.objects.filter(job=self.job).count(), 0)


class QualityBugFixTests(TestCase):
    """Kiểm thử hồi quy các lỗi P0/P1 ở quality (khoá/escalation, 4-eyes lịch sử, timezone, param validation)."""

    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.qc1 = self.f.client(self.f.qc1)
        self.qc2 = self.f.client(self.f.qc2)
        self.ann1 = self.f.client(self.f.ann1)

    def test_qc2_actions_blocked_on_locked_job_batch_dataset_escalated_and_completed_audit(self):
        from projects.models import DataStatus

        job = self.f.job(status=JobStatus.PENDING_QC2, frame_count=10)
        sample = ensure_qc2_sample(job)
        reject_body = {"errors": [{"category": self.f.category.id, "description": "loi"}]}
        other_qc2 = make_user("qc2_alt", Role.QC2, project=self.f.project)

        # 1. Locked job
        Job.objects.filter(pk=job.pk).update(is_locked=True)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 400)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/reject/"), reject_body, format="json").status_code, 400)
        self.assertEqual(self.pm.post(self.f.url(f"audit-samples/{sample.id}/assign/"), {"auditor": other_qc2.id}, format="json").status_code, 400)
        Job.objects.filter(pk=job.pk).update(is_locked=False)

        # 2. Locked batch
        self.f.batch.status = DataStatus.LOCKED
        self.f.batch.save(update_fields=["status"])
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 400)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/reject/"), reject_body, format="json").status_code, 400)
        self.assertEqual(self.pm.post(self.f.url(f"audit-samples/{sample.id}/assign/"), {"auditor": other_qc2.id}, format="json").status_code, 400)
        self.f.batch.status = DataStatus.ACTIVE
        self.f.batch.save(update_fields=["status"])

        # 3. Locked dataset
        self.f.dataset.status = DataStatus.LOCKED
        self.f.dataset.save(update_fields=["status"])
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 400)
        self.f.dataset.status = DataStatus.ACTIVE
        self.f.dataset.save(update_fields=["status"])

        # 4. Escalated job
        Job.objects.filter(pk=job.pk).update(is_escalated=True)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 400)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/reject/"), reject_body, format="json").status_code, 400)
        self.assertEqual(self.pm.post(self.f.url(f"audit-samples/{sample.id}/assign/"), {"auditor": other_qc2.id}, format="json").status_code, 400)
        Job.objects.filter(pk=job.pk).update(is_escalated=False)

        # 5. Completed audit
        Audit.objects.filter(pk=sample.audit_id).update(status=Audit.Status.COMPLETED)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 400)
        self.assertEqual(self.qc2.post(self.f.url(f"audit-samples/{sample.id}/reject/"), reject_body, format="json").status_code, 400)
        self.assertEqual(self.pm.post(self.f.url(f"audit-samples/{sample.id}/assign/"), {"auditor": other_qc2.id}, format="json").status_code, 400)

    def test_qc2_reject_creates_pinned_notification_in_vn_tz_sets_scope_and_total_rework_rounds(self):
        from datetime import UTC, datetime

        from jobs.models import ReworkScope
        from projects.models import UserNotification

        # 2026-11-26 18:30 UTC == 2026-11-27 01:30 Asia/Ho_Chi_Minh
        deadline_utc = datetime(2026, 11, 26, 18, 30, tzinfo=UTC)
        job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, deadline=deadline_utc)
        sample = ensure_qc2_sample(job)

        # Gửi kèm ?result=pending trên URL POST vẫn trả 200 (không 500 DoesNotExist)
        res = self.qc2.post(
            self.f.url(f"audit-samples/{sample.id}/reject/?result=pending"),
            {
                "errors": [{"category": self.f.category.id, "location": "frame 1"}],
                "rework_scope": ReworkScope.FULL,
            },
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["result"], AuditSample.Result.REJECT)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.REWORK)
        self.assertEqual(job.rework_round, 1)
        self.assertEqual(job.total_rework_rounds, 1)
        self.assertEqual(job.rework_scope, ReworkScope.FULL)

        notif = UserNotification.objects.get(
            recipient=self.f.ann1,
            job=job,
            category=UserNotification.Category.REWORK,
        )
        self.assertTrue(notif.is_pinned_pending)
        self.assertIn("27/11 01:30", notif.body)

    def test_qc2_pass_with_pending_query_param_returns_200(self):
        job = self.f.job(status=JobStatus.PENDING_QC2)
        sample = ensure_qc2_sample(job)
        res = self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/?result=pending"), {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["result"], AuditSample.Result.PASS)

    def test_historical_and_cross_stage_four_eyes_blocks_qc1_and_qc2_after_reassignment(self):
        from .qc2 import four_eyes_conflicts, get_stage_history, pick_auditor

        # User có cả ANNOTATOR, QC1, QC2
        multi = make_user("multi_stage", Role.ANNOTATOR, Role.QC1, Role.QC2, project=self.f.project)
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=multi)
        Job.objects.filter(pk=job.pk).update(qc1_reviewer=None)

        # multi annotate + submit job
        multi_client = self.f.client(multi)
        self.assertEqual(multi_client.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(multi_client.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json").status_code, 200)

        # PM đổi annotator sang ann2 → multi không còn là job.annotator hiện tại nhưng vẫn có lịch sử annotate
        Job.objects.filter(pk=job.pk).update(annotator=self.f.ann2)
        job.refresh_from_db()

        ann_ids, qc1_ids, qc2_ids = get_stage_history(job)
        self.assertIn(multi.id, ann_ids)
        self.assertIn(multi.id, four_eyes_conflicts(job))

        # multi bị chặn ở QC1 (ẩn khỏi pool và 403 khi gọi thẳng)
        self.assertEqual(multi_client.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 0)
        self.assertEqual(multi_client.post(self.f.url(f"qc1/jobs/{job.id}/start/"), {}, format="json").status_code, 403)
        self.assertEqual(multi_client.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 403)

        # qc1 duyệt job → vào PENDING_QC2; multi cũng bị chặn ở QC2 (assign → 400, pass → 403)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 200)
        sample = AuditSample.objects.get(job=job, result=AuditSample.Result.PENDING)
        self.assertNotEqual(sample.auditor_id, multi.id)
        self.assertEqual(
            self.pm.post(self.f.url(f"audit-samples/{sample.id}/assign/"), {"auditor": multi.id}, format="json").status_code,
            400,
        )
        # Kể cả nếu sample chưa có auditor, multi vẫn bị chặn 403 luật bốn mắt
        AuditSample.objects.filter(pk=sample.pk).update(auditor=None)
        self.assertEqual(multi_client.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 403)

        # Ngược lại: người đã audit QC2 (self.f.qc2 có thêm role QC1) không được QC1 lại job đó sau rework
        from accounts.models import RoleAssignment

        RoleAssignment.objects.create(user=self.f.qc2, role=Role.QC1, project=self.f.project)
        AuditSample.objects.filter(pk=sample.pk).update(auditor=self.f.qc2)
        self.assertEqual(
            self.qc2.post(
                self.f.url(f"audit-samples/{sample.id}/reject/"),
                {"errors": [{"category": self.f.category.id, "description": "sai"}]},
                format="json",
            ).status_code,
            200,
        )
        Job.objects.filter(pk=job.pk).update(status=JobStatus.PENDING_QC1, qc1_reviewer=None)
        self.assertEqual(self.qc2.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 0)
        self.assertEqual(self.qc2.post(self.f.url(f"qc1/jobs/{job.id}/start/"), {}, format="json").status_code, 403)

        # pick_auditor bỏ qua user không hoạt động (is_active=False)
        self.f.qc2.is_active = False
        self.f.qc2.save(update_fields=["is_active"])
        fresh_job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1)
        self.assertEqual(pick_auditor(fresh_job), multi)

    def test_ensure_qc2_sample_idempotent_and_handles_concurrent_integrity_error(self):
        from unittest.mock import patch

        from django.db import IntegrityError

        job = self.f.job(status=JobStatus.PENDING_QC2, frame_count=10)
        first = ensure_qc2_sample(job)
        second = ensure_qc2_sample(job)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Audit.objects.filter(batch=self.f.batch, status=Audit.Status.IN_PROGRESS).count(), 1)
        self.assertEqual(AuditSample.objects.filter(job=job, result=AuditSample.Result.PENDING).count(), 1)

        # Giả lập race condition khi tạo AuditSample: IntegrityError → lấy lại sample đang chờ
        real_filter = AuditSample.objects.filter
        call_count = {"n": 0}

        def fake_filter(*args, **kwargs):
            qs = real_filter(*args, **kwargs)
            if kwargs.get("result") == AuditSample.Result.PENDING and call_count["n"] == 0:
                call_count["n"] += 1
                return AuditSample.objects.none()
            return qs

        with (
            patch.object(AuditSample.objects, "filter", side_effect=fake_filter),
            patch.object(AuditSample.objects, "create", side_effect=IntegrityError("duplicate pending")),
        ):
            recovered = ensure_qc2_sample(job)
        self.assertEqual(recovered.pk, first.pk)

    def test_qc1_pool_excludes_locked_batch_and_dataset_and_reject_formats_vn_deadline(self):
        from datetime import UTC, datetime

        from projects.models import DataStatus, UserNotification

        pool_job = self.f.job(
            status=JobStatus.PENDING_QC1,
            annotator=self.f.ann1,
            deadline=datetime(2026, 11, 26, 19, 15, tzinfo=UTC),  # 27/11 02:15 VN
        )
        Job.objects.filter(pk=pool_job.pk).update(qc1_reviewer=None)

        # Khoá batch → ẩn khỏi pool QC1
        self.f.batch.status = DataStatus.LOCKED
        self.f.batch.save(update_fields=["status"])
        self.assertEqual(self.qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 0)
        self.f.batch.status = DataStatus.ACTIVE
        self.f.batch.save(update_fields=["status"])

        # Khoá dataset → ẩn khỏi pool QC1
        self.f.dataset.status = DataStatus.LOCKED
        self.f.dataset.save(update_fields=["status"])
        self.assertEqual(self.qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 0)
        self.f.dataset.status = DataStatus.ACTIVE
        self.f.dataset.save(update_fields=["status"])

        # Mở lại → hiện trong pool và reject tăng total_rework_rounds + format deadline VN
        self.assertEqual(self.qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 1)
        res = self.qc1.post(
            self.f.url(f"qc1/jobs/{pool_job.id}/reject/"),
            {"errors": [{"category": self.f.category.id, "description": "thieu"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        pool_job.refresh_from_db()
        self.assertEqual(pool_job.total_rework_rounds, 1)
        notif = UserNotification.objects.get(recipient=self.f.ann1, job=pool_job, category=UserNotification.Category.REWORK)
        self.assertIn("27/11 02:15", notif.body)

    def test_invalid_int_params_return_400_and_large_search_does_not_500(self):
        job = self.f.job(status=JobStatus.PENDING_QC2)
        sample = ensure_qc2_sample(job)

        self.assertEqual(self.pm.get(self.f.url("audits/?batch=abc")).status_code, 400)
        self.assertEqual(self.pm.get(self.f.url("audits/?batch=9999999999999")).status_code, 400)
        self.assertEqual(self.pm.get(self.f.url("audit-samples/?audit=abc")).status_code, 400)
        self.assertEqual(
            self.pm.post(self.f.url(f"audit-samples/{sample.id}/assign/"), {"auditor": "not_int"}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.pm.post(self.f.url(f"audit-samples/{sample.id}/assign/"), {"auditor": 9999999999999}, format="json").status_code,
            400,
        )
        self.assertEqual(self.qc1.get(self.f.url("qc1/jobs/?batch=abc")).status_code, 400)
        self.assertEqual(self.qc1.get(self.f.url("qc1/jobs/?annotator=abc")).status_code, 400)
        # Số vượt PG_INT32_MAX trong ô tìm kiếm không gây lỗi 500
        search_res = self.qc1.get(self.f.url("qc1/jobs/?search=999999999999999999"))
        self.assertEqual(search_res.status_code, 200)
