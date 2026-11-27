from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from projects.models import ActivityLog, Batch, Dataset, DataStatus, EscalationPolicy, UserNotification
from quality.models import Audit, AuditSample, ReviewError, ReviewStage
from teams.models import Team, TeamMember

from .models import DailyOutputRecord, Job, JobStatus, ReworkScope


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

    def test_locked_job_cannot_be_reassigned_and_delivered_job_cannot_be_locked(self):
        self.pm.post(self.f.url(f"jobs/{self.job.id}/lock/"))
        response = self.pm.post(self.f.url(f"jobs/{self.job.id}/assign/"), {"annotator": self.f.ann2.id}, format="json")
        self.assertEqual(response.status_code, 400)

        delivered = self.f.job(status=JobStatus.DELIVERED)
        self.assertEqual(self.pm.post(self.f.url(f"jobs/{delivered.id}/lock/"), {}, format="json").status_code, 400)
        delivered.is_locked = True
        delivered.save(update_fields=["is_locked"])
        self.assertEqual(self.pm.post(self.f.url(f"jobs/{delivered.id}/unlock/"), {}, format="json").status_code, 400)

    def test_bulk_deadline_and_overdue_filter_and_note_required_on_change(self):
        other = self.f.job(status=JobStatus.PENDING_QC1)
        past = (timezone.now() - timedelta(hours=1)).isoformat()
        body = {"ids": [self.job.id, other.id], "deadline": past}
        self.assertEqual(self.pm.post(self.f.url("jobs/bulk-deadline/"), body, format="json").status_code, 200)
        self.assertEqual(self.pm.get(self.f.url("jobs/?overdue=1")).data["count"], 2)

        # Thay đổi deadline đã đặt mà không ghi lý do (note) → 400 trên cả single & bulk
        new_dl = (timezone.now() + timedelta(days=2)).isoformat()
        self.assertEqual(
            self.pm.post(self.f.url(f"jobs/{self.job.id}/deadline/"), {"deadline": new_dl}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.pm.post(
                self.f.url("jobs/bulk-deadline/"),
                {"ids": [self.job.id, other.id], "deadline": new_dl, "note": "   "},
                format="json",
            ).status_code,
            400,
        )
        ok_bulk = self.pm.post(
            self.f.url("jobs/bulk-deadline/"),
            {"ids": [self.job.id, other.id], "deadline": new_dl, "note": "Khách hàng gia hạn"},
            format="json",
        )
        self.assertEqual(ok_bulk.status_code, 200, ok_bulk.data)

    def test_deadline_enforces_strict_rfc3339_and_normalizes_to_utc(self):
        ok = self.pm.post(
            self.f.url(f"jobs/{self.job.id}/deadline/"),
            {"deadline": "2026-11-26T15:30:00+07:00", "note": "Gia hạn"},
            format="json",
        )
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(ok.data["deadline"], "2026-11-26T08:30:00Z")
        log = ActivityLog.objects.filter(job=self.job, action="job.deadline").latest("id")
        self.assertIsNotNone(log.after)
        assert log.after is not None
        self.assertEqual(log.after["deadline"], "2026-11-26T08:30:00Z")

        for invalid in (
            "2026-11-26T15:30:00",
            "2026-11-26 15:30:00Z",
            "2026-11-26",
            "26/11/2026 15:30",
        ):
            res = self.pm.post(
                self.f.url(f"jobs/{self.job.id}/deadline/"),
                {"deadline": invalid, "note": "Thử sai"},
                format="json",
            )
            self.assertEqual(res.status_code, 400, f"Expected 400 for {invalid!r}, got {res.status_code}")

    def test_deadline_query_filters_validate_iso_and_respect_vn_timezone(self):
        # 2026-11-26T18:00:00Z == 2026-11-27 01:00 ở Asia/Ho_Chi_Minh (UTC+7)
        self.pm.post(
            self.f.url(f"jobs/{self.job.id}/deadline/"),
            {"deadline": "2026-11-26T18:00:00Z"},
            format="json",
        )
        in_vn_27 = self.pm.get(self.f.url("jobs/?deadline_from=2026-11-27&deadline_to=2026-11-27"))
        self.assertEqual(in_vn_27.status_code, 200, in_vn_27.data)
        self.assertEqual(in_vn_27.data["count"], 1)
        in_vn_26 = self.pm.get(self.f.url("jobs/?deadline_from=2026-11-26&deadline_to=2026-11-26"))
        self.assertEqual(in_vn_26.status_code, 200, in_vn_26.data)
        self.assertEqual(in_vn_26.data["count"], 0)

        for qs in (
            "deadline_from=not-a-date",
            "deadline_from=2026-11-26T15:30:00",
            "deadline_to=26/11/2026",
            "deadline_from=2026-11-28&deadline_to=2026-11-27",
        ):
            res = self.pm.get(self.f.url(f"jobs/?{qs}"))
            self.assertEqual(res.status_code, 400, f"Expected 400 for {qs!r}, got {res.status_code}")

    def test_resolve_escalation_unpins_escalated_notifications(self):
        self.job.is_escalated, self.job.rework_round = True, 3
        self.job.save()
        esc_notif = UserNotification.objects.create(
            recipient=self.f.pm,
            project=self.f.project,
            job=self.job,
            category=UserNotification.Category.ESCALATED,
            title="Escalated",
            is_pinned_pending=True,
            is_read=False,
        )
        response = self.pm.post(
            self.f.url(f"jobs/{self.job.id}/resolve-escalation/"),
            {"annotator": self.f.ann2.id},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["is_escalated"])
        self.assertEqual(response.data["rework_round"], 0)
        self.assertEqual(response.data["total_rework_rounds"], 3)
        esc_notif.refresh_from_db()
        self.assertFalse(esc_notif.is_pinned_pending)
        self.assertTrue(esc_notif.is_read)

    def test_hours_remaining_is_none_when_done_and_overdue_hours_frozen(self):
        now = timezone.now()
        done_job = self.f.job(
            status=JobStatus.APPROVED,
            deadline=now - timedelta(hours=5),
            submitted_at=now - timedelta(hours=2),
        )
        self.assertIsNone(done_job.hours_remaining)
        self.assertEqual(done_job.overdue_hours, 3.0)
        self.assertFalse(done_job.is_on_time)

        on_time_job = self.f.job(
            status=JobStatus.APPROVED,
            deadline=now + timedelta(hours=2),
            submitted_at=now - timedelta(hours=1),
        )
        self.assertIsNone(on_time_job.hours_remaining)
        self.assertEqual(on_time_job.overdue_hours, 0.0)
        self.assertTrue(on_time_job.is_on_time)

    def test_job_queue_counts_by_stage(self):
        self.f.job(status=JobStatus.PENDING_QC2)
        data = self.pm.get(self.f.url("job-queue/")).data
        stages = {s["stage"]: s["total"] for s in data["stages"]}
        self.assertEqual(stages, {"annotation": 1, "qc1": 0, "qc2": 1})

    @override_settings(CVAT_PUBLIC_URL="https://cvat.example.com")
    def test_cvat_url_appends_org_slug_when_present(self):
        cvat_job = self.f.job(cvat_task_id=10, cvat_job_id=20)
        self.assertEqual(cvat_job.cvat_url(), "https://cvat.example.com/tasks/10/jobs/20")
        self.f.project.cvat_org_slug = "acme-org"
        self.f.project.save(update_fields=["cvat_org_slug"])
        cvat_job.refresh_from_db()
        self.assertIn("https://cvat.example.com/tasks/10/jobs/20", cvat_job.cvat_url() or "")


class JobQc2ColumnTests(TestCase):
    def test_job_list_exposes_open_audit_sample_auditor(self):
        from quality.qc2 import ensure_qc2_sample

        f = ProjectFixture()
        waiting = [f.job() for _ in range(2)]
        in_qc1 = f.job(status=JobStatus.PENDING_QC1)
        for job in waiting + [in_qc1]:
            ensure_qc2_sample(job)
        pm = f.client(f.pm)
        rows = {r["id"]: r for r in pm.get(f.url("jobs/")).data["results"]}
        self.assertEqual([rows[j.id]["qc2"]["auditor"]["id"] for j in waiting], [f.qc2.id, f.qc2.id])
        self.assertIsNone(rows[in_qc1.id]["qc2"])  # chưa tới QC2 → chưa có lượt kiểm


class AnnotatorWorkflowTests(TestCase):
    """Kiểm thử không gian Annotator: phạm vi, chuyển trạng thái nguyên tử, khoá, escalation, sản lượng ngày."""

    def setUp(self):
        self.f = ProjectFixture()
        self.job_mine = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1)
        self.job_other = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2)
        self.ann1 = self.f.client(self.f.ann1)

    def test_non_annotator_cannot_access_annotator_endpoints(self):
        self.assertEqual(self.f.client(self.f.qc1).get(self.f.url("annotator/jobs/")).status_code, 403)
        self.assertEqual(self.f.client(self.f.pm).get(self.f.url("annotator/jobs/")).status_code, 403)

    def test_annotator_only_sees_own_jobs_and_cannot_touch_others(self):
        data = self.ann1.get(self.f.url("annotator/jobs/")).data
        self.assertEqual([r["id"] for r in data["results"]], [self.job_mine.id])
        self.assertEqual(self.ann1.get(self.f.url(f"annotator/jobs/{self.job_other.id}/")).status_code, 404)
        self.assertEqual(
            self.ann1.post(self.f.url(f"annotator/jobs/{self.job_other.id}/start/"), {}, format="json").status_code,
            404,
        )

    def test_start_then_submit_updates_status_object_count_daily_output_and_logs_activity(self):
        early = self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/submit/"), {}, format="json")
        self.assertEqual(early.status_code, 400)

        started = self.ann1.post(
            self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {"note": "bat dau"}, format="json"
        )
        self.assertEqual(started.status_code, 200, started.data)
        self.assertEqual(started.data["status"], JobStatus.ANNOTATING)

        submitted = self.ann1.post(
            self.f.url(f"annotator/jobs/{self.job_mine.id}/submit/"),
            {"note": "da xong", "object_count": 42},
            format="json",
        )
        self.assertEqual(submitted.status_code, 200, submitted.data)
        self.assertEqual(submitted.data["status"], JobStatus.PENDING_QC1)
        self.assertEqual(submitted.data["object_count"], 42)
        self.assertEqual(submitted.data["last_counted_objects"], 42)
        self.assertEqual(submitted.data["round_credited_objects"], 42)
        self.assertEqual(len(submitted.data["timeline"]), 2)
        self.assertEqual(submitted.data["timeline"][-1]["action"], "job.status")
        self.assertEqual(submitted.data["timeline"][-1]["after"]["status"], JobStatus.PENDING_QC1)

        rec = DailyOutputRecord.objects.get(job=self.job_mine, user=self.f.ann1)
        self.assertEqual(rec.object_count, 42)
        self.assertFalse(rec.is_rework)
        self.assertEqual(rec.source, DailyOutputRecord.Source.SUBMIT)

        overview = self.f.client(self.f.pm).get(self.f.url("overview/")).data
        self.assertEqual(overview["metrics"]["submitted_in_period"]["value"], 1)

    def test_partial_rework_daily_output_uses_exact_active_round_and_ignores_voided_errors(self):
        # Round 0 có 2 lỗi cũ; round 1 có 1 lỗi đã bị void → khi nộp vòng rework_round=2,
        # KHÔNG được hồi sinh 2 lỗi của round 0 (credited phải là 0 khi object_count không đổi).
        job = self.f.job(
            status=JobStatus.ANNOTATING,
            annotator=self.f.ann1,
            rework_round=2,
            total_rework_rounds=2,
            rework_scope=ReworkScope.PARTIAL,
            object_count=50,
            last_counted_objects=50,
            round_credited_objects=0,
        )
        ReviewError.objects.create(
            job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category, severity="major", location="F1"
        )
        ReviewError.objects.create(
            job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category, severity="major", location="F2"
        )
        ReviewError.objects.create(
            job=job,
            stage=ReviewStage.QC1,
            rework_round=1,
            category=self.f.category,
            severity="major",
            location="F3",
            is_voided=True,
        )

        res = self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(DailyOutputRecord.objects.filter(job=job).count(), 0)

        # Thêm 1 lỗi active đúng vòng rework_round - 1 (= 1) và nộp lại → ghi nhận đúng 1 object rework
        job.status = JobStatus.ANNOTATING
        job.save(update_fields=["status"])
        ReviewError.objects.create(
            job=job,
            stage=ReviewStage.QC1,
            rework_round=1,
            category=self.f.category,
            severity="major",
            frame_number=12,
            cvat_object_id=88,
            is_voided=False,
        )
        res2 = self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json")
        self.assertEqual(res2.status_code, 200, res2.data)
        rec = DailyOutputRecord.objects.get(job=job)
        self.assertEqual(rec.object_count, 1)
        self.assertTrue(rec.is_rework)

    def test_submit_notifies_only_same_team_qc1_when_unassigned_falling_back_to_org(self):
        qc1_a = make_user("qc1_team_a", Role.QC1, project=self.f.project)
        qc1_b = make_user("qc1_team_b", Role.QC1, project=self.f.project)
        team_a = Team.objects.create(project=self.f.project, name="Team Alpha")
        team_b = Team.objects.create(project=self.f.project, name="Team Beta")
        TeamMember.objects.create(team=team_a, user=qc1_a)
        TeamMember.objects.create(team=team_b, user=qc1_b)
        self.f.batch.team = team_a
        self.f.batch.save(update_fields=["team"])

        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1)
        job.qc1_reviewer = None
        job.save(update_fields=["qc1_reviewer"])

        res = self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json")
        self.assertEqual(res.status_code, 200, res.data)
        notified_ids = set(
            UserNotification.objects.filter(
                project=self.f.project, job=job, category=UserNotification.Category.REVIEW_NEEDED
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(notified_ids, {qc1_a.id})

        # Team không có QC1 → fallback sang toàn bộ QC1 của organization
        team_empty = Team.objects.create(project=self.f.project, name="Team NoQC1")
        batch_empty = Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="B-Empty", team=team_empty
        )
        job2 = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, batch=batch_empty)
        job2.qc1_reviewer = None
        job2.save(update_fields=["qc1_reviewer"])
        res2 = self.ann1.post(self.f.url(f"annotator/jobs/{job2.id}/submit/"), {}, format="json")
        self.assertEqual(res2.status_code, 200, res2.data)
        notified_ids_2 = set(
            UserNotification.objects.filter(
                project=self.f.project, job=job2, category=UserNotification.Category.REVIEW_NEEDED
            ).values_list("recipient_id", flat=True)
        )
        self.assertEqual(notified_ids_2, {self.f.qc1.id, qc1_a.id, qc1_b.id})

    def test_negative_object_count_rejected_with_400(self):
        self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json")
        resp = self.ann1.post(
            self.f.url(f"annotator/jobs/{self.job_mine.id}/submit/"),
            {"object_count": -5},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_locked_batch_or_locked_or_escalated_job_blocked(self):
        self.job_mine.is_locked = True
        self.job_mine.save(update_fields=["is_locked"])
        self.assertEqual(
            self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json").status_code, 400
        )

        self.job_mine.is_locked = False
        self.job_mine.status = JobStatus.REWORK
        self.job_mine.is_escalated = True
        self.job_mine.save(update_fields=["is_locked", "status", "is_escalated"])
        self.assertEqual(
            self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json").status_code, 400
        )

        self.job_mine.is_escalated = False
        self.job_mine.save(update_fields=["is_escalated"])
        self.f.batch.status = DataStatus.LOCKED
        self.f.batch.save(update_fields=["status"])
        self.assertEqual(
            self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json").status_code, 400
        )

        self.f.batch.status = DataStatus.ACTIVE
        self.f.batch.save(update_fields=["status"])
        self.f.dataset.status = DataStatus.LOCKED
        self.f.dataset.save(update_fields=["status"])
        self.assertEqual(
            self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json").status_code, 400
        )

    def test_invalid_batch_filter_returns_400(self):
        self.assertEqual(self.ann1.get(self.f.url("annotator/jobs/?batch=abc")).status_code, 400)

    def test_rework_tab_and_resubmit_flow(self):
        rework_job = self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1, rework_round=1)
        listed = self.ann1.get(self.f.url("annotator/jobs/?tab=rework")).data
        self.assertEqual([r["id"] for r in listed["results"]], [rework_job.id])

        r1 = self.ann1.post(self.f.url(f"annotator/jobs/{rework_job.id}/start/"), {}, format="json")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.data["status"], JobStatus.ANNOTATING)

        r2 = self.ann1.post(self.f.url(f"annotator/jobs/{rework_job.id}/submit/"), {}, format="json")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data["status"], JobStatus.PENDING_QC1)
        self.assertEqual(r2.data["timeline"][-1]["after"]["event"], "annotator.resubmit")

    def test_db06_priority_ordering_and_claim_respects_wip_limit(self):
        now = timezone.now()
        self.job_mine.deadline = now + timedelta(days=3)
        self.job_mine.save(update_fields=["deadline"])
        pool1 = Job.objects.create(
            project=self.f.project,
            dataset=self.f.dataset,
            batch=self.f.batch,
            name="POOL-1",
            status=JobStatus.PENDING_ANNOTATION,
            deadline=now + timedelta(hours=6),
            target_object_count=1000,
        )
        pool2 = Job.objects.create(
            project=self.f.project,
            dataset=self.f.dataset,
            batch=self.f.batch,
            name="POOL-2",
            status=JobStatus.PENDING_ANNOTATION,
            deadline=now + timedelta(days=2),
        )

        claimed = self.ann1.post(self.f.url("annotator/jobs/claim/"), {}, format="json")
        self.assertEqual(claimed.status_code, 200, claimed.data)
        self.assertEqual(claimed.data["id"], pool1.id)

        blocked = self.ann1.post(self.f.url("annotator/jobs/claim/"), {}, format="json")
        self.assertEqual(blocked.status_code, 400)

        listed = self.ann1.get(self.f.url("annotator/jobs/?tab=active")).data["results"]
        self.assertEqual([r["id"] for r in listed], [pool1.id, self.job_mine.id])
        self.assertTrue(Job.objects.filter(pk=pool2.id, annotator__isnull=True).exists())

    def test_annotator_requests_dispute_voiding_data_issue_and_notifications(self):
        team = Team.objects.create(project=self.f.project, name="Team Alpha")
        TeamMember.objects.create(team=team, user=self.f.ann1)

        err = ReviewError.objects.create(
            job=self.job_mine,
            stage=ReviewStage.QC1,
            rework_round=1,
            category=self.f.category,
            severity="major",
            location="Frame 231 · Object 12",
            description="ID xe đổi từ 12 sang 47",
            reported_by=self.f.qc1,
        )

        r_dispute = self.ann1.post(
            self.f.url("annotator/requests/"),
            {
                "job": self.job_mine.id,
                "review_error": err.id,
                "request_type": "error_dispute",
                "reason": "Frame 230 xe bị che khuất hoàn toàn nên CVAT cấp track mới.",
            },
            format="json",
        )
        self.assertEqual(r_dispute.status_code, 201, r_dispute.data)
        self.assertEqual(r_dispute.data["status"], "pending_pm")
        self.assertEqual(r_dispute.data["handler"]["id"], self.f.pm.id)
        self.assertEqual(r_dispute.data["handler_role"], "PM")

        r_data = self.ann1.post(
            self.f.url("annotator/requests/"),
            {
                "job": self.job_mine.id,
                "request_type": "data_issue",
                "title": "Point cloud mờ frame 90–96",
                "reason": "Thiếu điểm Lidar ở frame 90–96 không thể căn cuboid.",
            },
            format="json",
        )
        self.assertEqual(r_data.status_code, 201, r_data.data)
        self.assertEqual(r_data.data["status"], "pending_pm")
        self.assertEqual(r_data.data["handler"]["id"], self.f.pm.id)

        self.assertEqual(len(self.f.client(self.f.ann2).get(self.f.url("annotator/requests/")).data), 0)

        resolved = self.f.client(self.f.pm).post(
            self.f.url(f"annotator/requests/{r_dispute.data['id']}/resolve/"),
            {"status": "resolved", "resolution_note": "Đã kiểm tra và gỡ lỗi sai ID."},
            format="json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.data)
        self.assertEqual(resolved.data["status"], "resolved")
        err.refresh_from_db()
        self.assertTrue(err.is_voided)

        # Chặn phản hồi lại lỗi đã bị void
        dispute_voided = self.ann1.post(
            self.f.url("annotator/requests/"),
            {
                "job": self.job_mine.id,
                "review_error": err.id,
                "request_type": "error_dispute",
                "reason": "Thử phản hồi lỗi đã gỡ.",
            },
            format="json",
        )
        self.assertEqual(dispute_voided.status_code, 400)

        again = self.f.client(self.f.pm).post(
            self.f.url(f"annotator/requests/{r_dispute.data['id']}/resolve/"),
            {"status": "rejected", "resolution_note": "Đổi ý"},
            format="json",
        )
        self.assertEqual(again.status_code, 400)

        self.job_mine.status = JobStatus.REWORK
        self.job_mine.rework_round = 2
        self.job_mine.save(update_fields=["status", "rework_round"])
        rework_list = self.ann1.get(self.f.url("annotator/jobs/?tab=rework&include_errors=1"))
        self.assertEqual(rework_list.status_code, 200)
        self.assertEqual(len(rework_list.data["results"][0]["errors"]), 1)
        self.assertEqual(rework_list.data["results"][0]["open_error_count"], 0)  # lỗi đã void không tính vào lỗi mở

        notifs = self.ann1.get(self.f.url("notifications/"))
        self.assertEqual(notifs.status_code, 200, notifs.data)
        self.assertGreaterEqual(notifs.data["all_count"], 2)
        mark = self.ann1.post(self.f.url("notifications/mark-read/"), {}, format="json")
        self.assertEqual(mark.status_code, 200)

        search = self.ann1.get(self.f.url(f"annotator/search/?q={self.job_mine.name}"))
        self.assertEqual(search.status_code, 200)
        self.assertEqual([j["id"] for j in search.data["jobs"]], [self.job_mine.id])

    def test_escalation_warn_only_policy_bulk_move_batch_and_team_claim_scoping(self):
        # warn_only cho phép annotator tiếp tục sửa dù is_escalated=True
        self.f.project.escalation_policy = EscalationPolicy.WARN_ONLY
        self.f.project.save(update_fields=["escalation_policy"])
        self.job_mine.status = JobStatus.REWORK
        self.job_mine.is_escalated = True
        self.job_mine.save(update_fields=["status", "is_escalated"])
        ok_warn = self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json")
        self.assertEqual(ok_warn.status_code, 200, ok_warn.data)

        # Chặn chặt theo team khi claim
        team_a = Team.objects.create(project=self.f.project, name="Team A")
        team_b = Team.objects.create(project=self.f.project, name="Team B")
        TeamMember.objects.create(team=team_a, user=self.f.ann1)
        batch_b = Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="Batch B", team=team_b
        )
        Job.objects.create(
            project=self.f.project,
            dataset=self.f.dataset,
            batch=batch_b,
            name="OTHER-TEAM-JOB",
            status=JobStatus.PENDING_ANNOTATION,
        )
        denied = self.ann1.post(self.f.url("annotator/jobs/claim/"), {}, format="json")
        self.assertEqual(denied.status_code, 400)

        # bulk-move-batch đồng bộ cả batch lẫn dataset đích
        ds_dest = Dataset.objects.create(project=self.f.project, name="D2")
        batch_dest = Batch.objects.create(project=self.f.project, dataset=ds_dest, name="Batch Dest")
        moved = self.f.client(self.f.pm).post(
            self.f.url("jobs/bulk-move-batch/"),
            {"ids": [self.job_mine.id], "batch": batch_dest.id, "note": "gom lô"},
            format="json",
        )
        self.assertEqual(moved.status_code, 200, moved.data)
        self.job_mine.refresh_from_db()
        self.assertEqual(self.job_mine.batch_id, batch_dest.id)
        self.assertEqual(self.job_mine.dataset_id, ds_dest.id)

        # bulk-move-batch từ chối job đã liên kết CVAT
        cvat_job = self.f.job(status=JobStatus.ANNOTATING, cvat_job_id=9001, cvat_task_id=50)
        blocked_cvat = self.f.client(self.f.pm).post(
            self.f.url("jobs/bulk-move-batch/"),
            {"ids": [cvat_job.id], "batch": batch_dest.id},
            format="json",
        )
        self.assertEqual(blocked_cvat.status_code, 400)


class JobHardeningAndSecurityTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.pm = self.f.client(self.f.pm)
        self.ann1 = self.f.client(self.f.ann1)

    def test_resolve_escalation_keeps_total_rework_rounds_and_checks_editable(self):
        job = self.f.job(
            status=JobStatus.REWORK,
            annotator=self.f.ann1,
            rework_round=3,
            total_rework_rounds=3,
            is_escalated=True,
            is_locked=True,
        )
        blocked = self.pm.post(self.f.url(f"jobs/{job.id}/resolve-escalation/"), {}, format="json")
        self.assertEqual(blocked.status_code, 400)

        job.is_locked = False
        job.save(update_fields=["is_locked"])

        ok = self.pm.post(self.f.url(f"jobs/{job.id}/resolve-escalation/?escalated=1"), {}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        job.refresh_from_db()
        self.assertFalse(job.is_escalated)
        self.assertEqual(job.rework_round, 0)
        self.assertEqual(job.total_rework_rounds, 3)

    def test_assign_blocks_post_qc1_statuses_enforces_historical_four_eyes_and_batches_cvat(self):
        # P0 #6: block reassignment from QC1_PASSED onward as well as QC2/approved/delivered
        for st in (JobStatus.QC1_PASSED, JobStatus.PENDING_QC2, JobStatus.APPROVED, JobStatus.DELIVERED):
            locked_stage_job = self.f.job(status=st, annotator=self.f.ann1)
            res = self.pm.post(
                self.f.url(f"jobs/{locked_stage_job.id}/assign/"),
                {"annotator": self.f.ann2.id},
                format="json",
            )
            self.assertEqual(res.status_code, 400, f"Status {st} should reject assign")

        dual = make_user("dual_all", Role.ANNOTATOR, Role.QC1, Role.QC2, project=self.f.project)

        j_hist_ann = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann2)
        ActivityLog.record(
            project=self.f.project,
            actor=dual,
            action="job.status",
            target=j_hist_ann,
            job=j_hist_ann,
            after={"status": JobStatus.PENDING_QC1, "event": "annotator.submit"},
        )
        self.assertEqual(
            self.pm.post(
                self.f.url(f"jobs/{j_hist_ann.id}/assign/"), {"qc1_reviewer": dual.id}, format="json"
            ).status_code,
            400,
        )

        j_hist_qc1 = self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1)
        j_hist_qc1.qc1_reviewer = None
        j_hist_qc1.save(update_fields=["qc1_reviewer"])
        ReviewError.objects.create(
            job=j_hist_qc1,
            stage=ReviewStage.QC1,
            rework_round=0,
            category=self.f.category,
            severity="minor",
            reported_by=dual,
        )
        self.assertEqual(
            self.pm.post(self.f.url(f"jobs/{j_hist_qc1.id}/assign/"), {"annotator": dual.id}, format="json").status_code,
            400,
        )

        j_hist_qc2 = self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1)
        audit = Audit.objects.create(
            project=self.f.project, batch=self.f.batch, method="random", sampling_rate=20, seed=0, eligible_count=1
        )
        AuditSample.objects.create(
            audit=audit, job=j_hist_qc2, rework_round=0, auditor=dual, reviewed_by=dual, result=AuditSample.Result.REJECT
        )
        self.assertEqual(
            self.pm.post(self.f.url(f"jobs/{j_hist_qc2.id}/assign/"), {"annotator": dual.id}, format="json").status_code,
            400,
        )
        self.assertEqual(
            self.pm.post(
                self.f.url(f"jobs/{j_hist_qc2.id}/assign/"), {"qc1_reviewer": dual.id}, format="json"
            ).status_code,
            400,
        )

        j1 = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1)
        j2 = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1)
        with patch("jobs.views.schedule_assignee_push") as mock_push:
            res = self.pm.post(
                self.f.url("jobs/bulk-assign/"),
                {"ids": [j1.id, j2.id], "annotator": self.f.ann2.id},
                format="json",
            )
        self.assertEqual(res.status_code, 200, res.data)
        mock_push.assert_called_once_with(sorted([j1.id, j2.id]))

    def test_due_soon_filter_bad_int_params_and_overflow_guards(self):
        now = timezone.now()
        j_soon_active = self.f.job(
            status=JobStatus.ANNOTATING, annotator=self.f.ann1, deadline=now + timedelta(hours=6)
        )
        j_soon_qc1 = self.f.job(
            status=JobStatus.PENDING_QC1, annotator=self.f.ann1, deadline=now + timedelta(hours=6)
        )
        self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, deadline=now - timedelta(hours=2))
        self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, deadline=now + timedelta(days=3))
        self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, deadline=now + timedelta(hours=6))

        pm_soon = self.pm.get(self.f.url("jobs/?due_soon=1"))
        self.assertEqual(pm_soon.status_code, 200)
        self.assertEqual({r["id"] for r in pm_soon.data["results"]}, {j_soon_active.id, j_soon_qc1.id})

        ann_soon = self.ann1.get(self.f.url("annotator/jobs/?due_soon=1"))
        self.assertEqual(ann_soon.status_code, 200)
        self.assertEqual([r["id"] for r in ann_soon.data["results"]], [j_soon_active.id])

        for path in [
            "jobs/?batch=abc",
            "jobs/?dataset=abc",
            "jobs/?assignee=abc",
            "jobs/?batch=999999999999",
            "job-queue/?batch=abc",
            "annotator/requests/?job=abc",
        ]:
            self.assertEqual(self.pm.get(self.f.url(path)).status_code, 400, f"Expected 400 for {path}")
        self.assertEqual(self.ann1.get(self.f.url("annotator/jobs/?batch=999999999999")).status_code, 400)

        giant = "999999999999999999999"
        self.assertEqual(self.pm.get(self.f.url(f"jobs/?search={giant}")).status_code, 200)
        self.assertEqual(self.ann1.get(self.f.url(f"annotator/jobs/?search={giant}")).status_code, 200)
        self.assertEqual(self.ann1.get(self.f.url(f"annotator/search/?q={giant}")).status_code, 200)

        over = self.ann1.post(
            self.f.url(f"annotator/jobs/{j_soon_active.id}/submit/"),
            {"object_count": 2_147_483_648},
            format="json",
        )
        self.assertEqual(over.status_code, 400)

    def test_start_rework_refreshes_started_at_and_open_error_count_tracks_active_round(self):
        old_start = timezone.now() - timedelta(days=3)
        job = self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1, rework_round=2, started_at=old_start)
        ReviewError.objects.create(job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category, severity="minor")
        ReviewError.objects.create(job=job, stage=ReviewStage.QC1, rework_round=1, category=self.f.category, severity="major")
        ReviewError.objects.create(job=job, stage=ReviewStage.QC1, rework_round=1, category=self.f.category, severity="major")

        detail_rw = self.ann1.get(self.f.url(f"annotator/jobs/{job.id}/")).data
        self.assertEqual(detail_rw["open_error_count"], 2)

        started = self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/start/"), {}, format="json")
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.data["open_error_count"], 2)
        job.refresh_from_db()
        assert job.started_at is not None
        self.assertGreater(job.started_at, old_start)

        submitted = self.ann1.post(self.f.url(f"annotator/jobs/{job.id}/submit/"), {}, format="json")
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.data["open_error_count"], 0)

    def test_annotator_request_duplicates_approved_double_resolve_and_pm_unpin(self):
        pm2 = make_user("pm_second", Role.PROJECT_MANAGER, project=self.f.project)

        self.assertEqual(self.f.client(self.f.qc1).get(self.f.url("annotator/requests/")).status_code, 403)

        approved_job = self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1)
        self.assertEqual(
            self.ann1.post(
                self.f.url("annotator/requests/"),
                {"job": approved_job.id, "request_type": "data_issue", "reason": "Lỗi dữ liệu"},
                format="json",
            ).status_code,
            400,
        )

        job = self.f.job(status=JobStatus.REWORK, annotator=self.f.ann1, rework_round=1)
        err = ReviewError.objects.create(
            job=job, stage=ReviewStage.QC1, rework_round=0, category=self.f.category, severity="major"
        )

        created = self.ann1.post(
            self.f.url("annotator/requests/"),
            {"job": job.id, "review_error": err.id, "request_type": "error_dispute", "reason": "Đúng guideline"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)
        req_id = created.data["id"]
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=self.f.pm, job=job, category=UserNotification.Category.DISPUTE, is_pinned_pending=True
            ).exists()
        )
        self.assertTrue(
            UserNotification.objects.filter(
                recipient=pm2, job=job, category=UserNotification.Category.DISPUTE, is_pinned_pending=True
            ).exists()
        )

        dup_err = self.ann1.post(
            self.f.url("annotator/requests/"),
            {"job": job.id, "review_error": err.id, "request_type": "error_dispute", "reason": "Gửi lại"},
            format="json",
        )
        self.assertEqual(dup_err.status_code, 400)

        first_data = self.ann1.post(
            self.f.url("annotator/requests/"),
            {"job": job.id, "request_type": "data_issue", "reason": "Thiếu frame Lidar"},
            format="json",
        )
        self.assertEqual(first_data.status_code, 201)
        dup_data = self.ann1.post(
            self.f.url("annotator/requests/"),
            {"job": job.id, "request_type": "data_issue", "reason": "Thiếu frame Lidar lần 2"},
            format="json",
        )
        self.assertEqual(dup_data.status_code, 400)

        bad_status = self.pm.post(
            self.f.url(f"annotator/requests/{req_id}/resolve/"),
            {"status": "pending_pm"},
            format="json",
        )
        self.assertEqual(bad_status.status_code, 400)

        resolved = self.pm.post(
            self.f.url(f"annotator/requests/{req_id}/resolve/?status=pending_pm"),
            {"status": "resolved", "resolution_note": "Đã xác nhận"},
            format="json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.data)
        self.assertFalse(
            UserNotification.objects.filter(
                recipient_id__in=[self.f.ann1.id, self.f.pm.id, pm2.id],
                job=job,
                category=UserNotification.Category.DISPUTE,
                is_pinned_pending=True,
            ).exists()
        )
        self.assertTrue(ActivityLog.objects.filter(job=job, action="annotator.request_resolve").exists())

        double = self.pm.post(
            self.f.url(f"annotator/requests/{req_id}/resolve/"),
            {"status": "rejected", "resolution_note": "Đổi ý"},
            format="json",
        )
        self.assertEqual(double.status_code, 400)
