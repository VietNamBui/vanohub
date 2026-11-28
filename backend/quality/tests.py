from datetime import UTC, datetime
from unittest.mock import patch

from django.db import IntegrityError, connection
from django.db.models import RestrictedError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import Role, RoleAssignment
from accounts.testing import ProjectFixture, make_user
from jobs.models import FirstQc1Result, Job, JobStatus, ReworkScope
from projects.models import ActivityLog, Batch, DataStatus, EscalationPolicy, UserNotification
from teams.models import Team, TeamMember

from .models import Audit, AuditSample, ErrorCategory, ErrorVerdict, ReviewError, ReviewStage
from .qc2 import ensure_qc2_sample, four_eyes_conflicts, get_stage_history, pick_auditor, pick_frames
from .views import qc1_pass, qc1_reject


class FrameSamplingTests(TestCase):
    """QC2 kiểm MỌI job qua QC1, mỗi job sampling_rate % số frame (làm tròn lên, ít nhất 1)."""

    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.f.project.sampling_rate = 20
        self.f.project.save()

    def test_frame_count_rounds_up_with_minimum_one(self) -> None:
        job = self.f.job(frame_count=10, cvat_start_frame=100)
        frames = pick_frames(job, 20)
        self.assertEqual(len(frames), 2)
        self.assertTrue(all(100 <= f < 110 for f in frames))
        self.assertEqual(len(pick_frames(self.f.job(frame_count=11), 20)), 3)
        self.assertEqual(len(pick_frames(self.f.job(frame_count=1), 20)), 1)

    def test_same_job_and_round_gives_same_frames(self) -> None:
        job = self.f.job(frame_count=50)
        self.assertEqual(pick_frames(job, 20), pick_frames(job, 20))

    def test_every_pending_qc2_job_gets_one_open_sample_in_task_audit(self) -> None:
        jobs = [self.f.job(frame_count=10) for _ in range(3)]
        for job in jobs:
            ensure_qc2_sample(job)
            ensure_qc2_sample(job)
        self.assertEqual(AuditSample.objects.count(), 3)
        self.assertEqual(Audit.objects.filter(batch=self.f.batch).count(), 1)
        first = AuditSample.objects.first()
        assert first is not None
        self.assertEqual(first.auditor, self.f.qc2)

    def test_jobs_not_waiting_for_qc2_get_no_sample(self) -> None:
        self.assertIsNone(ensure_qc2_sample(self.f.job(status=JobStatus.PENDING_QC1)))
        self.assertIsNone(ensure_qc2_sample(self.f.job(status=JobStatus.QC1_PASSED)))

    def test_auto_assign_respects_four_eyes(self) -> None:
        job = self.f.job(annotator=self.f.qc2, frame_count=5)
        sample = ensure_qc2_sample(job)
        assert sample is not None
        self.assertIsNone(sample.auditor)

    def test_pick_frames_supports_frame_step_deleted_included_and_stop_frame(self) -> None:
        from cvat_integration.schemas import CvatJobMetaPayload

        job = self.f.job(frame_count=5, cvat_start_frame=10)
        # step=2 trên [10..18] trừ frame 12 → hợp lệ: [10, 14, 16, 18] (4 frame, rate 50% → 2 frame)
        sampled = pick_frames(job, 50, frame_step=2, deleted_frames=[12], stop_frame=18)
        self.assertEqual(len(sampled), 2)
        self.assertTrue(all(f in {10, 14, 16, 18} for f in sampled))
        self.assertEqual(sampled, pick_frames(job, 50, frame_step=2, deleted_frames=[12], stop_frame=18))

        # Hỗ trợ truyền CvatJobMetaPayload và included_frames
        meta = CvatJobMetaPayload.model_validate(
            {
                "size": 5,
                "start_frame": 10,
                "stop_frame": 18,
                "frame_filter": "step=2",
                "deleted_frames": [14],
                "included_frames": [10, 14, 16, 20],
            }
        )
        sampled_meta = pick_frames(job, 50, meta=meta)
        self.assertEqual(len(sampled_meta), 1)
        self.assertIn(sampled_meta[0], {10, 16})

        # Tất cả frame bị xoá → trả [] an toàn
        self.assertEqual(pick_frames(job, 20, included_frames=[14], deleted_frames=[14]), [])


