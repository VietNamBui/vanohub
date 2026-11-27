from datetime import timedelta
from typing import Any
from unittest import mock
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError as DrfValidationError

from accounts.models import Role, RoleAssignment, User
from accounts.testing import ProjectFixture
from jobs.models import DailyOutputRecord, Job, JobStatus, user_work_date
from projects.models import ActivityLog, Batch, DataStatus, EscalationPolicy, Project
from quality.models import Audit, AuditSample, ErrorCategory
from quality.qc2 import four_eyes_conflicts

from . import sync
from .assignee import _NOT_MANAGED, current_holder, jobs_held_by, push_assignees
from .client import MAX_PAGES, CvatClient, CvatError, CvatNotFoundError
from .models import CvatAccount
from .schemas import CvatAnnotationsPayload, CvatAssigneePayload, CvatJobMetaPayload, CvatJobPayload, CvatTaskPayload
from .sync import SYNCABLE_STATUSES, import_task_jobs, sync_batch


class CvatSchemaContractTests(TestCase):
    """Layer 4: strict Pydantic data contracts at CVAT integration boundaries."""

    def test_rejects_coerced_string_ids_and_invalid_frame_bounds(self):
        with self.assertRaises(PydanticValidationError):
            CvatTaskPayload.model_validate({"id": "123", "name": "Task 1"})

        with self.assertRaises(PydanticValidationError):
            CvatJobPayload.model_validate({"id": 0, "stage": "annotation"})

        with self.assertRaises(PydanticValidationError):
            CvatJobPayload.model_validate({"id": 10, "start_frame": 20, "stop_frame": 10})

        with self.assertRaises(PydanticValidationError):
            CvatAssigneePayload.model_validate({"username": "missing_id"})

    def test_valid_job_and_annotations_compute_counts_and_normalize_none(self):
        job = CvatJobPayload.model_validate(
            {
                "id": 42,
                "type": None,
                "stage": "annotation",
                "state": "in progress",
                "start_frame": 10,
                "stop_frame": 19,
                "assignee": {"id": 11, "username": None},
                "extra_cvat_field": "ignored",
            }
        )
        self.assertEqual(job.type, "annotation")
        self.assertEqual(job.resolved_frame_count, 10)
        assert job.assignee is not None
        self.assertEqual((job.assignee.id, job.assignee.username), (11, ""))

        ann = CvatAnnotationsPayload.model_validate({"shapes": [{"id": 1}], "tracks": [{"id": 2}, {"id": 3}]})
        self.assertEqual(ann.object_count, 3)

        empty_ann = CvatAnnotationsPayload.model_validate({"shapes": None, "tracks": None})
        self.assertEqual(empty_ann.object_count, 0)

    def test_zero_frame_count_is_not_overridden_by_bounds(self):
        job = CvatJobPayload.model_validate({"id": 43, "frame_count": 0, "start_frame": 0, "stop_frame": 9})
        self.assertEqual(job.resolved_frame_count, 0)

    def test_track_object_frame_expansion_respects_outside_deleted_and_included_frames(self):
        ann = CvatAnnotationsPayload.model_validate(
            {
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
            }
        )
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
        # included_frames=[] (empty list) MUST mean 0 matched frames, NOT all frames!
        self.assertEqual(
            ann.count_object_frames(start_frame=0, stop_frame=9, included_frames=[]),
            0,
        )
        minimal = CvatAnnotationsPayload.model_validate({"shapes": [{"id": 1}], "tracks": [{"id": 2}]})
        self.assertEqual(minimal.count_object_frames(included_frames=[]), 0)

    def test_track_expansion_respects_frame_step_and_resolved_stop_frame(self):
        meta = CvatJobMetaPayload.model_validate(
            {
                "size": 5,
                "start_frame": 0,
                "stop_frame": None,
                "frame_filter": "step=2",
                "deleted_frames": [4],
            }
        )
        self.assertEqual(meta.frame_step, 2)
        self.assertEqual(meta.resolved_stop_frame, 8)
        ann = CvatAnnotationsPayload.model_validate(
            {
                "tracks": [{"id": 1, "shapes": [{"frame": 0, "outside": False}]}],
            }
        )
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

        # included_frames overrides size-based resolved_stop_frame when stop_frame is None
        meta_inc = CvatJobMetaPayload.model_validate(
            {
                "size": 2,
                "start_frame": 0,
                "stop_frame": None,
                "frame_filter": None,
                "deleted_frames": None,
                "included_frames": [10, 25],
            }
        )
        self.assertEqual(meta_inc.resolved_stop_frame, 25)
        self.assertEqual(meta_inc.deleted_frames, [])
        self.assertEqual(meta_inc.frame_filter, "")


class CvatClientSecurityAndApiTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()

    @override_settings(CVAT_HOST_HEADER="cvat.internal:8080")
    def test_client_blocks_redirects_404_bad_json_pagination_and_filters_annotation_jobs(self):
        client = CvatClient(base_url="http://cvat.local", token="secret", organization="my-org")
        self.assertEqual(client.session.headers["X-Organization"], "my-org")
        self.assertEqual(client.session.headers["Host"], "cvat.internal:8080")

        # No global CVAT_ORGANIZATION fallback when organization=None
        client_no_org = CvatClient(base_url="http://cvat.local", token="secret")
        self.assertNotIn("X-Organization", client_no_org.session.headers)

        redirect_resp = MagicMock(status_code=302, ok=False)
        with patch.object(client.session, "request", return_value=redirect_resp) as mock_req:
            with self.assertRaises(CvatError):
                client._get("server/about")
            self.assertFalse(mock_req.call_args.kwargs["allow_redirects"])

        not_found_resp = MagicMock(status_code=404, ok=False)
        with patch.object(client.session, "request", return_value=not_found_resp), self.assertRaises(CvatNotFoundError):
            client._get("tasks/999")

        bad_json_resp = MagicMock(status_code=200, ok=True, content=b"<html>not json</html>")
        bad_json_resp.json.side_effect = ValueError("Expecting value")
        with patch.object(client.session, "request", return_value=bad_json_resp), self.assertRaises(CvatError):
            client._get("server/about")

        infinite_page = MagicMock(status_code=200, ok=True, content=b'{"results": [], "next": "http://next"}')
        infinite_page.json.return_value = {"results": [], "next": "http://next"}
        with patch.object(client.session, "request", return_value=infinite_page) as mock_req:
            with self.assertRaises(CvatError):
                client._get_all("tasks")
            self.assertEqual(mock_req.call_count, MAX_PAGES)

        jobs_resp = MagicMock(status_code=200, ok=True, content=b'{"results": [], "next": null}')
        jobs_resp.json.return_value = {"results": [], "next": None}
        with patch.object(client.session, "request", return_value=jobs_resp) as mock_req:
            client.list_task_jobs(15)
            self.assertEqual(mock_req.call_args.kwargs["params"]["type"], "annotation")

    def test_status_endpoint_sanitizes_internal_error_details(self):
        with patch(
            "cvat_integration.views.CvatClient.about",
            side_effect=CvatError("Không kết nối được CVAT tại http://10.99.0.5:8080: secret-token-leak"),
        ):
            res = self.f.client(self.f.ann1).get("/api/cvat/status/")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data["connected"])
        self.assertNotIn("10.99.0.5", res.data["detail"])
        self.assertNotIn("secret-token-leak", res.data["detail"])

    def test_client_rejects_invalid_and_unsafe_urls_before_creating_session(self):
        invalid_urls = [
            ("ftp://cvat.test", "http(s)://<host>"),
            ("file:///etc/passwd", "http(s)://<host>"),
            ("cvat.test", "http(s)://<host>"),
            ("http://", "http(s)://<host>"),
            ("http://user:pass@cvat.test", "thông tin đăng nhập"),
            ("http://cvat.test?x=1", "query string"),
            ("http://cvat.test#frag", "fragment"),
            ("http://cvat.test?", "query string"),
            ("http://cvat.test#", "fragment"),
            ("http://cvat.test:notaport", "http(s)://<host>"),
            ("http://[invalid", "http(s)://<host>"),
        ]
        with patch("cvat_integration.client.requests.Session") as mock_session:
            for bad_url, expected_text in invalid_urls:
                with self.subTest(base_url=bad_url), self.assertRaises(CvatError) as ctx:
                    CvatClient(base_url=bad_url, token="secret")
                self.assertIn(expected_text, str(ctx.exception))
            mock_session.assert_not_called()

    @override_settings(CVAT_REQUIRE_HTTPS=True)
    def test_client_enforces_https_when_cvat_require_https_is_true(self):
        with (
            patch("cvat_integration.client.requests.Session") as mock_session,
            self.assertRaises(CvatError) as ctx,
        ):
            CvatClient(base_url="http://cvat.test", token="secret")
        self.assertIn("https://", str(ctx.exception))
        mock_session.assert_not_called()

        client = CvatClient(base_url="https://cvat.test/", token="secret")
        self.assertEqual(client.base_url, "https://cvat.test")

    def test_client_allows_http_when_cvat_require_https_defaults_to_false(self):
        self.assertFalse(settings.CVAT_REQUIRE_HTTPS)
        for url in ("http://localhost:8080", "http://cvat.test"):
            with self.subTest(base_url=url):
                client = CvatClient(base_url=url, token="secret")
                self.assertEqual(client.base_url, url)


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
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="cvat_ann1")

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
                        "assignee": {"id": 11, "username": "cvat_ann1"},
                    }
                ]

            def count_job_objects(self, job_id):
                return 7

        client = GoodClient()
        res = import_task_jobs(self.f.batch, 100, self.f.pm, client=client)
        self.assertEqual(res, {"task_name": "Road Batch 1", "created": 1, "updated": 0, "total": 1})
        j = Job.objects.get(cvat_job_id=501)
        self.assertEqual(j.annotator, self.f.ann1)

        sync_res = sync_batch(self.f.batch, self.f.pm, client=client, count_objects=True)
        self.assertEqual(sync_res, {"updated": 1, "total": 1})

    def test_import_filters_non_annotation_jobs_never_bypasses_confirm_qc2_and_validates_dataset_project(self):
        self.f.dataset.cvat_project_id = 77
        self.f.dataset.save(update_fields=["cvat_project_id"])

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
        # Hybrid A2: acceptance trên CVAT khi batch chưa confirm-qc2 bị chặn ở QC1_PASSED (0 AuditSample)
        self.assertEqual(j.status, JobStatus.QC1_PASSED)
        self.assertEqual(j.audit_samples.count(), 0)
        j_rej = Job.objects.get(cvat_job_id=604)
        self.assertEqual((j_rej.status, j_rej.first_qc1_result, j_rej.total_rework_rounds), (JobStatus.REWORK, "reject", 1))
        self.assertFalse(Job.objects.filter(cvat_job_id__in=[602, 603]).exists())

        # Không được nhập trùng cvat_task_id vào batch khác
        other_batch = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="B2")
        with self.assertRaises(DrfValidationError):
            import_task_jobs(other_batch, 201, self.f.pm, client=MixedJobsClient())

    def test_sync_records_pre_qc_daily_output_delta_handles_rejected_and_source_missing(self):
        self.f.batch.cvat_task_id = 300
        self.f.batch.save(update_fields=["cvat_task_id"])
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=701, object_count=0)
        locked = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann2, cvat_job_id=702, is_locked=True)
        missing_job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=703)

        class ProgressClient:
            def __init__(self, count: int):
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
        self.assertEqual(job.last_counted_objects, 30)
        self.assertEqual(job.round_credited_objects, 30)
        self.assertEqual(job.frame_count, 20)
        self.assertEqual(locked.status, JobStatus.ANNOTATING)  # bị khóa nên không đổi trạng thái
        self.assertTrue(missing_job.source_missing)
        self.assertEqual(
            DailyOutputRecord.objects.filter(job=job, user=self.f.ann1, is_rework=False).count(),
            1,
        )
        self.assertEqual(DailyOutputRecord.objects.get(job=job, user=self.f.ann1).object_count, 30)

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
        self.assertEqual(self.f.batch.last_sync_status, Batch.SyncStatus.ERROR)

    def test_sync_after_submit_without_manual_object_count_credits_daily_output_once(self):
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

        records = list(DailyOutputRecord.objects.filter(job=job, user=self.f.ann1))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].object_count, 65)
        self.assertEqual(records[0].work_date, user_work_date(self.f.ann1, at=submitted_at))


