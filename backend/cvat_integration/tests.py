import io
from datetime import timedelta
from typing import Any
from unittest import mock
from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.core.management import call_command
from django.db import IntegrityError, connection
from django.test import TestCase, override_settings
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError as DrfValidationError

from accounts.models import Role, RoleAssignment, User
from accounts.testing import ProjectFixture
from jobs.models import DailyOutputRecord, Job, JobStatus, user_work_date
from projects.models import ActivityLog, Batch, Dataset, DataStatus, EscalationPolicy, Project
from quality.models import Audit, AuditSample, ErrorCategory
from quality.qc2 import four_eyes_conflicts

from . import sync
from .assignee import current_holder, drain_cvat_outbox, enqueue_assignee_push, jobs_held_by, push_assignees
from .client import MAX_PAGES, CvatClient, CvatError, CvatNotFoundError, _validate_model
from .models import CvatAccount, CvatAssigneeOutbox
from .schemas import CvatAnnotationsPayload, CvatAssigneePayload, CvatJobMetaPayload, CvatJobPayload, CvatTaskPayload
from .sync import SYNCABLE_STATUSES, import_task_jobs, sync_batch
from .views import _filter_sync_result_for_user


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

    def test_client_validation_edge_cases_and_auth_modes(self):
        with (
            override_settings(CVAT_URL="", CVAT_ACCESS_TOKEN="secret"),
            patch("cvat_integration.client.requests.Session") as mock_session,
            self.assertRaises(CvatError),
        ):
            CvatClient(base_url=None)
        mock_session.assert_not_called()

        with override_settings(CVAT_ACCESS_TOKEN="", CVAT_USERNAME="", CVAT_PASSWORD=""):
            with self.assertRaises(CvatError):
                CvatClient(base_url="http://cvat.test")
            with self.assertRaises(CvatError):
                CvatClient(base_url="http://cvat.test", username="only-user", password="")

        for bad_cred_url in ("http://onlyuser@cvat.test", "http://:onlypass@cvat.test"):
            with (
                patch("cvat_integration.client.requests.Session") as mock_session,
                self.assertRaises(CvatError) as ctx,
            ):
                CvatClient(base_url=bad_cred_url, token="secret")
            self.assertIn("thông tin đăng nhập", str(ctx.exception))
            mock_session.assert_not_called()

        basic_client = CvatClient(base_url="http://cvat.test///", username="svc", password="pw")
        self.assertEqual(basic_client.base_url, "http://cvat.test")
        self.assertEqual(basic_client.session.auth, ("svc", "pw"))
        self.assertNotIn("Authorization", basic_client.session.headers)

        ipv6_client = CvatClient(base_url="http://[::1]:8080/", token="secret")
        self.assertEqual(ipv6_client.base_url, "http://[::1]:8080")

        with (
            override_settings(CVAT_REQUIRE_HTTPS=True),
            patch("cvat_integration.client.requests.Session") as mock_session,
            self.assertRaises(CvatError),
        ):
            CvatClient(base_url="http://localhost:8080", token="secret")
        mock_session.assert_not_called()

    def test_client_request_error_mapping_empty_body_multipage_and_writes(self):
        client = CvatClient(base_url="http://cvat.local", token="secret")

        with (
            patch.object(client.session, "request", side_effect=requests.ConnectionError("refused")),
            self.assertRaises(CvatError),
        ):
            client._get("server/about")

        for status in (401, 403, 502):
            err_resp = MagicMock(status_code=status, ok=False, content=b"{}")
            with patch.object(client.session, "request", return_value=err_resp), self.assertRaises(CvatError):
                client._get("server/about")

        no_content = MagicMock(status_code=204, ok=True, content=b"")
        with patch.object(client.session, "request", return_value=no_content):
            self.assertIsNone(client._request("DELETE", "jobs/1"))

        page1 = MagicMock(status_code=200, ok=True, content=b'{"results": [{"id": 1}], "next": "p2"}')
        page1.json.return_value = {"results": [{"id": 1}], "next": "p2"}
        page2 = MagicMock(status_code=200, ok=True, content=b'{"results": [{"id": 2}], "next": null}')
        page2.json.return_value = {"results": [{"id": 2}], "next": None}
        with patch.object(client.session, "request", side_effect=[page1, page2]):
            self.assertEqual(client._get_all("tasks"), [{"id": 1}, {"id": 2}])

        for bad_page_body in ({"results": "invalid", "next": None}, [{"id": 1}]):
            bad_page = MagicMock(status_code=200, ok=True, content=b"{}")
            bad_page.json.return_value = bad_page_body
            with patch.object(client.session, "request", return_value=bad_page), self.assertRaises(CvatError):
                client._get_all("tasks")

        ok_post = MagicMock(status_code=201, ok=True, content=b'{"key": "inv"}')
        ok_post.json.return_value = {"key": "inv"}
        with patch.object(client.session, "request", return_value=ok_post) as mock_req:
            client.invite_to_org("acme", "a1@example.com")
            self.assertEqual(mock_req.call_args.args, ("POST", "http://cvat.local/api/invitations"))
            self.assertEqual(mock_req.call_args.kwargs["params"], {"org": "acme"})
            self.assertEqual(mock_req.call_args.kwargs["json"], {"role": "worker", "email": "a1@example.com"})
            self.assertFalse(mock_req.call_args.kwargs["allow_redirects"])

        ok_patch = MagicMock(status_code=200, ok=True, content=b'{"id": 77}')
        ok_patch.json.return_value = {"id": 77}
        with patch.object(client.session, "request", return_value=ok_patch) as mock_req:
            client.set_job_assignee(77, 11)
            self.assertEqual(mock_req.call_args.args, ("PATCH", "http://cvat.local/api/jobs/77"))
            self.assertEqual(mock_req.call_args.kwargs["json"], {"assignee": 11})

    def test_count_job_objects_uses_meta_and_handles_meta_404_explicitly(self):
        client = CvatClient(base_url="http://cvat.local", token="secret")
        ann_with_meta = {"tracks": [{"id": 1, "shapes": [{"frame": 0, "outside": False}]}]}
        meta_payload = {
            "size": 4,
            "start_frame": 0,
            "stop_frame": None,
            "frame_filter": "step=2",
            "deleted_frames": [2],
            "included_frames": None,
        }
        with patch.object(client, "_get", side_effect=[ann_with_meta, meta_payload]):
            self.assertEqual(client.count_job_objects(87), 3)

        # Mặc định data/meta 404 phải ném CvatNotFoundError để không bỏ sót frame_step/deleted_frames
        ann_fallback = {"shapes": [{"id": 1, "frame": 5, "outside": False}, {"id": 2, "frame": 9, "outside": False}]}
        with (
            patch.object(client, "_get", side_effect=[ann_fallback, CvatNotFoundError("404")]),
            self.assertRaises(CvatNotFoundError),
        ):
            client.count_job_objects(88, start_frame=4, stop_frame=6)

        with patch.object(client, "_get", side_effect=[ann_fallback, CvatNotFoundError("404")]):
            self.assertEqual(client.count_job_objects(88, start_frame=4, stop_frame=6, allow_missing_meta=True), 1)
        client.close()


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
            status=JobStatus.PENDING_QC1,
            annotator=self.f.ann1,
            cvat_job_id=750,
            object_count=0,
            submitted_at=submitted_at,
        )

        class PassedCountClient:
            def list_task_jobs(self, task_id):
                return [{"id": 750, "type": "annotation", "stage": "annotation", "state": "completed"}]

            def count_job_objects(self, job_id):
                return 65

        sync_batch(self.f.batch, self.f.pm, client=PassedCountClient(), count_objects=True)
        # Đồng bộ lần 2 không được cộng đúp
        sync_batch(self.f.batch, self.f.pm, client=PassedCountClient(), count_objects=True)

        records = list(DailyOutputRecord.objects.filter(job=job, user=self.f.ann1))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].object_count, 65)
        self.assertEqual(records[0].work_date, user_work_date(self.f.ann1, at=submitted_at))

        # Sau QC1 (QC1_PASSED / PENDING_QC2 / APPROVED / DELIVERED): dù submitted_at != None cũng KHÔNG đổi object_count hay cộng thêm sản lượng
        for frozen_status, cvat_id in (
            (JobStatus.QC1_PASSED, 751),
            (JobStatus.PENDING_QC2, 752),
            (JobStatus.APPROVED, 753),
            (JobStatus.DELIVERED, 754),
        ):
            frozen_job = self.f.job(
                status=frozen_status,
                annotator=self.f.ann1,
                cvat_job_id=cvat_id,
                object_count=10,
                last_counted_objects=10,
                submitted_at=submitted_at,
            )

            class FrozenClient:
                def list_task_jobs(self, task_id, jid=cvat_id):
                    return [{"id": jid, "type": "annotation", "stage": "validation", "state": "completed"}]

                def count_job_objects(self, job_id):
                    return 99

            sync_batch(self.f.batch, self.f.pm, client=FrozenClient(), count_objects=True)
            frozen_job.refresh_from_db()
            self.assertEqual(frozen_job.object_count, 10)
            self.assertFalse(DailyOutputRecord.objects.filter(job=frozen_job).exists())


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

    def test_holder_follows_status_and_clears_post_stage_assignee(self):
        annotating = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=1)
        in_qc1 = self.f.job(status=JobStatus.PENDING_QC1, annotator=self.f.ann1, cvat_job_id=2)
        qc1_passed_clean = self.f.job(status=JobStatus.QC1_PASSED, annotator=self.f.ann1, cvat_job_id=9)
        qc1_passed_stale = self.f.job(
            status=JobStatus.QC1_PASSED, annotator=self.f.ann1, cvat_job_id=10, cvat_assignee_id=33
        )
        approved_stale = self.f.job(
            status=JobStatus.APPROVED, annotator=self.f.ann1, cvat_job_id=3, cvat_assignee_id=22
        )

        self.assertIsNone(current_holder(qc1_passed_clean))
        self.assertIsNone(current_holder(approved_stale))
        self.assertEqual([j.pk for j in jobs_held_by(self.f.qc1)], [in_qc1.pk])

        result = push_assignees([annotating, in_qc1, qc1_passed_clean, qc1_passed_stale, approved_stale])
        self.assertEqual(result, {"pushed": 4, "waiting": 0, "warnings": []})
        self.assertEqual(FakeCvatClient.pushed, [(1, 11), (2, 33), (10, None), (3, None)])
        qc1_passed_stale.refresh_from_db()
        approved_stale.refresh_from_db()
        self.assertIsNone(qc1_passed_stale.cvat_assignee_id)
        self.assertIsNone(approved_stale.cvat_assignee_id)

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

    def test_pending_invitation_invite_failure_and_unlinked_org_project(self):
        class PendingMembershipCvat(FakeOrgCvat):
            def list_memberships(self, org_id):
                return [{"user": {"id": 11}, "is_active": False}]

        pending_client = PendingMembershipCvat()
        job_pending = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=10)
        res_pending = push_assignees([job_pending], pending_client)
        self.assertEqual(pending_client.invited, [])
        self.assertEqual(pending_client.pushed, [(10, 11)])
        self.assertEqual(len(res_pending["warnings"]), 1)
        self.assertIn("chưa chấp nhận", res_pending["warnings"][0])

        class FailingInviteCvat(FakeOrgCvat):
            def invite_to_org(self, org_slug, email, role="worker"):
                raise CvatError("smtp down")

        fail_client = FailingInviteCvat()
        job_fail = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=11)
        res_fail = push_assignees([job_fail], fail_client)
        self.assertEqual(fail_client.pushed, [(11, 11)])
        self.assertEqual(len(res_fail["warnings"]), 1)
        self.assertIn("Không tự thêm được vào organization", res_fail["warnings"][0])

        self.f.project.cvat_org_id = None
        self.f.project.cvat_org_slug = ""
        self.f.project.save(update_fields=["cvat_org_id", "cvat_org_slug"])
        no_org_client = FakeOrgCvat()
        with patch.object(no_org_client, "list_memberships") as mock_list:
            res_no_org = push_assignees(
                [self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=12)],
                no_org_client,
            )
            mock_list.assert_not_called()
        self.assertEqual(no_org_client.pushed, [(12, 11)])
        self.assertEqual(res_no_org["warnings"], [])


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
        sync.sync_organization(self.f.project, self.f.pm, client=client_confirmed, cooldown_seconds=0)
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
        sync.sync_organization(self.f.project, self.f.pm, client=client, cooldown_seconds=0)
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
            cooldown_seconds=0,
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
            "created_ids": [self.f.project.id, other.id],
            "updated": [other.name],
            "updated_ids": [other.id],
            "pm_added": [
                {"organization": self.f.project.name, "organization_id": self.f.project.id, "user": self.f.pm.username},
                {"organization": other.name, "organization_id": other.id, "user": "other_pm"},
            ],
            "members_added": [
                {"organization": self.f.project.name, "organization_id": self.f.project.id, "user": self.f.ann1.username},
                {"organization": other.name, "organization_id": other.id, "user": "other_ann"},
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

    def test_sync_organizations_scoped_to_cvat_user_and_filters_duplicate_names_by_id(self):
        foreign_pm = User.objects.create_user("foreign_pm", password="pw")
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="a1")
        CvatAccount.objects.create(user=foreign_pm, cvat_user_id=99, cvat_username="fpm")
        self.f.project.cvat_org_id = 7
        self.f.project.save(update_fields=["cvat_org_id"])

        client = _FakeSyncClient(
            jobs=[],
            orgs=[
                {"id": 7, "slug": "acme", "name": self.f.project.name},
                {"id": 8, "slug": "foreign", "name": "Foreign Org"},
            ],
            memberships={
                7: [{"user": {"id": 11}, "role": "worker", "is_active": True}],
                8: [{"user": {"id": 99}, "role": "owner", "is_active": True}],
            },
        )
        res = sync.sync_organizations(actor=self.f.ann1, client=client, only_cvat_user_id=11)
        self.assertFalse(Project.objects.filter(cvat_org_id=8).exists())
        self.assertEqual(res["created_ids"], [])

        dup = Project.objects.create(name=self.f.project.name, cvat_org_id=88)
        filtered = _filter_sync_result_for_user(
            self.f.pm,
            {
                "created": [self.f.project.name, dup.name],
                "created_ids": [self.f.project.id, dup.id],
                "updated": [],
                "updated_ids": [],
                "pm_added": [
                    {"organization": self.f.project.name, "organization_id": self.f.project.id, "user": "pm"},
                    {"organization": dup.name, "organization_id": dup.id, "user": "other"},
                ],
                "members_added": [],
                "waiting": [{"cvat_org_id": 99}],
            },
        )
        self.assertEqual(filtered["created"], [self.f.project.name])
        self.assertEqual(filtered["pm_added"], [{"organization": self.f.project.name, "user": "pm"}])

    def test_client_hardening_trust_env_crlf_token_and_redacted_validation(self):
        with override_settings(CVAT_URL="http://cvat.test"):
            client = CvatClient(token="secret")
            self.assertFalse(client.session.trust_env)

        with self.assertRaises(CvatError) as crlf_ctx:
            CvatClient(base_url="http://cvat.test", token="abc\r\nX")
        self.assertNotIn("abc", str(crlf_ctx.exception))

        with self.assertRaises(CvatError) as val_ctx:
            _validate_model(CvatTaskPayload, {"id": "bad", "name": "secret-payload"}, "task")
        self.assertNotIn("secret-payload", str(val_ctx.exception))
        self.assertNotIn("bad", str(val_ctx.exception))

    def test_cvat_sync_qc1_completion_records_reviewer_and_event_for_four_eyes(self):
        self.f.project.cvat_org_id = 7
        self.f.project.cvat_org_slug = "acme"
        self.f.project.save()
        self.f.dataset.cvat_project_id = 900
        self.f.dataset.save()
        self.f.batch.cvat_task_id = 5
        self.f.batch.save()
        CvatAccount.objects.create(user=self.f.qc1, cvat_user_id=33, cvat_username="q1")
        job = self.f.job(
            status=JobStatus.QC1_REVIEWING,
            annotator=self.f.ann1,
            qc1_reviewer=None,
            cvat_job_id=777,
        )
        client = _FakeSyncClient([{"id": 777, "stage": "validation", "state": "completed", "assignee": {"id": 33}}])
        sync.sync_organization(self.f.project, self.f.pm, client=client)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.QC1_PASSED)
        self.assertEqual(job.qc1_reviewer, self.f.qc1)
        log = ActivityLog.objects.get(job=job, action="job.status")
        self.assertEqual(log.actor, self.f.qc1)
        self.assertEqual(log.after.get("event"), "qc1.pass")


