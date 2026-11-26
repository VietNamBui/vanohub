from unittest.mock import MagicMock, patch

from django.test import TestCase
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError as DrfValidationError

from accounts.testing import ProjectFixture
from jobs.models import DailyOutputRecord, Job, JobStatus
from projects.models import Batch

from .client import CvatClient, CvatError, CvatNotFoundError
from .schemas import CvatAnnotationsPayload, CvatJobMetaPayload, CvatJobPayload, CvatTaskPayload
from .sync import import_task_jobs, sync_batch


class CvatSchemaContractTests(TestCase):
    """Layer 2: strict Pydantic data contracts at CVAT integration boundaries."""

    def test_rejects_coerced_string_ids_and_invalid_frame_bounds(self):
        with self.assertRaises(PydanticValidationError):
            CvatTaskPayload.model_validate({"id": "123", "name": "Task 1"})

        with self.assertRaises(PydanticValidationError):
            CvatJobPayload.model_validate({"id": 0, "stage": "annotation"})

        with self.assertRaises(PydanticValidationError):
            CvatJobPayload.model_validate({"id": 10, "start_frame": 20, "stop_frame": 10})

    def test_valid_job_and_annotations_compute_counts(self):
        job = CvatJobPayload.model_validate({
            "id": 42,
            "stage": "annotation",
            "state": "in progress",
            "start_frame": 10,
            "stop_frame": 19,
            "assignee": {"username": "ann1"},
            "extra_cvat_field": "ignored",
        })
        self.assertEqual(job.resolved_frame_count, 10)
        self.assertEqual(job.assignee.username if job.assignee else None, "ann1")

        ann = CvatAnnotationsPayload.model_validate({"shapes": [{"id": 1}], "tracks": [{"id": 2}, {"id": 3}]})
        self.assertEqual(ann.object_count, 3)

    def test_zero_frame_count_is_not_overridden_by_bounds(self):
        job = CvatJobPayload.model_validate({"id": 43, "frame_count": 0, "start_frame": 0, "stop_frame": 9})
        self.assertEqual(job.resolved_frame_count, 0)

    def test_track_object_frame_expansion_respects_outside_deleted_and_included_frames(self):
        ann = CvatAnnotationsPayload.model_validate({
            "shapes": [
                {"id": 1, "frame": 1, "outside": False},
                {"id": 2, "frame": 2, "outside": True},
                {"id": 3, "frame": 3, "outside": False},
            ],
            "tracks": [
                {
                    "id": 10,
                    "shapes": [
                        {"frame": 0, "outside": False},
                        {"frame": 5, "outside": True},
                        {"frame": 7, "outside": False},
                    ],
                },
            ],
        })
        # Shapes: frame 1 (ok), frame 2 (outside), frame 3 (deleted) => 1
        # Track 10 with stop_frame=9, deleted=[3, 8]:
        #   interval [0..4] minus {3} => 4 frames (0,1,2,4)
        #   interval [7..9] minus {8} => 2 frames (7,9)
        # Total = 1 + 4 + 2 = 7
        self.assertEqual(
            ann.count_object_frames(start_frame=0, stop_frame=9, deleted_frames=[3, 8]),
            7,
        )
        # With included_frames=[0, 1, 7]: shape@1 => 1, track@[0,1,7] => 3 => total 4
        self.assertEqual(
            ann.count_object_frames(start_frame=0, stop_frame=9, deleted_frames=[3], included_frames=[0, 1, 7]),
            4,
        )

    def test_track_expansion_respects_frame_step_and_resolved_stop_frame(self):
        meta = CvatJobMetaPayload.model_validate({
            "size": 5,
            "start_frame": 0,
            "stop_frame": None,
            "frame_filter": "step=2",
            "deleted_frames": [4],
        })
        self.assertEqual(meta.frame_step, 2)
        self.assertEqual(meta.resolved_stop_frame, 8)
        ann = CvatAnnotationsPayload.model_validate({
            "tracks": [{"id": 1, "shapes": [{"frame": 0, "outside": False}]}],
        })
        # Hợp lệ: 0, 2, 6, 8 (bỏ 4) => 4 object-frame (không phải 9!)
        self.assertEqual(
            ann.count_object_frames(
                start_frame=meta.start_frame,
                stop_frame=meta.resolved_stop_frame,
                frame_step=meta.frame_step,
                deleted_frames=meta.deleted_frames,
            ),
            4,
        )


class CvatClientSecurityAndApiTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()

    def test_client_blocks_redirects_and_filters_annotation_jobs_only(self):
        client = CvatClient(base_url="http://cvat.local", token="secret", organization="my-org")
        self.assertEqual(client.session.headers["X-Organization"], "my-org")

        redirect_resp = MagicMock(status_code=302, ok=False)
        with patch.object(client.session, "get", return_value=redirect_resp) as mock_get:
            with self.assertRaises(CvatError):
                client._get("server/about")
            self.assertFalse(mock_get.call_args.kwargs["allow_redirects"])

        not_found_resp = MagicMock(status_code=404, ok=False)
        with patch.object(client.session, "get", return_value=not_found_resp), self.assertRaises(CvatNotFoundError):
            client._get("tasks/999")

        jobs_resp = MagicMock(status_code=200, ok=True)
        jobs_resp.json.return_value = {"results": [], "next": None}
        with patch.object(client.session, "get", return_value=jobs_resp) as mock_get:
            client.list_task_jobs(15)
            self.assertEqual(mock_get.call_args.kwargs["params"]["type"], "annotation")

    def test_cvat_tasks_endpoint_restricted_to_pm(self):
        ann = self.f.client(self.f.ann1)
        qc1 = self.f.client(self.f.qc1)
        qc2 = self.f.client(self.f.qc2)
        self.assertEqual(ann.get("/api/cvat/tasks/").status_code, 403)
        self.assertEqual(qc1.get("/api/cvat/tasks/").status_code, 403)
        self.assertEqual(qc2.get("/api/cvat/tasks/").status_code, 403)


class CvatSyncValidationTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()

    def test_import_task_jobs_rejects_malformed_cvat_payload(self):
        class BadClient:
            def get_task(self, task_id):
                return {"id": "not-an-int", "name": "Bad"}

            def list_task_jobs(self, task_id):
                return []

        with self.assertRaises(CvatError):
            import_task_jobs(self.f.batch, 100, self.f.pm, client=BadClient())

    def test_import_and_sync_valid_cvat_payload(self):
        ann_username = self.f.ann1.username

        class GoodClient:
            def get_task(self, task_id):
                return {"id": task_id, "name": "Road Batch 1"}

            def list_task_jobs(self, task_id):
                return [
                    {
                        "id": 501,
                        "stage": "annotation",
                        "state": "in progress",
                        "start_frame": 0,
                        "stop_frame": 9,
                        "assignee": {"username": ann_username},
                    }
                ]

            def count_job_objects(self, job_id):
                return 7

        client = GoodClient()
        res = import_task_jobs(self.f.batch, 100, self.f.pm, client=client)
        self.assertEqual(res, {"task_name": "Road Batch 1", "created": 1, "updated": 0, "total": 1})

        sync_res = sync_batch(self.f.batch, self.f.pm, client=client, count_objects=True)
        self.assertEqual(sync_res, {"updated": 1, "total": 1})

    def test_import_filters_non_annotation_jobs_never_bypasses_confirm_qc2_and_validates_project(self):
        self.f.project.cvat_project_id = 77
        self.f.project.save(update_fields=["cvat_project_id"])

        class MismatchClient:
            def get_task(self, task_id):
                return {"id": task_id, "name": "Wrong Proj", "project_id": 88}

            def list_task_jobs(self, task_id):
                return []

        with self.assertRaises(DrfValidationError):
            import_task_jobs(self.f.batch, 200, self.f.pm, client=MismatchClient())

        class MixedJobsClient:
            def get_task(self, task_id):
                return {"id": task_id, "name": "Mixed Task", "project_id": 77}

            def list_task_jobs(self, task_id):
                return [
                    {"id": 601, "type": "annotation", "stage": "acceptance", "state": "completed"},
                    {"id": 602, "type": "ground_truth", "stage": "annotation", "state": "new"},
                    {"id": 603, "type": "consensus_replica", "stage": "annotation", "state": "new"},
                    {"id": 604, "type": "annotation", "stage": "validation", "state": "rejected"},
                ]

        res = import_task_jobs(self.f.batch, 201, self.f.pm, client=MixedJobsClient())
        self.assertEqual(res, {"task_name": "Mixed Task", "created": 2, "updated": 0, "total": 2})
        j = Job.objects.get(cvat_job_id=601)
        # acceptance trên CVAT không được bỏ qua bước PM confirm-qc2
        self.assertEqual(j.status, JobStatus.QC1_PASSED)
        j_rej = Job.objects.get(cvat_job_id=604)
        self.assertEqual((j_rej.status, j_rej.first_qc1_result, j_rej.total_rework_rounds), (JobStatus.REWORK, "reject", 1))
        self.assertFalse(Job.objects.filter(cvat_job_id__in=[602, 603]).exists())

        # Không được nhập trùng cvat_task_id vào batch khác
        other_batch = Batch.objects.create(dataset=self.f.dataset, name="B2")
        with self.assertRaises(DrfValidationError):
            import_task_jobs(other_batch, 201, self.f.pm, client=MixedJobsClient())

    def test_sync_records_pre_qc_daily_output_delta_handles_rejected_and_source_missing(self):
        self.f.batch.cvat_task_id = 300
        self.f.batch.save(update_fields=["cvat_task_id"])
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=701, object_count=0)
        locked = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann2, cvat_job_id=702, is_locked=True)
        missing_job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=703)

        class ProgressClient:
            def __init__(self, count):
                self.count = count

            def list_task_jobs(self, task_id):
                return [
                    {"id": 701, "type": "annotation", "stage": "annotation", "state": "in progress", "frame_count": 20},
                    {"id": 702, "type": "annotation", "stage": "annotation", "state": "completed", "frame_count": 10},
                ]

            def count_job_objects(self, job_id):
                return self.count

        # Đồng bộ lần 1: +30 cuboid trước QC
        sync_batch(self.f.batch, self.f.pm, client=ProgressClient(30), count_objects=True)
        job.refresh_from_db()
        locked.refresh_from_db()
        missing_job.refresh_from_db()
        self.assertEqual(job.object_count, 30)
        self.assertEqual(job.frame_count, 20)
        self.assertEqual(locked.status, JobStatus.ANNOTATING)  # bị khóa nên không đổi trạng thái
        self.assertTrue(missing_job.source_missing)
        self.assertEqual(
            DailyOutputRecord.objects.filter(job=job, user=self.f.ann1, is_rework=False).count(), 1
        )
        self.assertEqual(
            DailyOutputRecord.objects.get(job=job, user=self.f.ann1).object_count, 30
        )

        # Đồng bộ lần 2: tăng lên 45 cuboid → chỉ cộng thêm delta +15
        sync_batch(self.f.batch, self.f.pm, client=ProgressClient(45), count_objects=True)
        total_recorded = sum(
            DailyOutputRecord.objects.filter(job=job, user=self.f.ann1).values_list("object_count", flat=True)
        )
        self.assertEqual(total_recorded, 45)

        # annotation/rejected đưa về REWORK và tăng total_rework_rounds
        class RejectClient:
            def list_task_jobs(self, task_id):
                return [{"id": 701, "type": "annotation", "stage": "annotation", "state": "rejected"}]

        sync_batch(self.f.batch, self.f.pm, client=RejectClient(), count_objects=False)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.REWORK)
        self.assertEqual(job.rework_round, 1)
        self.assertEqual(job.total_rework_rounds, 1)

        # Task biến mất trên CVAT (404) → đánh dấu batch.source_missing=True
        class MissingTaskClient:
            def list_task_jobs(self, task_id):
                raise CvatNotFoundError("404")

        with self.assertRaises(CvatNotFoundError):
            sync_batch(self.f.batch, self.f.pm, client=MissingTaskClient())
        self.f.batch.refresh_from_db()
        self.assertTrue(self.f.batch.source_missing)

    def test_sync_after_submit_without_manual_object_count_credits_daily_output_once(self):
        from datetime import timedelta

        from django.utils import timezone

        self.f.batch.cvat_task_id = 305
        self.f.batch.save(update_fields=["cvat_task_id"])
        submitted_at = timezone.now() - timedelta(days=1)
        job = self.f.job(
            status=JobStatus.QC1_PASSED,
            annotator=self.f.ann1,
            cvat_job_id=750,
            object_count=0,
            submitted_at=submitted_at,
        )

        class PassedCountClient:
            def list_task_jobs(self, task_id):
                return [{"id": 750, "type": "annotation", "stage": "validation", "state": "completed"}]

            def count_job_objects(self, job_id):
                return 65

        sync_batch(self.f.batch, self.f.pm, client=PassedCountClient(), count_objects=True)
        # Đồng bộ lần 2 không được cộng đúp
        sync_batch(self.f.batch, self.f.pm, client=PassedCountClient(), count_objects=True)
        from jobs.models import user_work_date

        records = list(DailyOutputRecord.objects.filter(job=job, user=self.f.ann1))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].object_count, 65)
        self.assertEqual(records[0].work_date, user_work_date(self.f.ann1, at=submitted_at))