class FakeCvatClient:
    """Thay CvatClient thật: ghi lại các lần đặt assignee, trả user CVAT theo token."""

    users = {"tok-ann1": {"id": 11, "username": "cvat_ann1"}, "tok-other": {"id": 99, "username": "cvat_other"}}
    pushed: list[tuple[int, int | None]] = []

    def __init__(self, token: str | None = None, **kwargs: Any):
        self.token = token

    def get_self(self):
        if self.token not in self.users:
            raise CvatError("CVAT từ chối xác thực. Kiểm tra tài khoản/token CVAT.")
        return self.users[self.token]

    def set_job_assignee(self, job_id: int, cvat_user_id: int | None):
        FakeCvatClient.pushed.append((job_id, cvat_user_id))


@mock.patch("cvat_integration.assignee.CvatClient", FakeCvatClient)
@mock.patch("cvat_integration.views.CvatClient", FakeCvatClient)
class CvatLinkTests(TestCase):
    client: Any

    def setUp(self):
        FakeCvatClient.pushed = []
        self.f = ProjectFixture()
        self.client = self.f.client(self.f.ann1)

    def test_link_with_token_stores_only_id_and_username(self):
        response = self.client.post("/api/cvat/link/", {"token": "tok-ann1"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["linked"])
        account = CvatAccount.objects.get(user=self.f.ann1)
        self.assertEqual((account.cvat_user_id, account.cvat_username), (11, "cvat_ann1"))
        self.assertTrue(ActivityLog.objects.filter(action="cvat.link", actor=self.f.ann1).exists())

    def test_invalid_or_non_string_token_is_rejected(self):
        for bad in ("sai", "", None, ["tok-ann1"], 12345):
            response = self.client.post("/api/cvat/link/", {"token": bad}, format="json")
            self.assertEqual(response.status_code, 400, f"Expected 400 for token={bad!r}")
        self.assertFalse(CvatAccount.objects.exists())

    def test_cvat_account_cannot_be_linked_to_two_people(self):
        CvatAccount.objects.create(user=self.f.ann2, cvat_user_id=11, cvat_username="cvat_ann1")
        response = self.client.post("/api/cvat/link/", {"token": "tok-ann1"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_linking_pushes_jobs_assigned_before_link(self):
        """Giao trên VanoHub khi chưa liên kết → liên kết xong thì đẩy assignee sang CVAT."""
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=500)
        response = self.client.post("/api/cvat/link/", {"token": "tok-ann1"}, format="json")
        self.assertEqual(response.data["sync"], {"pushed": 1, "error": None})
        self.assertEqual(FakeCvatClient.pushed, [(500, 11)])
        job.refresh_from_db()
        self.assertEqual(job.cvat_assignee_id, 11)

    def test_unlink_removes_assignee_on_cvat(self):
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="cvat_ann1")
        self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=501, cvat_assignee_id=11)
        response = self.client.delete("/api/cvat/link/")
        self.assertFalse(response.data["linked"])
        self.assertEqual(FakeCvatClient.pushed, [(501, None)])


