from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from dashboard.models import (
    DeliveryBatch,
    Dimension,
    PipelineStep,
    QcEvent,
    SyncedJob,
    SyncedTask,
    WorkflowBatch,
    WorkflowBatchStatus,
    WorkflowDataset,
    WorkflowDataType,
    WorkflowJob,
    WorkflowJobStage,
    WorkflowKpiDaily,
    WorkflowProject,
    WorkflowRole,
    WorkflowTeam,
    WorkflowUser,
)

User = get_user_model()


class DashboardHardeningTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

        self.dj_admin = User.objects.create_user(
            username="admin_h", password="pw", is_staff=True, is_superuser=True
        )
        self.dj_lead = User.objects.create_user(username="lead_h", password="pw")
        self.dj_ann = User.objects.create_user(username="ann_h", password="pw")
        self.dj_ann2 = User.objects.create_user(username="ann_other", password="pw")

        self.dt3d = WorkflowDataType.objects.create(
            code="dt_h_3d",
            name="LiDAR 3D",
            dimension=Dimension.DIM_3D,
            shape_type="cuboid",
            kpi_per_day=1200,
            error_categories=["Yaw", "Missing"],
        )

        self.u_admin = WorkflowUser.objects.create(
            code="u_h_admin",
            name="Admin H",
            cvat_username="admin_h",
            role=WorkflowRole.ADMIN,
            django_user=self.dj_admin,
        )
        self.u_lead = WorkflowUser.objects.create(
            code="u_h_lead",
            name="Lead H",
            cvat_username="lead_h",
            role=WorkflowRole.LEAD,
            django_user=self.dj_lead,
        )
        self.u_ann = WorkflowUser.objects.create(
            code="u_h_ann",
            name="Ann H",
            cvat_username="ann_h",
            role=WorkflowRole.ANNOTATOR,
            django_user=self.dj_ann,
        )
        self.u_ann2 = WorkflowUser.objects.create(
            code="u_h_ann2",
            name="Ann Other",
            cvat_username="ann_other",
            role=WorkflowRole.ANNOTATOR,
            django_user=self.dj_ann2,
        )

        self.team1 = WorkflowTeam.objects.create(
            code="t_h1",
            name="Team H1",
            lead=self.u_lead,
            can_qa=False,
        )
        self.team1.members.set([self.u_lead, self.u_ann])

        self.project = WorkflowProject.objects.create(
            code="p_h1",
            display_code="PRJ-H1",
            name="Secret Client Proj",
            partner="Confidential OEM Partner",
            data_type=self.dt3d,
            pm_order=["u_h_admin"],
        )
        self.project.pms.set([self.u_admin])
        self.project.teams.set([self.team1])

        self.dataset = WorkflowDataset.objects.create(
            code="ds_h1",
            project=self.project,
            data_type=self.dt3d,
            name="DS H1",
            nas_path="/mnt/secret_nas/oem/batch1",
            file_count=100,
            frame_count=100,
        )
        self.batch = WorkflowBatch.objects.create(
            code="b_h1",
            project=self.project,
            dataset=self.dataset,
            team=self.team1,
            cvat_task_id=8101,
            status=WorkflowBatchStatus.IN_PROGRESS,
            name="Batch H1",
        )
        self.job_assigned = WorkflowJob.objects.create(
            code="j_h1",
            batch=self.batch,
            project=self.project,
            team=self.team1,
            cvat_job_id=9101,
            frames=100,
            annotator=self.u_ann,
            stage=WorkflowJobStage.ANNO_IN_PROGRESS,
        )
        self.job_other = WorkflowJob.objects.create(
            code="j_h2",
            batch=self.batch,
            project=self.project,
            team=self.team1,
            cvat_job_id=9102,
            frames=100,
            annotator=self.u_ann2,
            stage=WorkflowJobStage.ANNO_IN_PROGRESS,
        )
        WorkflowKpiDaily.objects.create(
            user=self.u_ann,
            date=date.today(),
            edited_cuboids=50,
        )
        WorkflowKpiDaily.objects.create(
            user=self.u_ann2,
            date=date.today(),
            edited_cuboids=99,
        )

        self.stask = SyncedTask.objects.create(cvat_task_id=8101, name="Task 8101")
        self.sjob = SyncedJob.objects.create(
            cvat_job_id=9101,
            task=self.stask,
            annotator_username="ann_h",
            pipeline_step=PipelineStep.ANNOTATOR,
        )

    @override_settings(DEBUG=True)
    def test_non_staff_impersonation_blocked_even_when_debug_true(self) -> None:
        self.client.force_authenticate(user=self.dj_ann)
        r_state = self.client.get(
            "/api/workflow/state/?as_user=u_h_admin",
            HTTP_X_WORKFLOW_USER="u_h_admin",
        )
        self.assertEqual(r_state.status_code, status.HTTP_200_OK)
        self.assertEqual(r_state.data["currentUserId"], "u_h_ann")

        r_switch = self.client.post(
            "/api/workflow/switch-user/",
            {"userId": "u_h_admin"},
            format="json",
        )
        self.assertEqual(r_switch.status_code, status.HTTP_403_FORBIDDEN)

    def test_annotator_dashboard_state_redacts_sensitive_fields_and_other_users(self) -> None:
        self.client.force_authenticate(user=self.dj_ann)
        r = self.client.get("/api/workflow/state/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.data

        job_ids = {j["id"] for j in data["jobs"]}
        self.assertEqual(job_ids, {"j_h1"})

        for proj in data["projects"]:
            self.assertEqual(
                proj["partner"],
                {"name": "", "contact": "", "email": "", "contractNote": ""},
            )
        for ds in data["datasets"]:
            self.assertEqual(ds["nasPath"], "")

        kpi_users = {k["userId"] for k in data["kpiDaily"]}
        self.assertEqual(kpi_users, {"u_h_ann"})

        self.assertEqual(data["audits"], [])

    def test_preview_distribution_forbidden_for_annotator(self) -> None:
        self.client.force_authenticate(user=self.dj_ann)
        r = self.client.post("/api/workflow/batches/b_h1/preview-distribution/", {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_lead_cannot_escalate_role_via_update_user(self) -> None:
        self.client.force_authenticate(user=self.dj_lead)
        r = self.client.patch(
            "/api/workflow/users/u_h_lead/",
            {"role": "admin", "cvatUsername": "admin_h"},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)
        self.u_lead.refresh_from_db()
        self.assertEqual(self.u_lead.role, WorkflowRole.LEAD)
        self.assertEqual(self.u_lead.cvat_username, "lead_h")

    def test_qc_events_post_forces_identity_and_client_prefix_for_annotator(self) -> None:
        self.client.force_authenticate(user=self.dj_ann)

        # Unassigned job is rejected
        r_other = self.client.post(
            "/api/qc-events/",
            {"job_id": 9102, "event_type": "job_submitted", "username": "admin_h"},
            format="json",
        )
        self.assertEqual(r_other.status_code, status.HTTP_403_FORBIDDEN)

        # Assigned job forces identity + client_ prefix
        r_ok = self.client.post(
            "/api/qc-events/",
            {
                "idempotency_key": "ann_h_ev_1",
                "job_id": 9101,
                "event_type": "job_accepted_l2",
                "username": "admin_h",
                "actor_role": "admin",
            },
            format="json",
        )
        self.assertEqual(r_ok.status_code, status.HTTP_201_CREATED)
        ev = QcEvent.objects.get(idempotency_key="ann_h_ev_1")
        self.assertEqual(ev.username, "ann_h")
        self.assertEqual(ev.actor_role, WorkflowRole.ANNOTATOR)
        self.assertTrue(ev.event_type.startswith("client_"))
        self.assertFalse(ev.applied_to_workflow)

        # Oversized batch rejected with 400
        r_big = self.client.post(
            "/api/qc-events/",
            {"events": [{"job_id": 9101}] * 501},
            format="json",
        )
        self.assertEqual(r_big.status_code, status.HTTP_400_BAD_REQUEST)

    def test_negative_or_invalid_ints_return_400(self) -> None:
        self.client.force_authenticate(user=self.dj_ann)
        r_bad_submit = self.client.post(
            "/api/workflow/jobs/j_h1/submit/",
            {"editedCuboids": -5},
            format="json",
        )
        self.assertEqual(r_bad_submit.status_code, status.HTTP_400_BAD_REQUEST)

        self.client.force_authenticate(user=self.dj_admin)
        r_bad_audit = self.client.post(
            "/api/workflow/audits/",
            {"batchId": "b_h1", "percent": "not_an_int"},
            format="json",
        )
        self.assertEqual(r_bad_audit.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(CVAT_WEBHOOK_SECRET="")
    def test_webhook_fails_closed_when_secret_empty(self) -> None:
        self.client.force_authenticate(user=None)
        r_anon = self.client.post(
            "/api/webhooks/cvat-stage/",
            {"job_id": 9101, "to_step": "l1_qc"},
            format="json",
        )
        self.assertEqual(r_anon.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(user=self.dj_ann)
        r_ann = self.client.post(
            "/api/webhooks/cvat-stage/",
            {"job_id": 9101, "to_step": "l1_qc"},
            format="json",
        )
        self.assertEqual(r_ann.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(CVAT_WEBHOOK_SECRET="wh_secret_h", CVAT_WEBHOOK_MAX_AGE_SECONDS=60)
    def test_webhook_validates_pipeline_step_and_timestamp_replay_window(self) -> None:
        self.client.force_authenticate(user=None)

        bad_step_body = json.dumps({"job_id": 9101, "to_step": "hacked_step"}).encode("utf-8")
        bad_sig = "sha256=" + hmac.new(b"wh_secret_h", bad_step_body, hashlib.sha256).hexdigest()
        r_step = self.client.post(
            "/api/webhooks/cvat-stage/",
            data=bad_step_body,
            content_type="application/json",
            HTTP_X_CVAT_SIGNATURE_256=bad_sig,
        )
        self.assertEqual(r_step.status_code, status.HTTP_400_BAD_REQUEST)

        valid_body = json.dumps({"job_id": 9101, "to_step": "l1_qc"}).encode("utf-8")
        valid_sig = "sha256=" + hmac.new(b"wh_secret_h", valid_body, hashlib.sha256).hexdigest()
        expired_ts = str(int(time.time()) - 3600)
        r_stale = self.client.post(
            "/api/webhooks/cvat-stage/",
            data=valid_body,
            content_type="application/json",
            HTTP_X_CVAT_SIGNATURE_256=valid_sig,
            HTTP_X_CVAT_TIMESTAMP=expired_ts,
        )
        self.assertEqual(r_stale.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delivery_batch_status_is_read_only(self) -> None:
        self.client.force_authenticate(user=self.dj_admin)
        r_create = self.client.post(
            "/api/delivery-batches/",
            {
                "batch_code": "BATCH-RO-1",
                "title": "ReadOnly Status Test",
                "status": DeliveryBatch.Status.DELIVERED,
                "created_by": "spoofed_user",
            },
            format="json",
        )
        self.assertEqual(r_create.status_code, status.HTTP_201_CREATED)
        batch = DeliveryBatch.objects.get(batch_code="BATCH-RO-1")
        self.assertEqual(batch.status, DeliveryBatch.Status.DRAFT)
        self.assertEqual(batch.created_by, self.dj_admin)

        r_patch = self.client.patch(
            f"/api/delivery-batches/{batch.id}/",
            {"status": DeliveryBatch.Status.DELIVERED},
            format="json",
        )
        self.assertEqual(r_patch.status_code, status.HTTP_200_OK)
        batch.refresh_from_db()
        self.assertEqual(batch.status, DeliveryBatch.Status.DRAFT)

    @override_settings(DEBUG=False)
    def test_spa_entry_hides_endpoints_when_not_debug(self) -> None:
        self.client.force_authenticate(user=None)
        r = self.client.get("/")
        if r.status_code == status.HTTP_200_OK and r.headers.get("Content-Type", "").startswith("application/json"):
            data = json.loads(r.content.decode("utf-8"))
            self.assertNotIn("endpoints", data)