class Qc2ReviewTests(TestCase):
    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.qc2 = self.f.client(self.f.qc2)
        self.job = self.f.job(frame_count=10)
        sample = ensure_qc2_sample(self.job)
        assert sample is not None
        self.sample = sample

    def test_audits_are_read_only(self) -> None:
        response = self.pm.post(self.f.url("audits/"), {"batch": self.f.batch.id}, format="json")
        self.assertEqual(response.status_code, 405)
        listed = self.pm.get(self.f.url("audits/")).data
        self.assertEqual((len(listed), listed[0]["sample_count"]), (1, 1))

    def test_qc2_passes_job_and_leaves_checked_object_count_none(self) -> None:
        listed = self.qc2.get(self.f.url("audit-samples/?result=pending")).data
        self.assertEqual([s["id"] for s in listed], [self.sample.id])
        self.assertEqual(len(listed[0]["frames"]), 5)  # 50% của 10 frame
        self.assertEqual(listed[0]["job_name"], self.job.name)
        self.assertEqual(listed[0]["batch_name"], self.f.batch.name)
        self.assertEqual(listed[0]["dataset_name"], self.f.dataset.name)
        response = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/pass/"), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.job.refresh_from_db()
        self.sample.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.APPROVED)
        # Không ghi khống checked_object_count=0 trên job chưa chốt mẫu số theo frame
        self.assertIsNone(self.sample.checked_object_count)

    def test_reject_sends_job_to_rework_and_next_round_gets_new_sample(self) -> None:
        body = {
            "errors": [
                {
                    "category": self.f.category.id,
                    "frame_number": 3,
                    "cvat_object_id": 7,
                    "verdict": ErrorVerdict.FAIL,
                    "location": "frame 3",
                }
            ],
            "comment": "x",
        }
        response = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/reject/"), body, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        job = Job.objects.get(pk=self.job.pk)
        self.assertEqual((job.status, job.rework_round, job.total_rework_rounds), (JobStatus.REWORK, 1, 1))
        err = ReviewError.objects.get(job=job, stage=ReviewStage.QC2)
        self.assertEqual((err.frame_number, err.cvat_object_id, err.verdict, err.is_missing_object), (3, 7, "fail", False))
        # Sửa xong, qua QC1 lại → vào Chờ QC2 → lượt QC2 mới
        job.status = JobStatus.PENDING_QC2
        job.save(update_fields=["status"])
        second = ensure_qc2_sample(job)
        assert second is not None
        self.assertNotEqual(second.pk, self.sample.pk)
        self.assertEqual(second.rework_round, 1)

    def test_structured_review_error_validation(self) -> None:
        # 1. is_missing_object=True kèm cvat_object_id bị từ chối (400)
        res_obj = self.qc2.post(
            self.f.url(f"audit-samples/{self.sample.id}/reject/"),
            {
                "errors": [
                    {
                        "category": self.f.category.id,
                        "frame_number": 2,
                        "cvat_object_id": 9,
                        "is_missing_object": True,
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(res_obj.status_code, 400)

        # 2. is_missing_object=True kèm verdict="edge" bị từ chối (400)
        res_edge = self.qc2.post(
            self.f.url(f"audit-samples/{self.sample.id}/reject/"),
            {
                "errors": [
                    {
                        "category": self.f.category.id,
                        "frame_number": 2,
                        "is_missing_object": True,
                        "verdict": ErrorVerdict.EDGE,
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(res_edge.status_code, 400)

        # 3. cvat_object_id=0 bị từ chối (phải >= 1)
        res_zero = self.qc2.post(
            self.f.url(f"audit-samples/{self.sample.id}/reject/"),
            {"errors": [{"category": self.f.category.id, "cvat_object_id": 0}]},
            format="json",
        )
        self.assertEqual(res_zero.status_code, 400)

        # 4. Hợp lệ: is_missing_object=True, cvat_object_id=None, verdict="fail"
        res_ok = self.qc2.post(
            self.f.url(f"audit-samples/{self.sample.id}/reject/"),
            {
                "errors": [
                    {
                        "category": self.f.category.id,
                        "frame_number": 4,
                        "is_missing_object": True,
                        "verdict": ErrorVerdict.FAIL,
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(res_ok.status_code, 200, res_ok.data)
        err = ReviewError.objects.get(job=self.job, stage=ReviewStage.QC2)
        self.assertTrue(err.is_missing_object)
        self.assertIsNone(err.cvat_object_id)
        self.assertEqual(err.verdict, ErrorVerdict.FAIL)

    def test_reject_without_errors_is_refused(self) -> None:
        response = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/reject/"), {"errors": []}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_exceeding_max_rework_rounds_escalates_and_respects_warn_only(self) -> None:
        Job.objects.filter(pk=self.job.pk).update(rework_round=2, total_rework_rounds=2)
        self.f.project.escalation_policy = EscalationPolicy.WARN_ONLY
        self.f.project.save(update_fields=["escalation_policy"])

        body = {"errors": [{"category": self.f.category.id}]}
        res = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/reject/"), body, format="json")
        self.assertEqual(res.status_code, 200, res.data)

        self.job.refresh_from_db()
        self.assertTrue(self.job.is_escalated)
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.f.pm, job=self.job, category=UserNotification.Category.ESCALATED
            ).exists()
        )
        # Với WARN_ONLY, annotator vẫn được tiếp tục sửa dù is_escalated=True
        ann_client = self.f.client(self.job.annotator)
        self.assertEqual(
            ann_client.post(self.f.url(f"annotator/jobs/{self.job.id}/start/"), {}, format="json").status_code,
            200,
        )

    def test_four_eyes_blocks_auditing_own_annotation(self) -> None:
        Job.objects.filter(pk=self.job.pk).update(annotator=self.f.pm)
        response = self.pm.post(self.f.url(f"audit-samples/{self.sample.id}/pass/"), {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_qc2_cannot_review_sample_assigned_to_someone_else(self) -> None:
        other = make_user("qc2_other", Role.QC2, project=self.f.project)
        AuditSample.objects.filter(pk=self.sample.pk).update(auditor=other)
        response = self.qc2.post(self.f.url(f"audit-samples/{self.sample.id}/pass/"), {}, format="json")
        self.assertIn(response.status_code, (403, 404))

    def test_qc2_only_can_read_error_categories_but_not_edit(self) -> None:
        self.assertEqual(self.qc2.get(self.f.url("error-categories/")).status_code, 200)
        response = self.qc2.post(self.f.url("error-categories/"), {"name": "X"}, format="json")
        self.assertEqual(response.status_code, 403)


class DeletionRulesTests(TestCase):
    """Loại lỗi đang được dùng không xoá riêng được, nhưng xoá cả organization thì được."""

    def setUp(self) -> None:
        self.f = ProjectFixture()
        job = self.f.job()
        ReviewError.objects.create(job=job, stage=ReviewStage.QC2, rework_round=0, category=self.f.category, severity="minor")

    def test_category_in_use_cannot_be_deleted(self) -> None:
        with self.assertRaises(RestrictedError):
            self.f.category.delete()

    def test_project_with_review_errors_can_be_deleted(self) -> None:
        self.f.project.delete()
        self.assertFalse(ReviewError.objects.exists())


class Qc2ScreensTests(TestCase):
    """Mọi tài khoản QC2 có Tổng quan (số liệu của mình). Quy tắc QC2 (tỉ lệ frame) chỉ PM xem."""

    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.jobs = [self.f.job(frame_count=10) for _ in range(3)]
        self.samples = [ensure_qc2_sample(job) for job in self.jobs]
        self.pm = self.f.client(self.f.pm)
        self.qc2 = self.f.client(self.f.qc2)

    def test_qc2_only_sees_own_dashboard_but_no_strategy(self) -> None:
        summary = self.qc2.get(self.f.url("qc2-summary/"))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["scope"], "mine")
        self.assertEqual(self.qc2.get(self.f.url("audit-strategy/")).status_code, 403)

    def test_pm_strategy_with_history_and_stats(self) -> None:
        self.pm.patch(self.f.url("settings/"), {"sampling_rate": 30}, format="json")
        data = self.pm.get(self.f.url("audit-strategy/")).data
        self.assertTrue(data["can_edit"])
        self.assertEqual(data["sampling_rate"], 30)
        self.assertEqual(data["history"][0]["after"], {"sampling_rate": 30})
        self.assertEqual(data["stats"]["pending"], 3)

    def test_pm_summary_has_kpi_comparison_trend_and_pending_definition_metrics(self) -> None:
        sample0 = self.samples[0]
        assert sample0 is not None
        self.qc2.post(self.f.url(f"audit-samples/{sample0.id}/pass/"), {}, format="json")
        data = self.pm.get(self.f.url("qc2-summary/?period=week")).data
        self.assertEqual(data["kpi"]["current"]["passed"], 1)
        self.assertEqual(data["kpi"]["previous"]["audited"], 0)
        self.assertEqual(len(data["trend"]), 7)
        self.assertEqual(data["trend"][-1]["audited"], 1)
        self.assertEqual(data["audit_speed"]["status"], "pending_definition")
        self.assertEqual(data["error_percent_in_job"]["status"], "pending_definition")
        self.assertIsNone(data["error_percent_in_job"]["value"])
        self.assertEqual(data["quality_cl"]["status"], "pending_definition")
        self.assertIsNone(data["quality_cl"]["value"])
        self.assertEqual(data["defect_rate_by_severity"]["status"], "pending_definition")
        self.assertIsNone(data["defect_rate_by_severity"]["value"])


class Qc1WorkflowTests(TestCase):
    """Kiểm thử Level 1 QC: phân quyền, Hybrid A2 anti-deadlock, luật bốn mắt, pool team, atomic rollback."""

    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)
        self.pm = self.f.client(self.f.pm)
        self.qc1 = self.f.client(self.f.qc1)
        self.ann1 = self.f.client(self.f.ann1)

    def test_annotator_and_qc2_only_cannot_use_qc1_api(self) -> None:
        self.assertEqual(self.ann1.get(self.f.url("qc1/jobs/")).status_code, 403)
        self.assertEqual(self.f.client(self.f.qc2).get(self.f.url("qc1/jobs/")).status_code, 403)

    def test_hybrid_a2_pre_confirm_transitions_to_qc1_passed_without_sample(self) -> None:
        started = self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/start/"), {}, format="json")
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["status"], JobStatus.QC1_REVIEWING)

        passed = self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/pass/"), {"comment": "dat chuan"}, format="json")
        self.assertEqual(passed.status_code, 200, passed.data)
        self.assertEqual(passed.data["status"], JobStatus.QC1_PASSED)
        self.assertEqual(passed.data["first_qc1_result"], FirstQc1Result.PASS)
        self.assertEqual([e["action"] for e in passed.data["timeline"]], ["qc1.start", "qc1.pass"])
        # Chưa confirm-qc2 → KHÔNG tự tạo AuditSample trước
        self.assertFalse(AuditSample.objects.filter(job=self.job).exists())
        # Batch 100% QC1_PASSED → gửi thông báo cho PM
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.f.pm, category=UserNotification.Category.REVIEW_NEEDED
            ).exists()
        )

    def test_hybrid_a2_post_confirm_rework_transitions_directly_to_pending_qc2_with_sample(self) -> None:
        self.f.batch.qc2_confirmed_by = self.f.pm
        self.f.batch.qc2_confirmed_at = timezone.now()
        self.f.batch.save(update_fields=["qc2_confirmed_by", "qc2_confirmed_at"])

        qc1_pool = make_user("qc1_pool_user", Role.QC1, project=self.f.project)
        pool_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann2, frame_count=10)
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

    def test_qc1_pass_does_not_flip_cvat_rejected_job_to_first_qc1_pass(self) -> None:
        cvat_rw = self.f.job(
            status=JobStatus.PENDING_QC1,
            annotator=self.f.ann2,
            rework_round=1,
            total_rework_rounds=1,
            first_qc1_result="",
        )
        res = self.qc1.post(self.f.url(f"qc1/jobs/{cvat_rw.id}/pass/"), {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        cvat_rw.refresh_from_db()
        self.assertEqual(cvat_rw.first_qc1_result, "")

    def test_qc1_reject_records_structured_errors_increments_rework_and_escalates(self) -> None:
        qc2_only_cat = ErrorCategory.objects.create(
            project=self.f.project, name="Chi QC2", applies_to=ErrorCategory.AppliesTo.QC2
        )
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

        body = {
            "errors": [
                {
                    "category": self.f.category.id,
                    "frame_number": 5,
                    "cvat_object_id": 12,
                    "verdict": ErrorVerdict.EDGE,
                    "location": "frame 5",
                    "description": "lech box",
                }
            ],
            "comment": "sua lai",
        }
        r1 = self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/reject/"), body, format="json")
        self.assertEqual(r1.status_code, 200, r1.data)
        self.assertEqual(r1.data["status"], JobStatus.REWORK)
        self.assertEqual(r1.data["rework_round"], 1)
        self.assertEqual(r1.data["first_qc1_result"], FirstQc1Result.REJECT)
        self.assertFalse(r1.data["is_escalated"])
        err = ReviewError.objects.get(job=self.job, stage=ReviewStage.QC1, rework_round=0)
        self.assertEqual((err.frame_number, err.cvat_object_id, err.verdict), (5, 12, ErrorVerdict.EDGE))

        # Vòng 2 -> 3 (vượt max_rework_rounds=2 → tự bật is_escalated)
        Job.objects.filter(pk=self.job.pk).update(status=JobStatus.QC1_REVIEWING, rework_round=2, total_rework_rounds=2)
        r2 = self.qc1.post(self.f.url(f"qc1/jobs/{self.job.id}/reject/"), body, format="json")
        self.assertEqual(r2.status_code, 200, r2.data)
        self.assertEqual(r2.data["rework_round"], 3)
        self.assertTrue(r2.data["is_escalated"])
        self.assertEqual(ReviewError.objects.filter(job=self.job, stage=ReviewStage.QC1).count(), 2)

    def test_four_eyes_blocks_qc1_on_own_annotated_job(self) -> None:
        dual = make_user("dual_ann_qc1", Role.ANNOTATOR, Role.QC1, project=self.f.project)
        own_job = self.f.job(status=JobStatus.PENDING_QC1, annotator=dual)
        Job.objects.filter(pk=own_job.pk).update(qc1_reviewer=None)

        client = self.f.client(dual)
        self.assertEqual(client.get(self.f.url("qc1/jobs/?scope=all")).data["count"], 0)
        self.assertEqual(client.post(self.f.url(f"qc1/jobs/{own_job.id}/start/"), {}, format="json").status_code, 403)
        self.assertEqual(client.post(self.f.url(f"qc1/jobs/{own_job.id}/pass/"), {}, format="json").status_code, 403)

    def test_qc1_cannot_review_job_assigned_to_another_qc1(self) -> None:
        other_qc1 = make_user("qc1_other", Role.QC1, project=self.f.project)
        client = self.f.client(other_qc1)
        self.assertEqual(client.get(self.f.url(f"qc1/jobs/{self.job.id}/")).status_code, 404)
        self.assertEqual(client.post(self.f.url(f"qc1/jobs/{self.job.id}/pass/"), {}, format="json").status_code, 403)

    def test_end_to_end_hybrid_a2_pipeline_including_post_qc2_rework(self) -> None:
        """Toàn luồng Hybrid A2:
        Anno -> QC1 reject -> Rework -> QC1 pass (QC1_PASSED) -> PM confirm-qc2 -> QC2 reject
        -> Rework -> QC1 pass (thẳng PENDING_QC2 + auto sample) -> QC2 pass (APPROVED).
        """
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, frame_count=10)
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

        detail = self.ann1.get(self.f.url(f"annotator/jobs/{job.id}/")).data
        self.assertEqual(detail["status"], JobStatus.REWORK)
        self.assertEqual(len(detail["errors"]), 1)

        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json").status_code, 200)
        p1 = self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json")
        self.assertEqual(p1.status_code, 200)
        self.assertEqual(p1.data["status"], JobStatus.QC1_PASSED)

        # Đưa job setUp sang QC1_PASSED để batch đạt 100%, rồi PM xác nhận chuyển QC2
        Job.objects.filter(pk=self.job.pk).update(status=JobStatus.QC1_PASSED)
        confirm = self.pm.post(self.f.url(f"batches/{self.f.batch.id}/confirm-qc2/"), {}, format="json")
        self.assertEqual(confirm.status_code, 200, confirm.data)

        sample1 = ensure_qc2_sample(Job.objects.get(pk=job.pk))
        assert sample1 is not None
        # QC2 trả về rework hậu confirm-qc2
        self.assertEqual(
            qc2.post(
                self.f.url(f"audit-samples/{sample1.id}/reject/"),
                {"errors": [{"category": self.f.category.id, "frame_number": 1}]},
                format="json",
            ).status_code,
            200,
        )
        # Annotator sửa xong, QC1 pass → chuyển THẲNG PENDING_QC2 và tự tạo sample2 (anti-deadlock!)
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json").status_code, 200)
        p2 = self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json")
        self.assertEqual(p2.status_code, 200, p2.data)
        self.assertEqual(p2.data["status"], JobStatus.PENDING_QC2)

        sample2 = AuditSample.objects.get(job=job, result=AuditSample.Result.PENDING)
        self.assertNotEqual(sample2.pk, sample1.pk)
        self.assertEqual(qc2.post(self.f.url(f"audit-samples/{sample2.id}/pass/"), {}, format="json").status_code, 200)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.APPROVED)

    def test_qc1_pool_strictly_scoped_to_own_team(self) -> None:
        team_a = Team.objects.create(project=self.f.project, name="Team A")
        team_b = Team.objects.create(project=self.f.project, name="Team B")
        TeamMember.objects.create(team=team_a, user=self.f.qc1)
        batch_b = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="Batch B", team=team_b)
        foreign_job = Job.objects.create(
            project=self.f.project,
            dataset=self.f.dataset,
            batch=batch_b,
            name="FOREIGN-1",
            status=JobStatus.PENDING_QC1,
            annotator=self.f.ann2,
        )
        pool_ids = [r["id"] for r in self.qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["results"]]
        self.assertNotIn(foreign_job.id, pool_ids)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{foreign_job.id}/start/"), {}, format="json").status_code, 403)

    def test_qc1_reject_rolls_back_atomically_on_failure(self) -> None:
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

    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.qc1 = self.f.client(self.f.qc1)
        self.qc2 = self.f.client(self.f.qc2)
        self.ann1 = self.f.client(self.f.ann1)

    def test_qc2_actions_blocked_on_locked_job_batch_dataset_escalated_and_completed_audit(self) -> None:
        job = self.f.job(status=JobStatus.PENDING_QC2, frame_count=10)
        sample = ensure_qc2_sample(job)
        assert sample is not None
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

        # 4. Escalated job (BLOCK policy)
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

    def test_qc2_reject_creates_pinned_notification_in_vn_tz_sets_scope_and_total_rework_rounds(self) -> None:
        # 2026-11-26 18:30 UTC == 2026-11-27 01:30 Asia/Ho_Chi_Minh
        deadline_utc = datetime(2026, 11, 26, 18, 30, tzinfo=UTC)
        job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, deadline=deadline_utc)
        sample = ensure_qc2_sample(job)
        assert sample is not None

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

    def test_qc2_pass_with_pending_query_param_returns_200(self) -> None:
        job = self.f.job(status=JobStatus.PENDING_QC2)
        sample = ensure_qc2_sample(job)
        assert sample is not None
        res = self.qc2.post(self.f.url(f"audit-samples/{sample.id}/pass/?result=pending"), {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data["result"], AuditSample.Result.PASS)

    def test_historical_and_cross_stage_four_eyes_blocks_qc1_and_qc2_after_reassignment(self) -> None:
        multi = make_user("multi_stage", Role.ANNOTATOR, Role.QC1, Role.QC2, project=self.f.project)
        self.f.batch.qc2_confirmed_by = self.f.pm
        self.f.batch.qc2_confirmed_at = timezone.now()
        self.f.batch.save(update_fields=["qc2_confirmed_by", "qc2_confirmed_at"])

        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=multi)
        Job.objects.filter(pk=job.pk).update(qc1_reviewer=None)

        multi_client = self.f.client(multi)
        self.assertEqual(multi_client.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(multi_client.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json").status_code, 200)

        Job.objects.filter(pk=job.pk).update(annotator=self.f.ann2)
        job.refresh_from_db()

        ann_ids, _, _ = get_stage_history(job)
        self.assertIn(multi.id, ann_ids)
        self.assertIn(multi.id, four_eyes_conflicts(job))

        # multi bị chặn ở QC1 (ẩn khỏi pool và 403 khi gọi thẳng)
        self.assertEqual(multi_client.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 0)
        self.assertEqual(multi_client.post(self.f.url(f"qc1/jobs/{job.id}/start/"), {}, format="json").status_code, 403)
        self.assertEqual(multi_client.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 403)

        # qc1 duyệt job (batch đã confirm-qc2 → thẳng PENDING_QC2 + auto sample)
        self.assertEqual(self.qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 200)
        sample = AuditSample.objects.get(job=job, result=AuditSample.Result.PENDING)
        self.assertNotEqual(sample.auditor_id, multi.id)
        self.assertEqual(
            self.pm.post(self.f.url(f"audit-samples/{sample.id}/assign/"), {"auditor": multi.id}, format="json").status_code,
            400,
        )
        AuditSample.objects.filter(pk=sample.pk).update(auditor=None)
        self.assertEqual(multi_client.post(self.f.url(f"audit-samples/{sample.id}/pass/"), {}, format="json").status_code, 403)

        # Ngược lại: người đã audit QC2 không được QC1 lại job đó sau rework
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

    def test_ensure_qc2_sample_idempotent_and_handles_concurrent_integrity_error(self) -> None:
        job = self.f.job(status=JobStatus.PENDING_QC2, frame_count=10)
        first = ensure_qc2_sample(job)
        second = ensure_qc2_sample(job)
        assert first is not None and second is not None
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Audit.objects.filter(batch=self.f.batch, status=Audit.Status.IN_PROGRESS).count(), 1)
        self.assertEqual(AuditSample.objects.filter(job=job, result=AuditSample.Result.PENDING).count(), 1)

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
        assert recovered is not None
        self.assertEqual(recovered.pk, first.pk)

    def test_qc1_pool_excludes_locked_batch_and_dataset_and_reject_formats_vn_deadline(self) -> None:
        pool_job = self.f.job(
            status=JobStatus.PENDING_QC1,
            annotator=self.f.ann1,
            deadline=datetime(2026, 11, 26, 19, 15, tzinfo=UTC),  # 27/11 02:15 VN
        )
        Job.objects.filter(pk=pool_job.pk).update(qc1_reviewer=None)

        self.f.batch.status = DataStatus.LOCKED
        self.f.batch.save(update_fields=["status"])
        self.assertEqual(self.qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 0)
        self.f.batch.status = DataStatus.ACTIVE
        self.f.batch.save(update_fields=["status"])

        self.f.dataset.status = DataStatus.LOCKED
        self.f.dataset.save(update_fields=["status"])
        self.assertEqual(self.qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 0)
        self.f.dataset.status = DataStatus.ACTIVE
        self.f.dataset.save(update_fields=["status"])

        self.assertEqual(self.qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 1)
        res = self.qc1.post(
            self.f.url(f"qc1/jobs/{pool_job.id}/reject/"),
            {"errors": [{"category": self.f.category.id, "description": "thieu"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        pool_job.refresh_from_db()
        self.assertEqual(pool_job.total_rework_rounds, 1)
        notif = UserNotification.objects.get(
            recipient=self.f.ann1, job=pool_job, category=UserNotification.Category.REWORK
        )
        self.assertIn("27/11 02:15", notif.body)

    def test_invalid_int_params_return_400_and_large_search_does_not_500(self) -> None:
        job = self.f.job(status=JobStatus.PENDING_QC2)
        sample = ensure_qc2_sample(job)
        assert sample is not None

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
        search_res = self.qc1.get(self.f.url("qc1/jobs/?search=999999999999999999"))
        self.assertEqual(search_res.status_code, 200)

    def test_audit_sample_assign_enforces_four_eyes_and_blocks_non_pending_or_completed_audit(self) -> None:
        RoleAssignment.objects.create(user=self.f.ann1, role=Role.QC2, project=self.f.project)
        RoleAssignment.objects.create(user=self.f.qc1, role=Role.QC2, project=self.f.project)
        valid_qc2 = make_user("qc2_valid_assign", Role.QC2, project=self.f.project)

        job = self.f.job(
            status=JobStatus.PENDING_QC2,
            annotator=self.f.ann1,
            qc1_reviewer=self.f.qc1,
            frame_count=10,
        )
        sample = ensure_qc2_sample(job)
        assert sample is not None

        for conflicting_user in (self.f.ann1, self.f.qc1):
            resp = self.pm.post(
                self.f.url(f"audit-samples/{sample.id}/assign/"),
                {"auditor": conflicting_user.id},
                format="json",
            )
            self.assertEqual(resp.status_code, 400)
            self.assertIn("Luật bốn mắt", str(resp.data))

        non_qc2_resp = self.pm.post(
            self.f.url(f"audit-samples/{sample.id}/assign/"),
            {"auditor": self.f.ann2.id},
            format="json",
        )
        self.assertEqual(non_qc2_resp.status_code, 400)

        with patch("quality.views.schedule_assignee_push") as mock_push:
            ok = self.pm.post(
                self.f.url(f"audit-samples/{sample.id}/assign/"),
                {"auditor": valid_qc2.id},
                format="json",
            )
        self.assertEqual(ok.status_code, 200, ok.data)
        sample.refresh_from_db()
        self.assertEqual(sample.auditor, valid_qc2)
        mock_push.assert_called_once_with([job.id])
        self.assertTrue(ActivityLog.objects.filter(job=job, action="qc2.assign_auditor").exists())

        AuditSample.objects.filter(pk=sample.pk).update(result=AuditSample.Result.PASS)
        self.assertEqual(
            self.pm.post(
                self.f.url(f"audit-samples/{sample.id}/assign/"),
                {"auditor": self.f.qc2.id},
                format="json",
            ).status_code,
            400,
        )

        AuditSample.objects.filter(pk=sample.pk).update(result=AuditSample.Result.PENDING)
        Audit.objects.filter(pk=sample.audit_id).update(status=Audit.Status.COMPLETED)
        self.assertEqual(
            self.pm.post(
                self.f.url(f"audit-samples/{sample.id}/assign/"),
                {"auditor": self.f.qc2.id},
                format="json",
            ).status_code,
            400,
        )


class P0RegressionTests(TestCase):
    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.ann1 = self.f.client(self.f.ann1)

    def test_qc1_pass_locks_batch_before_job_and_assign_blocks_qc1_passed(self) -> None:
        job = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1)
        with CaptureQueriesContext(connection) as queries:
            updated = qc1_pass(job.id, project=self.f.project, actor=self.f.qc1)
        self.assertEqual(updated.status, JobStatus.QC1_PASSED)
        for_update = [q["sql"] for q in queries if "FOR UPDATE" in q["sql"]]
        self.assertTrue(for_update)
        self.assertIn("projects_batch", for_update[0])
        self.assertTrue(any("jobs_job" in sql for sql in for_update[1:]))

        res = self.pm.post(self.f.url(f"jobs/{job.id}/assign/"), {"annotator": self.f.ann2.id}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_reassign_preserves_prior_annotator_and_claim_excludes_qc2_auditor(self) -> None:
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1)
        res = self.pm.post(self.f.url(f"jobs/{job.id}/assign/"), {"annotator": self.f.ann2.id}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        ann_ids, _, _ = get_stage_history(job)
        self.assertIn(self.f.ann1.id, ann_ids)
        self.assertIn(self.f.ann2.id, ann_ids)

        pool_job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=None)
        audit = Audit.objects.create(
            project=self.f.project, batch=self.f.batch, method="random", sampling_rate=20, seed=0, eligible_count=1
        )
        AuditSample.objects.create(audit=audit, job=pool_job, auditor=self.f.ann1, result=AuditSample.Result.PASS)
        self.assertEqual(self.ann1.post(self.f.url("annotator/jobs/claim/"), {}, format="json").status_code, 400)

    def test_open_error_count_tracks_active_round_after_resolve_escalation(self) -> None:
        job = self.f.job(
            status=JobStatus.REWORK,
            annotator=self.f.ann1,
            rework_round=3,
            total_rework_rounds=3,
            is_escalated=True,
        )
        ReviewError.objects.create(
            job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category, severity="minor"
        )
        res = self.pm.post(
            self.f.url(f"jobs/{job.id}/resolve-escalation/"),
            {"note": "Reset vòng để làm lại"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)

        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        self.assertEqual(
            self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json").status_code,
            200,
        )
        qc1_reject(
            job.id,
            project=self.f.project,
            actor=self.f.qc1,
            errors=[
                {"category": self.f.category, "location": "f1", "description": "e1"},
                {"category": self.f.category, "location": "f2", "description": "e2"},
            ],
        )
        job.refresh_from_db()
        self.assertEqual((job.rework_round, job.total_rework_rounds), (1, 4))
        list_row = next(r for r in self.pm.get(self.f.url("jobs/")).data["results"] if r["id"] == job.id)
        detail = self.pm.get(self.f.url(f"jobs/{job.id}/")).data
        self.assertEqual(list_row["open_error_count"], 2)
        self.assertEqual(detail["open_error_count"], 2)

    def test_qc1_respects_escalation_policy_block_vs_warn_only(self) -> None:
        from projects.models import EscalationPolicy

        qc1 = self.f.client(self.f.qc1)
        job = self.f.job(
            status=JobStatus.PENDING_QC1,
            annotator=self.f.ann1,
            qc1_reviewer=None,
            rework_round=4,
            total_rework_rounds=4,
            is_escalated=True,
        )

        # Chế độ BLOCK: ẩn khỏi pool và chặn start/pass/reject
        self.f.project.escalation_policy = EscalationPolicy.BLOCK
        self.f.project.save(update_fields=["escalation_policy"])
        self.assertEqual(qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["count"], 0)
        self.assertEqual(qc1.post(self.f.url(f"qc1/jobs/{job.id}/start/"), {}, format="json").status_code, 400)
        self.assertEqual(qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json").status_code, 400)

        # Chế độ WARN_ONLY: hiện trong pool và cho phép start + pass
        self.f.project.escalation_policy = EscalationPolicy.WARN_ONLY
        self.f.project.save(update_fields=["escalation_policy"])
        pool_ids = [r["id"] for r in qc1.get(self.f.url("qc1/jobs/?scope=pool")).data["results"]]
        self.assertIn(job.id, pool_ids)
        self.assertEqual(qc1.post(self.f.url(f"qc1/jobs/{job.id}/start/"), {}, format="json").status_code, 200)
        pass_res = qc1.post(self.f.url(f"qc1/jobs/{job.id}/pass/"), {}, format="json")
        self.assertEqual(pass_res.status_code, 200, pass_res.data)
        self.assertEqual(pass_res.data["status"], JobStatus.QC1_PASSED)

    def test_error_category_duplicate_integrity_error_returns_400(self) -> None:
        with patch.object(ErrorCategory, "save", side_effect=IntegrityError("unique_error_category")):
            res = self.pm.post(
                self.f.url("error-categories/"),
                {"name": "Loại lỗi race", "severity": "minor"},
                format="json",
            )
            self.assertEqual(res.status_code, 400)

        with patch.object(ErrorCategory, "save", side_effect=IntegrityError("unique_error_category")):
            upd = self.pm.patch(
                self.f.url(f"error-categories/{self.f.category.id}/"),
                {"name": "Đổi tên race"},
                format="json",
            )
            self.assertEqual(upd.status_code, 400)

    def test_audit_sample_assign_requires_pending_qc2_status_and_locks_auditor(self) -> None:
        other_qc2 = make_user("qc2_lock_assign", Role.QC2, project=self.f.project)
        job = self.f.job(status=JobStatus.PENDING_QC2, frame_count=10)
        sample = ensure_qc2_sample(job)
        assert sample is not None

        with CaptureQueriesContext(connection) as q_assign:
            ok = self.pm.post(
                self.f.url(f"audit-samples/{sample.id}/assign/"),
                {"auditor": other_qc2.id},
                format="json",
            )
        self.assertEqual(ok.status_code, 200, ok.data)
        locks = [q["sql"] for q in q_assign if "FOR UPDATE" in q["sql"]]
        self.assertGreaterEqual(len(locks), 3)
        self.assertIn("quality_auditsample", locks[0])
        self.assertIn("jobs_job", locks[1])
        self.assertIn("accounts_user", locks[2])

        # Nếu job không còn ở trạng thái PENDING_QC2 → chặn phân auditor (400)
        Job.objects.filter(pk=job.pk).update(status=JobStatus.APPROVED)
        blocked = self.pm.post(
            self.f.url(f"audit-samples/{sample.id}/assign/"),
            {"auditor": self.f.qc2.id},
            format="json",
        )
        self.assertEqual(blocked.status_code, 400)

    def test_qc2_reject_unpins_confirm_qc2_notification_when_last_sample_resolved(self) -> None:
        job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, frame_count=10)
        sample = ensure_qc2_sample(job)
        assert sample is not None
        notif = UserNotification.objects.create(
            recipient=self.f.qc2,
            project=self.f.project,
            batch=self.f.batch,
            category=UserNotification.Category.REVIEW_NEEDED,
            title=f"Task {self.f.batch.name} đã được xác nhận chuyển QC2",
            is_pinned_pending=True,
        )
        res = self.f.client(self.f.qc2).post(
            self.f.url(f"audit-samples/{sample.id}/reject/"),
            {"errors": [{"category": self.f.category.id, "description": "sai"}]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        notif.refresh_from_db()
        self.assertFalse(notif.is_pinned_pending)

    def test_pick_auditor_locks_candidate_user_and_skips_revoked_role(self) -> None:
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from quality.qc2 import pick_auditor

        job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, frame_count=10)
        with CaptureQueriesContext(connection) as ctx:
            picked = pick_auditor(job)
        self.assertEqual(picked, self.f.qc2)
        self.assertTrue(
            any("accounts_user" in q["sql"] and "FOR UPDATE" in q["sql"] for q in ctx),
            "pick_auditor phải khoá dòng accounts_user với FOR UPDATE",
        )

    def test_error_category_id_oracle_uniform_for_foreign_and_missing_ids(self) -> None:
        other = ProjectFixture(name="err_oracle")
        foreign_cat_id = other.category.id
        missing_cat_id = foreign_cat_id + 99999

        # QC1 reject: foreign category ID và nonexistent ID trả cùng 400 payload
        qc1_job = self.f.job(status=JobStatus.QC1_REVIEWING, annotator=self.f.ann1, qc1_reviewer=self.f.qc1)
        qc1 = self.f.client(self.f.qc1)
        r_foreign_qc1 = qc1.post(
            self.f.url(f"qc1/jobs/{qc1_job.id}/reject/"),
            {"errors": [{"category": foreign_cat_id, "description": "x"}]},
            format="json",
        )
        r_missing_qc1 = qc1.post(
            self.f.url(f"qc1/jobs/{qc1_job.id}/reject/"),
            {"errors": [{"category": missing_cat_id, "description": "x"}]},
            format="json",
        )
        self.assertEqual(r_foreign_qc1.status_code, 400)
        self.assertEqual(r_missing_qc1.status_code, 400)
        self.assertEqual(r_foreign_qc1.data, r_missing_qc1.data)

        # QC2 reject: foreign category ID và nonexistent ID trả cùng 400 payload
        qc2_job = self.f.job(status=JobStatus.PENDING_QC2, annotator=self.f.ann1, frame_count=10)
        sample = ensure_qc2_sample(qc2_job)
        assert sample is not None
        qc2 = self.f.client(self.f.qc2)
        r_foreign_qc2 = qc2.post(
            self.f.url(f"audit-samples/{sample.id}/reject/"),
            {"errors": [{"category": foreign_cat_id, "description": "x"}]},
            format="json",
        )
        r_missing_qc2 = qc2.post(
            self.f.url(f"audit-samples/{sample.id}/reject/"),
            {"errors": [{"category": missing_cat_id, "description": "x"}]},
            format="json",
        )
        self.assertEqual(r_foreign_qc2.status_code, 400)
        self.assertEqual(r_missing_qc2.status_code, 400)
        self.assertEqual(r_foreign_qc2.data, r_missing_qc2.data)