@mock.patch("cvat_integration.assignee.CvatClient", FakeCvatClient)
class AssigneePushTests(TestCase):
    def setUp(self):
        FakeCvatClient.pushed = []
        self.f = ProjectFixture()
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="a1")
        CvatAccount.objects.create(user=self.f.qc1, cvat_user_id=33, cvat_username="q1")

    def test_holder_follows_status_and_qc1_passed_is_not_managed(self):
        annotating = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=1)
        in_qc1 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, cvat_job_id=2)
        qc1_passed = self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann1, cvat_job_id=9)
        approved = self.f.job(status=JobStatus.APPROVED, annotator=self.f.ann1, cvat_job_id=3)

        self.assertIs(current_holder(qc1_passed), _NOT_MANAGED)
        self.assertEqual([j.pk for j in jobs_held_by(self.f.qc1)], [in_qc1.pk])

        result = push_assignees([annotating, in_qc1, qc1_passed, approved])
        self.assertEqual(result, {"pushed": 2, "waiting": 0, "warnings": []})
        self.assertEqual(FakeCvatClient.pushed, [(1, 11), (2, 33)])  # QC1_PASSED và APPROVED: không động vào

    def test_unlinked_holder_is_waiting_and_old_assignee_removed(self):
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann2, cvat_job_id=4, cvat_assignee_id=11)
        self.assertEqual(push_assignees([job]), {"pushed": 1, "waiting": 1, "warnings": []})
        self.assertEqual(FakeCvatClient.pushed, [(4, None)])

    def test_unchanged_assignee_is_not_pushed_again(self):
        job = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=5, cvat_assignee_id=11)
        self.assertEqual(push_assignees([job])["pushed"], 0)
        self.assertEqual(FakeCvatClient.pushed, [])

    def test_qc2_sample_holder_is_auditor(self):
        CvatAccount.objects.create(user=self.f.qc2, cvat_user_id=22, cvat_username="q2")
        job = self.f.job(status=JobStatus.PENDING_QC2, cvat_job_id=6)
        audit = Audit.objects.create(
            project=self.f.project,
            batch=self.f.batch,
            method="random",
            sampling_rate=50,
            seed=1,
            eligible_count=1,
            created_by=self.f.pm,
        )
        AuditSample.objects.create(audit=audit, job=job, auditor=self.f.qc2)
        push_assignees([job])
        self.assertEqual(FakeCvatClient.pushed, [(6, 22)])

    def test_pm_assignment_pushes_after_commit(self):
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2, cvat_job_id=7)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.f.client(self.f.pm).post(
                self.f.url(f"jobs/{job.id}/assign/"),
                {"annotator": self.f.ann1.id},
                format="json",
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(FakeCvatClient.pushed, [(7, 11)])

    def test_assignment_succeeds_even_if_cvat_is_down(self):
        job = self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann2, cvat_job_id=8)
        with (
            mock.patch.object(FakeCvatClient, "set_job_assignee", side_effect=CvatError("down")),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.f.client(self.f.pm).post(
                self.f.url(f"jobs/{job.id}/assign/"),
                {"annotator": self.f.ann1.id},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual((job.annotator, job.cvat_assignee_id), (self.f.ann1, None))


class FakeOrgCvat:
    """CVAT giả có organization: user 11 có email (mời được), user 33 không có email."""

    def __init__(self, members=()):
        self.members = list(members)
        self.invited: list[tuple[str, str, str]] = []
        self.pushed: list[tuple[int, int | None]] = []

    def list_memberships(self, org_id):
        return [{"user": {"id": uid}, "is_active": True} for uid in self.members]

    def get_user(self, user_id):
        return {
            11: {"id": 11, "username": "a1", "email": "a1@example.com"},
            33: {"id": 33, "username": "q1", "email": ""},
        }[user_id]

    def invite_to_org(self, org_slug, email, role="worker"):
        self.invited.append((org_slug, email, role))

    def set_job_assignee(self, job_id, cvat_user_id):
        self.pushed.append((job_id, cvat_user_id))


class AutoOrgMembershipTests(TestCase):
    """Giao job cho người chưa là thành viên CVAT organization → tự mời (worker) để họ thấy job."""

    def setUp(self):
        self.f = ProjectFixture()
        self.f.project.cvat_org_id, self.f.project.cvat_org_slug = 7, "acme"
        self.f.project.save()
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="a1")
        CvatAccount.objects.create(user=self.f.qc1, cvat_user_id=33, cvat_username="q1")

    def test_non_member_is_invited_once_then_assigned(self):
        client = FakeOrgCvat()
        jobs = [self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=n) for n in (1, 2)]
        result = push_assignees(jobs, client)
        self.assertEqual(client.invited, [("acme", "a1@example.com", "worker")])  # mời một lần cho cả hai job
        self.assertEqual(client.pushed, [(1, 11), (2, 11)])
        self.assertEqual(result["warnings"], [])

    def test_existing_member_is_not_invited(self):
        client = FakeOrgCvat(members=[11])
        push_assignees([self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=3)], client)
        self.assertEqual(client.invited, [])

    def test_user_without_email_still_gets_job_with_warning(self):
        client = FakeOrgCvat()
        result = push_assignees([self.f.job(status=JobStatus.PENDING_QC1, cvat_job_id=4)], client)
        self.assertEqual(client.pushed, [(4, 33)])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("chưa có email", result["warnings"][0])


