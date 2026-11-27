from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from accounts.testing import ProjectFixture, make_user
from projects.models import ActivityLog

from .models import JobStatus


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

    def test_locked_job_cannot_be_reassigned(self):
        self.pm.post(self.f.url(f"jobs/{self.job.id}/lock/"))
        response = self.pm.post(self.f.url(f"jobs/{self.job.id}/assign/"), {"annotator": self.f.ann2.id}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_bulk_deadline_and_overdue_filter(self):
        other = self.f.job(status=JobStatus.PENDING_QC1)
        past = (timezone.now() - timedelta(hours=1)).isoformat()
        body = {"ids": [self.job.id, other.id], "deadline": past}
        self.assertEqual(self.pm.post(self.f.url("jobs/bulk-deadline/"), body, format="json").status_code, 200)
        self.assertEqual(self.pm.get(self.f.url("jobs/?overdue=1")).data["count"], 2)

    def test_resolve_escalation(self):
        self.job.is_escalated, self.job.rework_round = True, 3
        self.job.save()
        response = self.pm.post(self.f.url(f"jobs/{self.job.id}/resolve-escalation/"),
                                {"annotator": self.f.ann2.id}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["is_escalated"])
        self.assertEqual(response.data["rework_round"], 0)

    def test_job_queue_counts_by_stage(self):
        self.f.job(status=JobStatus.PENDING_QC2)
        data = self.pm.get(self.f.url("job-queue/")).data
        stages = {s["stage"]: s["total"] for s in data["stages"]}
        self.assertEqual(stages, {"annotation": 1, "qc1": 0, "qc2": 1})


class JobQc2ColumnTests(TestCase):
    def test_job_list_exposes_open_audit_sample_auditor(self):
        from accounts.testing import ProjectFixture

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
    """Kiểm thử không gian Annotator: phạm vi, chuyển trạng thái nguyên tử, khoá, escalation."""

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
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{self.job_other.id}/start/"), {}, format="json").status_code, 404)

    def test_start_then_submit_updates_status_object_count_and_logs_activity(self):
        # Không được nộp trực tiếp khi chưa bắt đầu
        early = self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/submit/"), {}, format="json")
        self.assertEqual(early.status_code, 400)

        started = self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {"note": "bat dau"}, format="json")
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
        self.assertEqual(len(submitted.data["timeline"]), 2)
        self.assertEqual(submitted.data["timeline"][-1]["action"], "job.status")
        self.assertEqual(submitted.data["timeline"][-1]["after"]["status"], JobStatus.PENDING_QC1)

        # Kiểm tra ProjectOverviewView tự động đếm submitted_in_period
        overview = self.f.client(self.f.pm).get(self.f.url("overview/")).data
        self.assertEqual(overview["metrics"]["submitted_in_period"]["value"], 1)

    def test_negative_object_count_rejected_with_400(self):
        self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json")
        resp = self.ann1.post(
            self.f.url(f"annotator/jobs/{self.job_mine.id}/submit/"),
            {"object_count": -5},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_locked_batch_or_locked_or_escalated_job_blocked(self):
        from projects.models import DataStatus

        # Locked job
        self.job_mine.is_locked = True
        self.job_mine.save(update_fields=["is_locked"])
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json").status_code, 400)

        # Escalated job
        self.job_mine.is_locked = False
        self.job_mine.status = JobStatus.REWORK
        self.job_mine.is_escalated = True
        self.job_mine.save(update_fields=["is_locked", "status", "is_escalated"])
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json").status_code, 400)

        # Locked batch
        self.job_mine.is_escalated = False
        self.job_mine.save(update_fields=["is_escalated"])
        self.f.batch.status = DataStatus.LOCKED
        self.f.batch.save(update_fields=["status"])
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json").status_code, 400)

        # Locked dataset
        self.f.batch.status = DataStatus.ACTIVE
        self.f.batch.save(update_fields=["status"])
        self.f.dataset.status = DataStatus.LOCKED
        self.f.dataset.save(update_fields=["status"])
        self.assertEqual(self.ann1.post(self.f.url(f"annotator/jobs/{self.job_mine.id}/start/"), {}, format="json").status_code, 400)

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
        from .models import Job

        now = timezone.now()
        self.job_mine.deadline = now + timedelta(days=3)
        self.job_mine.save(update_fields=["deadline"])
        # Tạo 2 job chưa phân công trong pool
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

        # WIP limit mặc định = 2, ann1 đang giữ 1 (job_mine) → nhận được pool1 (deadline sớm hơn)
        claimed = self.ann1.post(self.f.url("annotator/jobs/claim/"), {}, format="json")
        self.assertEqual(claimed.status_code, 200, claimed.data)
        self.assertEqual(claimed.data["id"], pool1.id)

        # Đã giữ 2/2 → bị chặn WIP limit
        blocked = self.ann1.post(self.f.url("annotator/jobs/claim/"), {}, format="json")
        self.assertEqual(blocked.status_code, 400)

        # Thứ tự ưu tiên: pool1 (sắp hạn 6h) đứng trước job_mine (còn 3 ngày)
        listed = self.ann1.get(self.f.url("annotator/jobs/?tab=active")).data["results"]
        self.assertEqual([r["id"] for r in listed], [pool1.id, self.job_mine.id])
        self.assertTrue(Job.objects.filter(pk=pool2.id, annotator__isnull=True).exists())

    def test_annotator_requests_dispute_data_issue_and_notifications(self):
        from quality.models import ReviewError, ReviewStage
        from teams.models import Team, TeamMember

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

        # 1. Phản hồi lỗi → định tuyến sang PM
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

        # 2. Báo dữ liệu bị chặn → định tuyến sang PM
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

        # 3. Phạm vi riêng: ann2 không thấy yêu cầu của ann1
        self.assertEqual(len(self.f.client(self.f.ann2).get(self.f.url("annotator/requests/")).data), 0)

        # 4. PM giải quyết yêu cầu
        resolved = self.f.client(self.f.pm).post(
            self.f.url(f"annotator/requests/{r_dispute.data['id']}/resolve/"),
            {"status": "resolved", "resolution_note": "Đã kiểm tra và gỡ lỗi sai ID."},
            format="json",
        )
        self.assertEqual(resolved.status_code, 200, resolved.data)
        self.assertEqual(resolved.data["status"], "resolved")

        # 5. Thông báo hợp nhất & đánh dấu đã đọc
        notifs = self.ann1.get(self.f.url("notifications/"))
        self.assertEqual(notifs.status_code, 200, notifs.data)
        self.assertGreaterEqual(notifs.data["all_count"], 2)
        mark = self.ann1.post(self.f.url("notifications/mark-read/"), {}, format="json")
        self.assertEqual(mark.status_code, 200)

        # 6. Tìm kiếm nhanh (⌘K) chỉ trả về job của chính annotator
        search = self.ann1.get(self.f.url(f"annotator/search/?q={self.job_mine.name}"))
        self.assertEqual(search.status_code, 200)
        self.assertEqual([j["id"] for j in search.data["jobs"]], [self.job_mine.id])
