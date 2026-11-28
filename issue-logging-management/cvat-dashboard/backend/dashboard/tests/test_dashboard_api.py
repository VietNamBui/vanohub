from __future__ import annotations

import hashlib
import hmac
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from dashboard.models import (
    DailyUserMetrics,
    DefectRecord,
    DeliverStatus,
    DeliveryBatch,
    DeliveryBatchItem,
    JobQualitySnapshot,
    PipelineStep,
    StageTransition,
    SyncedJob,
    SyncedTask,
)

User = get_user_model()


class DashboardApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()
        self.staff_user = User.objects.create_user(
            username="qa_lead",
            password="password123",
            email="qa_lead@company.local",
            is_staff=True,
            is_superuser=True,
        )
        self.token = Token.objects.create(user=self.staff_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {self.token.key}")

        now = timezone.now()

        # Task & Jobs
        self.task = SyncedTask.objects.create(
            cvat_task_id=501,
            name="Test_3D_LiDAR_Scene",
            project_name="Project_Alpha",
            total_frames=500,
        )
        self.job1 = SyncedJob.objects.create(
            cvat_job_id=5001,
            task=self.task,
            start_frame=0,
            stop_frame=99,
            frame_count=100,
            pipeline_step=PipelineStep.ANNOTATOR,
            deliver_status=DeliverStatus.NOT_READY,
            annotator_username="annotator_alice",
            open_issues=1,
            step_entered_at=now - timedelta(hours=30),  # SLA breach (> 24h)
        )
        self.job2 = SyncedJob.objects.create(
            cvat_job_id=5002,
            task=self.task,
            start_frame=100,
            stop_frame=199,
            frame_count=100,
            pipeline_step=PipelineStep.COMPLETED,
            deliver_status=DeliverStatus.READY,
            annotator_username="annotator_bob",
            open_issues=0,
            threshold_met=True,
            step_entered_at=now - timedelta(hours=5),
        )

        # Stage Transitions
        StageTransition.objects.create(
            job=self.job1,
            from_step="l1_qc",
            to_step="annotator",
            actor_username="qc_charlie",
            actor_role="l1_qc",
            reason="Sai lệch góc yaw quá ngưỡng",
            duration_prev_step_sec=7200,
        )

        # Quality Snapshot
        JobQualitySnapshot.objects.create(
            job=self.job1,
            total_source_boxes=100,
            added_boxes=5,
            deleted_boxes=3,
            unchanged_boxes=90,
            modified_boxes=2,
            touched_rate=0.07,
            source_box_touch_rate=0.05,
            effort_score=0.2,
            rubber_stamp_strata_suspect=True,
            attr_missed_count=2,
            issues_tp=10,
            issues_fp=2,
            suspicious_deletion_count=2,
            track_id_switch_count=1,
            l1_escape_count=1,
            ruling_agreed_count=5,
            ruling_disagreed_count=1,
        )

        # Daily Metrics
        DailyUserMetrics.objects.create(
            date=now.date(),
            username="annotator_alice",
            role="annotator",
            jobs_submitted=3,
            frames_processed=300,
            cuboids_inspected=450,
            working_time_ms=7 * 3600000,
        )

        # Defects
        DefectRecord.objects.create(
            cvat_issue_id=9001,
            job=self.job1,
            frame=10,
            primary_category="E1",
            defect_code="E101_DIM_ERROR",
            severity="major",
            summary_text="Kích thước hộp cuboid sai lệch",
            root_cause="Sensor Glare",
        )
        DefectRecord.objects.create(
            cvat_issue_id=9002,
            job=self.job1,
            frame=20,
            primary_category="E3",
            defect_code="E301_MISSED_BOX",
            severity="critical",
            summary_text="Bỏ sót vật thể",
            root_cause="Human Oversight",
        )

    def test_data_cycle_funnel(self) -> None:
        resp = self.client.get("/api/funnel/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        wip = resp.data["wip"]
        self.assertEqual(wip["annotation"]["jobs"], 1)
        self.assertEqual(wip["deliver"]["jobs"], 1)

        # SLA breach check (job1 entered 30h ago, SLA is 24h)
        self.assertGreaterEqual(resp.data["sla_breaches_count"], 1)
        breached_job_ids = [b["job_id"] for b in resp.data["sla_breaches"]]
        self.assertIn(5001, breached_job_ids)

        # Rework loop counter
        rework_loops = resp.data["rework_loops"]
        self.assertGreaterEqual(rework_loops["qc1_to_annotation"], 1)

    def test_daily_productivity(self) -> None:
        resp = self.client.get("/api/productivity/?days=7")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("timeline", resp.data)
        self.assertIn("users", resp.data)

        users = resp.data["users"]
        alice = next((u for u in users if u["username"] == "annotator_alice"), None)
        self.assertIsNotNone(alice)
        self.assertEqual(alice["jobs_submitted"], 3)
        self.assertGreater(alice["frames_per_hour"], 0)

    def test_quality_scorecard_and_red_flags(self) -> None:
        resp = self.client.get("/api/scorecard/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        scorecard = resp.data["reviewer_scorecard"]
        self.assertEqual(scorecard["total_tp"], 10)
        self.assertEqual(scorecard["total_fp"], 2)
        self.assertIn("lower", scorecard["precision"])
        self.assertIn("upper", scorecard["precision"])
        self.assertGreaterEqual(scorecard["precision"]["value"], 0.8)

        red_flags = resp.data["anti_gaming_red_flags"]
        self.assertEqual(red_flags["low_touch_suspects"], 1)
        self.assertEqual(red_flags["missing_attributes"], 1)
        self.assertEqual(red_flags["suspicious_s0_deletions"], 1)
        self.assertEqual(red_flags["track_id_switches"], 1)
        self.assertGreaterEqual(len(red_flags["flagged_jobs"]), 1)

    def test_defect_pareto(self) -> None:
        resp = self.client.get("/api/defects/")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["total_defects"], 2)

        pareto = resp.data["pareto"]
        categories = [p["category"] for p in pareto]
        self.assertIn("E1", categories)
        self.assertIn("E3", categories)

    def test_delivery_batch_lifecycle_and_gate_verification(self) -> None:
        # 1. Create Batch
        resp_create = self.client.post(
            "/api/delivery-batches/",
            {
                "batch_code": "BATCH-TEST-001",
                "title": "Batch Alpha Delivery",
                "client_name": "Autonomous Client",
            },
            format="json",
        )
        self.assertEqual(resp_create.status_code, status.HTTP_201_CREATED)
        batch_id = resp_create.data["id"]

        # 2. Add Job 2 (completed, no issues) and Job 1 (open issues, incomplete)
        batch = DeliveryBatch.objects.get(id=batch_id)
        DeliveryBatchItem.objects.create(batch=batch, job=self.job2)

        # Verify gate with only job2 -> should PASS
        resp_verify = self.client.post(f"/api/delivery-batches/{batch_id}/verify-gate/")
        self.assertEqual(resp_verify.status_code, status.HTTP_200_OK)
        self.assertTrue(resp_verify.data["all_passed"])
        self.assertEqual(resp_verify.data["status"], DeliveryBatch.Status.GATE_READY)

        # Add job1 (incomplete) -> verify gate should FAIL
        DeliveryBatchItem.objects.create(batch=batch, job=self.job1)
        resp_verify2 = self.client.post(f"/api/delivery-batches/{batch_id}/verify-gate/")
        self.assertEqual(resp_verify2.status_code, status.HTTP_200_OK)
        self.assertFalse(resp_verify2.data["all_passed"])
        self.assertEqual(resp_verify2.data["status"], DeliveryBatch.Status.DRAFT)

        # Export manifest
        resp_manifest = self.client.get(f"/api/delivery-batches/{batch_id}/export-manifest/")
        self.assertEqual(resp_manifest.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_manifest.data["batch_code"], "BATCH-TEST-001")
        self.assertEqual(len(resp_manifest.data["items"]), 2)

    @override_settings(CVAT_WEBHOOK_SECRET="test_webhook_secret_key")
    def test_webhook_cvat_stage_transition(self) -> None:
        payload = {
            "job_id": 6001,
            "task_id": 501,
            "task_name": "Test_3D_LiDAR_Scene",
            "event": "stage.accepted",
            "from_step": "annotator",
            "to_step": "l1_qc",
            "actor": "qc_lead",
            "actor_role": "l1_qc",
            "reason": "Hoàn tất duyệt L1",
        }
        raw_body = json.dumps(payload).encode("utf-8")
        sig = "sha256=" + hmac.new(b"test_webhook_secret_key", raw_body, hashlib.sha256).hexdigest()

        resp = self.client.post(
            "/api/webhooks/cvat-stage/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_SIGNATURE_256=sig,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["status"], "received")

        # Job is created/synced
        synced_job = SyncedJob.objects.filter(cvat_job_id=6001).first()
        self.assertIsNotNone(synced_job)
        self.assertEqual(synced_job.pipeline_step, PipelineStep.L1_QC)

        # Transition is created
        tr = StageTransition.objects.filter(job=synced_job, to_step="l1_qc").first()
        self.assertIsNotNone(tr)
        self.assertEqual(tr.actor_username, "qc_lead")

    def test_flexible_2d_3d_modalities_and_filtering(self) -> None:
        # Create a 2D task + job + snapshot + daily metric + defect + 2D delivery batch
        task_2d = SyncedTask.objects.create(
            cvat_task_id=502,
            name="Test_2D_DMS_Landmarks",
            project_name="Cabin_DMS",
            dimension="2d",
            annotation_type="skeleton",
            total_frames=200,
        )
        job_2d = SyncedJob.objects.create(
            cvat_job_id=7001,
            task=task_2d,
            frame_count=200,
            pipeline_step=PipelineStep.COMPLETED,
            deliver_status=DeliverStatus.READY,
            annotator_username="ann_2d",
            l1_qc_username="qc_2d",
            total_cuboids=320,
            inspected_cuboids=320,
            required_cuboids=200,
            open_issues=0,
            threshold_met=True,
            l2_required=False,
        )
        JobQualitySnapshot.objects.create(
            job=job_2d,
            issues_tp=15,
            issues_fp=1,
            source_box_touch_rate=0.45,
            geometry_metrics={
                "mean_iou_2d": 0.92,
                "mean_center_shift_px": 2.4,
                "mean_landmark_err_px": 1.1,
                "out_of_bounds_count": 1,
            },
            honeypot_evaluated=True,
            honeypot_passed=True,
            honeypot_mean_iou=0.93,
        )
        DailyUserMetrics.objects.create(
            date=timezone.now().date(),
            username="ann_2d",
            role="annotator",
            dimension="2d",
            jobs_submitted=4,
            frames_processed=400,
            cuboids_inspected=900,
            working_time_ms=4 * 3600000,
        )
        DefectRecord.objects.create(
            cvat_issue_id=9501,
            job=job_2d,
            frame=10,
            primary_category="E1",
            defect_code="DMS_001_EYEBROW_ORDER",
            severity="major",
            summary_text="Thứ tự landmark lông mày sai",
        )

        # 1. Modalities endpoint
        resp_mod = self.client.get("/api/modalities/")
        self.assertEqual(resp_mod.status_code, status.HTTP_200_OK)
        self.assertIn("3d", resp_mod.data["profiles"])
        self.assertIn("2d", resp_mod.data["profiles"])
        self.assertEqual(resp_mod.data["job_counts"]["2d"], 1)
        self.assertGreaterEqual(resp_mod.data["job_counts"]["3d"], 2)

        # 2. Funnel filtered by 2d
        resp_funnel_2d = self.client.get("/api/funnel/?dimension=2d")
        self.assertEqual(resp_funnel_2d.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_funnel_2d.data["dimension"], "2d")
        self.assertEqual(resp_funnel_2d.data["wip"]["deliver"]["jobs"], 1)
        self.assertEqual(resp_funnel_2d.data["wip"]["deliver"]["items"], 320)
        self.assertEqual(resp_funnel_2d.data["wip"]["annotation"]["jobs"], 0)

        # 3. Productivity filtered by 2d
        resp_prod_2d = self.client.get("/api/productivity/?days=7&dimension=2d")
        self.assertEqual(resp_prod_2d.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_prod_2d.data["modality"]["unit_label"], "Objects 2D")
        self.assertEqual(len(resp_prod_2d.data["users"]), 1)
        self.assertEqual(resp_prod_2d.data["users"][0]["items_inspected"], 900)

        # 4. Scorecard filtered by 2d returns 2D geometry_summary
        resp_sc_2d = self.client.get("/api/scorecard/?dimension=2d")
        self.assertEqual(resp_sc_2d.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_sc_2d.data["total_evaluated_jobs"], 1)
        self.assertAlmostEqual(resp_sc_2d.data["geometry_summary"]["mean_iou_2d"], 0.92, places=2)
        self.assertAlmostEqual(resp_sc_2d.data["geometry_summary"]["mean_landmark_err_px"], 1.1, places=2)

        # 5. Defects filtered by 2d uses 2D E1 label
        resp_def_2d = self.client.get("/api/defects/?dimension=2d")
        self.assertEqual(resp_def_2d.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_def_2d.data["total_defects"], 1)
        self.assertIn("2D", resp_def_2d.data["pareto"][0]["label"])

        # 6. Delivery batch dimension enforcement
        batch_2d = DeliveryBatch.objects.create(
            batch_code="BATCH-2D-ONLY",
            title="2D Only Batch",
            dimension="2d",
        )
        DeliveryBatchItem.objects.create(batch=batch_2d, job=job_2d)
        DeliveryBatchItem.objects.create(batch=batch_2d, job=self.job2)  # 3D job mismatch
        resp_gate = self.client.post(f"/api/delivery-batches/{batch_2d.id}/verify-gate/")
        self.assertEqual(resp_gate.status_code, status.HTTP_200_OK)
        self.assertFalse(resp_gate.data["all_passed"])
        mismatch_item = DeliveryBatchItem.objects.get(batch=batch_2d, job=self.job2)
        self.assertFalse(mismatch_item.gate_passed)
        self.assertTrue(any("2D" in b for b in mismatch_item.gate_blockers))

    @override_settings(CVAT_WEBHOOK_SECRET="test_webhook_secret_key")
    def test_webhook_creates_2d_task_from_payload(self) -> None:
        payload = {
            "job_id": 7002,
            "task_id": 503,
            "task_name": "DMS_2D_Webhook_Task",
            "dimension": "2d",
            "annotation_type": "skeleton",
            "event": "stage.submitted",
            "from_step": "annotator",
            "to_step": "l1_qc",
            "actor": "ann_2d",
            "actor_role": "annotator",
        }
        raw_body = json.dumps(payload).encode("utf-8")
        sig = "sha256=" + hmac.new(b"test_webhook_secret_key", raw_body, hashlib.sha256).hexdigest()
        resp = self.client.post(
            "/api/webhooks/cvat-stage/",
            data=raw_body,
            content_type="application/json",
            HTTP_X_SIGNATURE_256=sig,
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        t = SyncedTask.objects.get(cvat_task_id=503)
        self.assertEqual(t.dimension, "2d")
        self.assertEqual(t.annotation_type, "skeleton")