class _FakeSyncClient:
    """CVAT client giả phục vụ kiểm thử sync workflow & kiểm tra không gọi HTTP trong transaction."""

    def __init__(
        self,
        jobs: list[dict[str, Any]],
        *,
        orgs: list[dict[str, Any]] | None = None,
        memberships: dict[int, list[dict[str, Any]]] | None = None,
        tasks: list[dict[str, Any]] | None = None,
        jobs_by_task: dict[int, list[dict[str, Any]]] | None = None,
        missing_task_ids: set[int] | None = None,
        missing_count_job_ids: set[int] | None = None,
        counts_by_job: dict[int, int] | None = None,
        expected_atomic_depth: int | None = None,
    ):
        self.jobs = jobs
        self.orgs = orgs or []
        self.memberships = memberships or {}
        self.tasks = tasks if tasks is not None else [{"id": 5, "name": "Synced Task"}]
        self.jobs_by_task = jobs_by_task
        self.missing_task_ids = missing_task_ids or set()
        self.missing_count_job_ids = missing_count_job_ids or set()
        self.counts_by_job = counts_by_job or {}
        self.expected_atomic_depth = expected_atomic_depth
        self.pushed: list[tuple[int, int | None]] = []
        self.http_calls: list[str] = []

    def _check_not_in_nested_atomic(self, label: str) -> None:
        self.http_calls.append(label)
        if self.expected_atomic_depth is not None:
            assert len(connection.atomic_blocks) == self.expected_atomic_depth, (
                f"CVAT HTTP call {label} ran inside nested transaction.atomic()"
            )

    def list_organizations(self):
        self._check_not_in_nested_atomic("list_organizations")
        return self.orgs

    def list_memberships(self, org_id):
        self._check_not_in_nested_atomic("list_memberships")
        return self.memberships.get(org_id, [])

    def list_org_projects(self, org_id):
        self._check_not_in_nested_atomic("list_org_projects")
        return [{"id": 900, "name": "Synced Project"}]

    def list_project_tasks(self, project_id):
        self._check_not_in_nested_atomic("list_project_tasks")
        return self.tasks

    def list_task_jobs(self, task_id):
        self._check_not_in_nested_atomic("list_task_jobs")
        if task_id in self.missing_task_ids:
            raise CvatNotFoundError(f"Task {task_id} not found")
        if self.jobs_by_task is not None:
            return self.jobs_by_task.get(task_id, [])
        return self.jobs

    def count_job_objects(self, job_id):
        self._check_not_in_nested_atomic("count_job_objects")
        if job_id in self.missing_count_job_ids:
            raise CvatNotFoundError(f"Job {job_id} not found")
        return self.counts_by_job.get(job_id, 12)

    def set_job_assignee(self, job_id, cvat_user_id):
        self._check_not_in_nested_atomic("set_job_assignee")
        self.pushed.append((job_id, cvat_user_id))


class CvatSyncWorkflowSafetyTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()
        self.f.project.cvat_org_id = 7
        self.f.project.cvat_org_slug = "acme"
        self.f.project.save()
        self.f.dataset.cvat_project_id = 900
        self.f.dataset.save()
        self.f.batch.cvat_task_id = 5
        self.f.batch.save()

    def test_qc1_passed_is_excluded_from_syncable_statuses_and_never_rolled_back(self):
        self.assertNotIn(JobStatus.QC1_PASSED, SYNCABLE_STATUSES)
        job = self.f.job(status=JobStatus.QC1_PASSED, cvat_job_id=400)
        client = _FakeSyncClient([{"id": 400, "stage": "annotation", "state": "in progress"}])
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QC1_PASSED)

    def test_hybrid_a2_gate_respects_batch_qc2_confirmed_at(self):
        # Batch chưa confirm-qc2 → post-QC1 từ CVAT chặn ở QC1_PASSED và KHÔNG tạo AuditSample
        existing_unconfirmed = self.f.job(status=JobStatus.QC1_REVIEWING, cvat_job_id=405)
        client_unconfirmed = _FakeSyncClient(
            [
                {"id": 405, "stage": "validation", "state": "completed"},
                {"id": 406, "stage": "acceptance", "state": "completed", "start_frame": 0, "stop_frame": 9},
            ]
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client_unconfirmed)
        existing_unconfirmed.refresh_from_db()
        new_unconfirmed = Job.objects.get(cvat_job_id=406)
        self.assertEqual(existing_unconfirmed.status, JobStatus.QC1_PASSED)
        self.assertEqual(new_unconfirmed.status, JobStatus.QC1_PASSED)
        self.assertEqual(existing_unconfirmed.audit_samples.count(), 0)
        self.assertEqual(new_unconfirmed.audit_samples.count(), 0)

        # Batch ĐÃ confirm-qc2 → post-QC1 từ CVAT được phép vào PENDING_QC2 và tạo AuditSample
        self.f.batch.qc2_confirmed_by = self.f.pm
        self.f.batch.qc2_confirmed_at = timezone.now()
        self.f.batch.save(update_fields=["qc2_confirmed_by", "qc2_confirmed_at"])
        existing_confirmed = self.f.job(status=JobStatus.QC1_REVIEWING, cvat_job_id=407, frame_count=10)
        client_confirmed = _FakeSyncClient(
            [
                {"id": 405, "stage": "validation", "state": "completed"},
                {"id": 406, "stage": "acceptance", "state": "completed", "start_frame": 0, "stop_frame": 9},
                {"id": 407, "stage": "validation", "state": "completed", "frame_count": 10},
                {"id": 408, "stage": "acceptance", "state": "completed", "start_frame": 10, "stop_frame": 19},
            ]
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client_confirmed)
        existing_confirmed.refresh_from_db()
        new_confirmed = Job.objects.get(cvat_job_id=408)
        self.assertEqual(existing_confirmed.status, JobStatus.PENDING_QC2)
        self.assertEqual(new_confirmed.status, JobStatus.PENDING_QC2)
        self.assertEqual(existing_confirmed.audit_samples.count(), 1)
        self.assertEqual(new_confirmed.audit_samples.count(), 1)

    def test_sync_activity_log_never_poisons_four_eyes_with_pm_actor(self):
        # Unassigned job moving to PENDING_QC1 via PM sync: actor MUST be None (not PM), synced_by=pm.pk
        unassigned = self.f.job(status=JobStatus.ANNOTATING, cvat_job_id=409)
        unassigned.annotator = None
        unassigned.save(update_fields=["annotator"])
        assigned = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=410)
        client = _FakeSyncClient(
            [
                {"id": 409, "stage": "annotation", "state": "completed"},
                {"id": 410, "stage": "annotation", "state": "completed"},
            ]
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client)

        log_unassigned = ActivityLog.objects.filter(job=unassigned, action="job.status").latest("id")
        self.assertIsNone(log_unassigned.actor)
        assert isinstance(log_unassigned.after, dict)
        self.assertEqual(log_unassigned.after.get("synced_by"), self.f.pm.pk)
        self.assertNotIn(self.f.pm.pk, four_eyes_conflicts(unassigned))

        log_assigned = ActivityLog.objects.filter(job=assigned, action="job.status").latest("id")
        self.assertEqual(log_assigned.actor, self.f.ann1)
        assert isinstance(log_assigned.after, dict)
        self.assertEqual(log_assigned.after.get("synced_by"), self.f.pm.pk)
        self.assertNotIn(self.f.pm.pk, four_eyes_conflicts(assigned))

    def test_rework_job_not_teleported_to_pending_qc2(self):
        """P0: Job bị QC2 reject về REWORK không bị CVAT kéo ngược lên PENDING_QC2."""
        job_val = self.f.job(status=JobStatus.REWORK, rework_round=1, cvat_job_id=401)
        job_acc = self.f.job(status=JobStatus.REWORK, rework_round=1, cvat_job_id=402)
        client = _FakeSyncClient(
            [
                {"id": 401, "stage": "validation", "state": "completed"},
                {"id": 402, "stage": "acceptance", "state": "completed"},
            ]
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        job_val.refresh_from_db()
        job_acc.refresh_from_db()
        self.assertEqual((job_val.status, job_val.rework_round), (JobStatus.REWORK, 1))
        self.assertEqual((job_acc.status, job_acc.rework_round), (JobStatus.REWORK, 1))
        self.assertEqual(job_val.audit_samples.count(), 0)
        self.assertEqual(job_acc.audit_samples.count(), 0)

    def test_pending_qc1_and_qc1_reviewing_not_rolled_back_to_annotating(self):
        """P0: Job đang ở PENDING_QC1/QC1_REVIEWING không bị CVAT kéo lùi về ANNOTATING."""
        j_pending = self.f.job(status=JobStatus.PENDING_QC1, cvat_job_id=411)
        j_reviewing = self.f.job(status=JobStatus.QC1_REVIEWING, cvat_job_id=412)
        client = _FakeSyncClient(
            [
                {"id": 411, "stage": "annotation", "state": "in progress"},
                {"id": 412, "stage": "annotation", "state": "in progress"},
            ]
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        j_pending.refresh_from_db()
        j_reviewing.refresh_from_db()
        self.assertEqual(j_pending.status, JobStatus.PENDING_QC1)
        self.assertEqual(j_reviewing.status, JobStatus.QC1_REVIEWING)

    def test_stale_cvat_rejection_does_not_double_increment_rework_round(self):
        """P0: CVAT giữ nguyên ('validation', 'rejected') cũ không được tăng rework_round lần 2."""
        j_rework = self.f.job(
            status=JobStatus.REWORK,
            rework_round=1,
            cvat_job_id=415,
            cvat_stage="validation",
            cvat_state="rejected",
        )
        j_resubmitted = self.f.job(
            status=JobStatus.QC1_REVIEWING,
            rework_round=1,
            cvat_job_id=416,
            cvat_stage="validation",
            cvat_state="rejected",
        )
        client = _FakeSyncClient(
            [
                {"id": 415, "stage": "validation", "state": "rejected"},
                {"id": 416, "stage": "validation", "state": "rejected"},
            ]
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        j_rework.refresh_from_db()
        j_resubmitted.refresh_from_db()
        self.assertEqual((j_rework.status, j_rework.rework_round), (JobStatus.REWORK, 1))
        self.assertEqual((j_resubmitted.status, j_resubmitted.rework_round), (JobStatus.QC1_REVIEWING, 1))

    def test_locked_escalated_policy_and_locked_batch_jobs(self):
        """P0: Job is_locked / is_escalated (BLOCK vs WARN_ONLY) / batch bị khoá."""
        j_locked = self.f.job(status=JobStatus.PENDING_ANNOTATION, is_locked=True, cvat_job_id=421)
        j_escalated = self.f.job(status=JobStatus.ANNOTATING, is_escalated=True, cvat_job_id=422)
        client = _FakeSyncClient(
            [
                {"id": 421, "stage": "annotation", "state": "in progress"},
                {"id": 422, "stage": "annotation", "state": "completed"},
            ]
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        j_locked.refresh_from_db()
        j_escalated.refresh_from_db()
        self.assertEqual(j_locked.status, JobStatus.PENDING_ANNOTATION)
        self.assertEqual(j_escalated.status, JobStatus.ANNOTATING)

        # Đổi sang WARN_ONLY → escalated job ĐƯỢC phép đồng bộ trạng thái (nhưng is_locked vẫn bị chặn)
        self.f.project.escalation_policy = EscalationPolicy.WARN_ONLY
        self.f.project.save(update_fields=["escalation_policy"])
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        j_locked.refresh_from_db()
        j_escalated.refresh_from_db()
        self.assertEqual(j_locked.status, JobStatus.PENDING_ANNOTATION)
        self.assertEqual(j_escalated.status, JobStatus.PENDING_QC1)

        # Khoá batch → job trong batch không đổi trạng thái khi sync
        self.f.batch.status = DataStatus.LOCKED
        self.f.batch.save(update_fields=["status"])
        j_in_locked_batch = self.f.job(status=JobStatus.PENDING_ANNOTATION, cvat_job_id=423)
        sync.sync_organization(
            self.f.project,
            self.f.pm,
            client=_FakeSyncClient([{"id": 423, "stage": "annotation", "state": "in progress"}]),
        )
        j_in_locked_batch.refresh_from_db()
        self.assertEqual(j_in_locked_batch.status, JobStatus.PENDING_ANNOTATION)

    def test_per_task_and_per_job_404_marks_source_missing_without_aborting_org_sync(self):
        task2 = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="T2", cvat_task_id=6)
        j_ok = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=450)
        j_404 = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=451)
        j_absent = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=452)

        client = _FakeSyncClient(
            jobs=[],
            tasks=[{"id": 5, "name": "Synced Task"}, {"id": 6, "name": "Missing Task"}],
            jobs_by_task={
                5: [
                    {"id": 450, "stage": "annotation", "state": "in progress"},
                    {"id": 451, "stage": "annotation", "state": "in progress"},
                ]
            },
            missing_task_ids={6},
            missing_count_job_ids={451},
            counts_by_job={450: 25},
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client, count_objects=True)

        j_ok.refresh_from_db()
        j_404.refresh_from_db()
        j_absent.refresh_from_db()
        self.f.batch.refresh_from_db()
        task2.refresh_from_db()

        self.assertFalse(j_ok.source_missing)
        self.assertEqual(j_ok.object_count, 25)
        self.assertEqual(DailyOutputRecord.objects.get(job=j_ok, user=self.f.ann1).object_count, 25)
        self.assertTrue(j_404.source_missing)
        self.assertTrue(j_absent.source_missing)
        self.assertFalse(self.f.batch.source_missing)
        self.assertEqual(self.f.batch.last_sync_status, Batch.SyncStatus.OK)
        self.assertTrue(task2.source_missing)
        self.assertEqual(task2.last_sync_status, Batch.SyncStatus.ERROR)

    def test_cvat_http_calls_run_outside_transaction_atomic(self):
        """P0: Toàn bộ lệnh gọi HTTP tới CVAT chạy ngoài transaction.atomic()."""
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="a1")
        self.f.job(status=JobStatus.PENDING_ANNOTATION, annotator=self.f.ann1, cvat_job_id=430)
        client = _FakeSyncClient(
            [{"id": 430, "stage": "annotation", "state": "in progress"}],
            memberships={7: [{"user": {"id": 11}, "is_active": True}]},
            expected_atomic_depth=len(connection.atomic_blocks),
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client, count_objects=True)
        self.assertIn("list_org_projects", client.http_calls)
        self.assertIn("count_job_objects", client.http_calls)
        self.assertIn("set_job_assignee", client.http_calls)

    def test_new_job_ignores_non_annotator_cvat_assignee(self):
        CvatAccount.objects.create(user=self.f.pm, cvat_user_id=50, cvat_username="pm_cvat")
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="ann_cvat")
        client = _FakeSyncClient(
            [
                {"id": 440, "stage": "annotation", "state": "in progress", "assignee": {"id": 50}},
                {"id": 441, "stage": "annotation", "state": "in progress", "assignee": {"id": 11}},
            ]
        )
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        self.assertIsNone(Job.objects.get(cvat_job_id=440).annotator)
        self.assertEqual(Job.objects.get(cvat_job_id=441).annotator, self.f.ann1)

    def test_sync_organizations_seeds_default_error_categories_for_existing_org(self):
        CvatAccount.objects.create(user=self.f.pm, cvat_user_id=50, cvat_username="pm_cvat")
        ErrorCategory.objects.filter(project=self.f.project).delete()
        self.assertEqual(ErrorCategory.objects.filter(project=self.f.project).count(), 0)
        client = _FakeSyncClient(
            jobs=[],
            orgs=[{"id": 7, "slug": "acme", "name": self.f.project.name}],
            memberships={7: [{"user": {"id": 50}, "role": "owner", "is_active": True}]},
        )
        sync.sync_organizations(actor=self.f.pm, client=client)
        self.assertGreater(ErrorCategory.objects.filter(project=self.f.project).count(), 0)