class Phase1CvatHardeningRegressionTests(TestCase):
    """Kiểm thử hồi quy cho CvatClient DoS/OOM, counting edge cases, freeze guards, outbox và race IntegrityError."""

    def setUp(self) -> None:
        self.f = ProjectFixture()
        self.f.project.cvat_org_id = 7
        self.f.project.cvat_org_slug = "acme"
        self.f.project.save(update_fields=["cvat_org_id", "cvat_org_slug"])
        self.f.dataset.cvat_project_id = 900
        self.f.dataset.save(update_fields=["cvat_project_id"])
        self.f.batch.cvat_task_id = 5
        self.f.batch.save(update_fields=["cvat_task_id"])

    def test_client_host_header_validation_session_close_deadline_and_streaming_limit(self) -> None:
        for bad_host in ("cvat.local\r\nX-Inject: 1", "bad host", "cvat.local/path", "user@cvat.local", "cvat.local:99999"):
            with (
                override_settings(CVAT_HOST_HEADER=bad_host),
                patch("cvat_integration.client.requests.Session") as mock_session,
                self.assertRaises(CvatError),
            ):
                CvatClient(base_url="http://127.0.0.1:8080", token="secret")
            mock_session.assert_not_called()

        with (
            override_settings(CVAT_HOST_HEADER="cvat.internal:8443"),
            self.assertLogs("cvat_integration.client", level="WARNING") as logs,
            CvatClient(base_url="https://10.0.0.5:8443", token="secret") as client,
        ):
            self.assertEqual(client.session.headers["Host"], "cvat.internal:8443")
        self.assertTrue(any("TLS SNI" in msg for msg in logs.output))

        # Session được đóng khi rời context manager
        with patch("cvat_integration.client.requests.Session") as mock_sess_cls:
            sess_inst = mock_sess_cls.return_value
            sess_inst.headers = {}
            with CvatClient(base_url="http://cvat.local", token="secret"):
                pass
            sess_inst.close.assert_called_once()

        # Total deadline across _get_all pagination
        dl_client = CvatClient(base_url="http://cvat.local", token="secret", max_duration_seconds=0.05)
        page_resp = MagicMock(status_code=200, ok=True, content=b'{"results": [{"id": 1}], "next": "p2"}')
        page_resp.json.return_value = {"results": [{"id": 1}], "next": "p2"}
        with (
            patch.object(dl_client.session, "request", return_value=page_resp),
            patch("cvat_integration.client.time.monotonic", side_effect=[0.0, 0.01, 0.10]),
            self.assertRaises(CvatError),
        ):
            dl_client._get_all("tasks")
        dl_client.close()

        # Streaming size limit (Content-Length và streamed requests.Response)
        stream_client = CvatClient(base_url="http://cvat.local", token="secret", max_response_bytes=32)

        too_large_header = requests.Response()
        too_large_header.status_code = 200
        too_large_header.headers["Content-Length"] = "1024"
        too_large_header.raw = io.BytesIO(b"{}")
        with (
            patch.object(stream_client.session, "request", return_value=too_large_header),
            self.assertRaises(CvatError),
        ):
            stream_client._get("jobs/1/annotations")

        too_large_stream = requests.Response()
        too_large_stream.status_code = 200
        too_large_stream._content_consumed = False
        too_large_stream.raw = io.BytesIO(b'{"shapes": [{"id": 1, "padding": "' + b"x" * 64 + b'"}]}')
        with (
            patch.object(stream_client.session, "request", return_value=too_large_stream),
            self.assertRaises(CvatError),
        ):
            stream_client._get("jobs/1/annotations")

        ok_stream = requests.Response()
        ok_stream.status_code = 200
        ok_stream._content_consumed = False
        ok_stream.raw = io.BytesIO(b'{"shapes": []}')
        with patch.object(stream_client.session, "request", return_value=ok_stream):
            self.assertEqual(stream_client._get("jobs/1/annotations"), {"shapes": []})
        stream_client.close()

    def test_meta_stop_frame_precedence_and_no_spurious_plus_one_on_constrained_counts(self) -> None:
        meta = CvatJobMetaPayload.model_validate({"size": 100, "start_frame": 0, "stop_frame": None})
        self.assertEqual(meta.resolve_stop_frame(19), 19)
        self.assertEqual(meta.resolved_stop_frame, 99)

        client = CvatClient(base_url="http://cvat.local", token="secret")
        ann_payload = {
            "shapes": [
                {"id": 1, "frame": 5, "outside": False},
                {"id": 2, "frame": 12, "outside": False},
                {"id": 3, "outside": False},  # thiếu frame → phải là 0 khi có giới hạn job
            ],
            "tracks": [
                {"id": 10, "shapes": [{"frame": 10, "outside": False}]},
                {"id": 11},  # thiếu shapes → phải là 0 khi có giới hạn job
            ],
        }
        task_scoped_meta = {"size": 100, "start_frame": 0, "stop_frame": None, "deleted_frames": []}
        with patch.object(client, "_get", side_effect=[ann_payload, task_scoped_meta]):
            # Segment [10..19]: shape@12 (1) + track 10 bung từ [10..19] (10) = 11 (không tính shape@5 hay +1 rác)
            self.assertEqual(client.count_job_objects(1, start_frame=10, stop_frame=19), 11)
        client.close()

        # included_frames != None cũng không được cộng +1 rác cho shape thiếu frame / track thiếu shapes
        parsed = CvatAnnotationsPayload.model_validate(ann_payload)
        self.assertEqual(parsed.count_object_frames(included_frames=[10, 12]), 3)

    def test_sync_freeze_guards_source_missing_cascade_and_lock_cooldown(self) -> None:
        # 1. Batch LOCKED và Dataset LOCKED: không ghi đè name/dataset, không tạo job mới, không sửa job metadata
        locked_ds = Dataset.objects.create(
            project=self.f.project, name="Frozen DS", cvat_project_id=901, status=DataStatus.LOCKED
        )
        locked_batch = Batch.objects.create(
            project=self.f.project, dataset=self.f.dataset, name="Frozen Batch", cvat_task_id=6, status=DataStatus.LOCKED
        )
        frozen_job = self.f.job(
            batch=locked_batch,
            dataset=self.f.dataset,
            status=JobStatus.ANNOTATING,
            cvat_job_id=801,
            cvat_stage="annotation",
            cvat_state="new",
            frame_count=5,
        )
        locked_flag_job = self.f.job(
            batch=self.f.batch,
            dataset=self.f.dataset,
            status=JobStatus.ANNOTATING,
            cvat_job_id=802,
            is_locked=True,
            cvat_stage="annotation",
            cvat_state="new",
            frame_count=5,
        )
        active_missing_job = self.f.job(
            batch=self.f.batch,
            dataset=self.f.dataset,
            status=JobStatus.ANNOTATING,
            cvat_job_id=803,
        )

        class FreezeClient:
            def list_org_projects(self, org_id):
                return [
                    {"id": 900, "name": "Synced Project"},
                    {"id": 901, "name": "Renamed DS"},
                ]

            def list_project_tasks(self, project_id):
                if project_id == 900:
                    return [{"id": 6, "name": "Renamed Batch"}]  # task 5 biến mất → absent_batches + cascade!
                return [{"id": 7, "name": "Should Not Create Batch In Locked DS"}]

            def list_task_jobs(self, task_id):
                return [
                    {"id": 801, "stage": "validation", "state": "completed", "frame_count": 99},
                    {"id": 804, "stage": "annotation", "state": "new", "frame_count": 10},
                ]

            def set_job_assignee(self, job_id, cvat_user_id):
                pass

        sync.sync_organization(self.f.project, self.f.pm, client=FreezeClient(), cooldown_seconds=0)
        locked_ds.refresh_from_db()
        locked_batch.refresh_from_db()
        frozen_job.refresh_from_db()
        self.f.batch.refresh_from_db()
        active_missing_job.refresh_from_db()
        locked_flag_job.refresh_from_db()

        self.assertEqual(locked_ds.name, "Frozen DS")
        self.assertFalse(Batch.objects.filter(cvat_task_id=7).exists())
        self.assertEqual(locked_batch.name, "Frozen Batch")
        self.assertFalse(Job.objects.filter(cvat_job_id=804).exists())
        self.assertEqual((frozen_job.cvat_stage, frozen_job.frame_count), ("annotation", 5))
        # Task 5 mất trên CVAT → Batch.source_missing=True và lan sang active_missing_job, KHÔNG lan sang locked_flag_job
        self.assertTrue(self.f.batch.source_missing)
        self.assertTrue(active_missing_job.source_missing)
        self.assertFalse(locked_flag_job.source_missing)

        # 2. Advisory lock busy → ValidationError
        with (
            patch("cvat_integration.sync._try_advisory_lock", return_value=False),
            self.assertRaises(DrfValidationError),
        ):
            sync.sync_organization(self.f.project, self.f.pm, client=FreezeClient(), cooldown_seconds=0)

        # 3. Cooldown → POST /api/projects/{id}/cvat-sync/ trả 400 nếu vừa mới đồng bộ
        with override_settings(CVAT_SYNC_COOLDOWN_SECONDS=60):
            res = self.f.client(self.f.pm).post(self.f.url("cvat-sync/"), {"count_objects": False}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_integrity_error_races_handled_without_500_in_link_and_sync(self) -> None:
        # 1. cvat/link IntegrityError race → HTTP 400
        with (
            patch("cvat_integration.views.CvatClient", FakeCvatClient),
            patch("cvat_integration.views.CvatAccount.objects.update_or_create", side_effect=IntegrityError("dup")),
        ):
            res = self.f.client(self.f.ann1).post("/api/cvat/link/", {"token": "tok-ann1"}, format="json")
        self.assertEqual(res.status_code, 400)

        # 2. import_task_jobs IntegrityError race on cvat_task_id → ValidationError (400)
        other_batch = Batch.objects.create(project=self.f.project, dataset=self.f.dataset, name="Other")

        class ImportClient:
            def get_task(self, task_id):
                return {"id": task_id, "name": "Task X"}

            def list_task_jobs(self, task_id):
                return []

        with (
            patch.object(Batch, "save", side_effect=IntegrityError("dup task")),
            self.assertRaises(DrfValidationError),
        ):
            import_task_jobs(other_batch, 999, self.f.pm, client=ImportClient())

        # 3. sync_organizations IntegrityError on Project/RoleAssignment → recovers cleanly
        CvatAccount.objects.create(user=self.f.pm, cvat_user_id=50, cvat_username="pm_cvat")
        client = _FakeSyncClient(
            jobs=[],
            orgs=[{"id": 7, "slug": "acme", "name": self.f.project.name}],
            memberships={7: [{"user": {"id": 50}, "role": "owner", "is_active": True}]},
        )
        with patch("cvat_integration.sync.RoleAssignment.objects.get_or_create", side_effect=IntegrityError("dup role")):
            summary = sync.sync_organizations(actor=self.f.pm, client=client)
        self.assertEqual(summary["pm_added"], [])

    def test_outbox_durable_retry_isolation_stale_guard_activity_log_and_command(self) -> None:
        CvatAccount.objects.create(user=self.f.ann1, cvat_user_id=11, cvat_username="a1")
        CvatAccount.objects.create(user=self.f.ann2, cvat_user_id=12, cvat_username="a2")
        j1 = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=911)
        j2 = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann2, cvat_job_id=912)
        enqueue_assignee_push([j1.pk, j2.pk])
        self.assertEqual(CvatAssigneeOutbox.objects.filter(status=CvatAssigneeOutbox.Status.PENDING).count(), 2)

        # Job 1 lỗi, Job 2 thành công → lô không dừng giữa chừng; j1 lên backoff pending, j2 xong + ActivityLog
        class PartialOrgFailClient:
            def __init__(self):
                self.invited: list[tuple[str, str, str]] = []
                self.pushed: list[tuple[int, int | None]] = []

            def list_memberships(self, org_id):
                return []

            def get_user(self, user_id):
                return {"id": user_id, "username": f"u{user_id}", "email": f"u{user_id}@example.com"}

            def invite_to_org(self, org_slug, email, role="worker"):
                self.invited.append((org_slug, email, role))

            def set_job_assignee(self, cvat_job_id, cvat_user_id):
                if cvat_job_id == 911:
                    raise CvatError("temporary 503")
                self.pushed.append((cvat_job_id, cvat_user_id))

        partial_client = PartialOrgFailClient()
        stats = drain_cvat_outbox(client=partial_client, max_attempts=2)
        self.assertEqual((stats["pushed"], stats["failed"]), (1, 1))
        self.assertEqual(partial_client.pushed, [(912, 12)])
        j1.refresh_from_db()
        j2.refresh_from_db()
        self.assertIsNone(j1.cvat_assignee_id)
        self.assertEqual(j2.cvat_assignee_id, 12)
        self.assertTrue(ActivityLog.objects.filter(job=j2, action="cvat.assignee_push", actor__isnull=True).exists())
        self.assertTrue(ActivityLog.objects.filter(project=self.f.project, action="cvat.org_invite", actor__isnull=True).exists())

        outbox_j1 = CvatAssigneeOutbox.objects.get(job=j1)
        self.assertEqual((outbox_j1.status, outbox_j1.attempts), (CvatAssigneeOutbox.Status.PENDING, 1))
        self.assertGreater(outbox_j1.next_retry_at, timezone.now())

        # Lần retry thứ 2 đạt max_attempts=2 → chuyển DEAD
        stats_dead = drain_cvat_outbox(client=partial_client, force=True, max_attempts=2)
        self.assertEqual(stats_dead["dead"], 1)
        outbox_j1.refresh_from_db()
        self.assertEqual(outbox_j1.status, CvatAssigneeOutbox.Status.DEAD)

        # Stale-write guard: trong lúc HTTP đang chạy cho j3 (target=11), VanoHub đổi annotator sang ann2 (target=12)
        j3 = self.f.job(status=JobStatus.ANNOTATING, annotator=self.f.ann1, cvat_job_id=913)
        enqueue_assignee_push([j3.pk])

        class StaleRaceClient(PartialOrgFailClient):
            def __init__(self, new_ann_id: int) -> None:
                super().__init__()
                self.new_ann_id = new_ann_id

            def list_memberships(self, org_id):
                return [{"user": {"id": 11}, "is_active": True}, {"user": {"id": 12}, "is_active": True}]

            def set_job_assignee(self, cvat_job_id, cvat_user_id):
                super().set_job_assignee(cvat_job_id, cvat_user_id)
                if cvat_job_id == 913 and cvat_user_id == 11:
                    Job.objects.filter(pk=j3.pk).update(annotator=self.new_ann_id)

        race_client = StaleRaceClient(self.f.ann2.pk)
        drain_cvat_outbox(job_ids=[j3.pk], client=race_client)
        j3.refresh_from_db()
        # Không ghi đè cvat_assignee_id=11 bị cũ; đã xếp hàng lại cho 12
        self.assertIsNone(j3.cvat_assignee_id)
        pending_j3 = CvatAssigneeOutbox.objects.get(job=j3, status=CvatAssigneeOutbox.Status.PENDING)
        self.assertEqual(pending_j3.target_cvat_user_id, 12)

        # Management command drain_cvat_outbox chạy thành công
        with patch("cvat_integration.management.commands.drain_cvat_outbox.drain_cvat_outbox") as mock_drain:
            mock_drain.return_value = {"claimed": 1, "pushed": 1, "failed": 0, "dead": 0, "skipped": 0, "locked": False}
            call_command("drain_cvat_outbox", "--limit", "10", "--force")
            mock_drain.assert_called_once_with(batch_limit=10, force=True, max_attempts=10)

    def test_submit_annotation_cvat_linked_job_preserves_cvat_object_count_ssot(self) -> None:
        cvat_job = self.f.job(
            status=JobStatus.ANNOTATING,
            annotator=self.f.ann1,
            cvat_job_id=950,
            object_count=30,
            last_counted_objects=30,
        )
        res = self.f.client(self.f.ann1).post(
            self.f.url(f"annotator/jobs/{cvat_job.id}/submit/"),
            {"object_count": 9999, "note": "done"},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.data)
        cvat_job.refresh_from_db()
        self.assertEqual(cvat_job.status, JobStatus.PENDING_QC1)
        self.assertEqual(cvat_job.object_count, 30)
        self.assertFalse(DailyOutputRecord.objects.filter(job=cvat_job).exists())