class JobsHeldByAndSyncOrgsRbacTests(TestCase):
    def setUp(self):
        self.f = ProjectFixture()

    def test_jobs_held_by_excludes_rejected_prior_qc2_samples_and_qc1_passed(self):
        """P1: Auditor có mẫu QC2 đã reject và QC1 có job đã QC1_PASSED đều không còn giữ job."""
        other_qc2 = User.objects.create_user("qc2_new", password="pw")
        RoleAssignment.objects.create(user=other_qc2, role=Role.QC2, project=self.f.project)
        CvatAccount.objects.create(user=self.f.qc2, cvat_user_id=22, cvat_username="q2_old")
        CvatAccount.objects.create(user=other_qc2, cvat_user_id=23, cvat_username="q2_new")

        self.f.job(status=JobStatus.QC1_PASSED, cvat_job_id=600)
        self.assertEqual(list(jobs_held_by(self.f.qc1)), [])

        job = self.f.job(status=JobStatus.PENDING_QC2, cvat_job_id=601)
        audit = Audit.objects.create(
            project=self.f.project,
            batch=self.f.batch,
            method="random",
            sampling_rate=50,
            seed=1,
            eligible_count=1,
            created_by=self.f.pm,
        )
        AuditSample.objects.create(audit=audit, job=job, auditor=self.f.qc2, result=AuditSample.Result.REJECT)
        AuditSample.objects.create(audit=audit, job=job, auditor=other_qc2, result=AuditSample.Result.PENDING)

        self.assertEqual(list(jobs_held_by(self.f.qc2)), [])
        held = list(jobs_held_by(other_qc2))
        self.assertEqual([j.pk for j in held], [job.pk])
        self.assertTrue(hasattr(held[0], "_pending_samples"))

    @mock.patch("cvat_integration.views.sync_organizations")
    def test_sync_organizations_view_blocks_outsider_and_annotator(self, mock_sync):
        outsider = User.objects.create_user("outsider", password="pw")
        for user in (outsider, self.f.ann1, self.f.qc1, self.f.qc2):
            res = self.f.client(user).post("/api/cvat/sync-organizations/", {}, format="json")
            self.assertEqual(res.status_code, 403, f"Expected 403 for {user.username}")
        mock_sync.assert_not_called()

    @mock.patch("cvat_integration.views.sync_organizations")
    def test_sync_organizations_view_filters_result_for_pm_and_shows_all_for_superuser(self, mock_sync):
        other = Project.objects.create(name="Secret Org")
        mock_sync.return_value = {
            "created": [self.f.project.name, other.name],
            "updated": [other.name],
            "pm_added": [
                {"organization": self.f.project.name, "user": self.f.pm.username},
                {"organization": other.name, "user": "other_pm"},
            ],
            "members_added": [
                {"organization": self.f.project.name, "user": self.f.ann1.username},
                {"organization": other.name, "user": "other_ann"},
            ],
            "waiting": [{"cvat_org_id": 99, "name": "Unlinked Org", "reason": "No PM"}],
        }

        pm_res = self.f.client(self.f.pm).post("/api/cvat/sync-organizations/", {}, format="json")
        self.assertEqual(pm_res.status_code, 200, pm_res.data)
        self.assertEqual(pm_res.data["created"], [self.f.project.name])
        self.assertEqual(pm_res.data["updated"], [])
        self.assertEqual(pm_res.data["pm_added"], [{"organization": self.f.project.name, "user": self.f.pm.username}])
        self.assertEqual(
            pm_res.data["members_added"], [{"organization": self.f.project.name, "user": self.f.ann1.username}]
        )
        self.assertEqual(pm_res.data["waiting"], [])

        admin = User.objects.create_superuser("super_admin", "super@example.com", "pw")
        admin_res = self.f.client(admin).post("/api/cvat/sync-organizations/", {}, format="json")
        self.assertEqual(admin_res.status_code, 200, admin_res.data)
        self.assertEqual(admin_res.data["created"], [self.f.project.name, other.name])
        self.assertEqual(len(admin_res.data["waiting"]), 1)
