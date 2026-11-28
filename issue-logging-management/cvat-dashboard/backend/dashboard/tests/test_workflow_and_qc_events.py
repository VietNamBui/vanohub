from __future__ import annotations

import hashlib
import hmac
import json

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from dashboard.models import (
    DefectRecord,
    Dimension,
    JobQualitySnapshot,
    QcEvent,
    SyncedJob,
    SyncedTask,
    WorkflowAudit,
    WorkflowBatch,
    WorkflowBatchStatus,
    WorkflowDataset,
    WorkflowDataType,
    WorkflowJob,
    WorkflowJobEvent,
    WorkflowJobStage,
    WorkflowKpiDaily,
    WorkflowProject,
    WorkflowRole,
    WorkflowTeam,
    WorkflowUser,
)

User = get_user_model()


class WorkflowAndTransactionalQcEventTests(APITestCase):
    def setUp(self) -> None:
        self.dj_admin = User.objects.create_user(
            username="pm_test", password="pw", is_staff=True, is_superuser=True
        )
        self.client.force_authenticate(user=self.dj_admin)

        self.dt3d = WorkflowDataType.objects.create(
            code="dt3d",
            name="LiDAR 3D",
            dimension=Dimension.DIM_3D,
            shape_type="cuboid",
            kpi_per_day=1200,
            error_categories=["Sai hướng (Yaw)", "Thiếu object"],
        )
        self.u_pm = WorkflowUser.objects.create(
            code="u_pm", django_user=self.dj_admin, name="PM Test", cvat_username="pm_test", role=WorkflowRole.ADMIN, is_qc=True, employee_id=101
        )
        self.u_ann = WorkflowUser.objects.create(
            code="u_ann", name="Annotator A", cvat_username="ann_a", role=WorkflowRole.ANNOTATOR, is_qc=False, employee_id=201
        )
        self.u_qc1 = WorkflowUser.objects.create(
            code="u_qc1", name="QC1 A", cvat_username="qc1_a", role=WorkflowRole.LEAD, is_qc=True, employee_id=202
        )
        self.team = WorkflowTeam.objects.create(
            code="t1", name="Team Alpha", lead=self.u_qc1, allowed_steps=["annotate", "qc1", "qc2"], can_qa=True
        )
        self.team.members.set([self.u_qc1, self.u_ann])

        self.project = WorkflowProject.objects.create(
            code="p1", display_code="PRJ-P1", name="Proj 3D", data_type=self.dt3d, pm_order=["u_pm"]
        )
        self.project.pms.set([self.u_pm])
        self.project.teams.set([self.team])

        self.dataset = WorkflowDataset.objects.create(
            code="d1", name="DS 1", data_type=self.dt3d, project=self.project, file_count=100, frame_count=100
        )
        self.batch = WorkflowBatch.objects.create(
            code="b01",
            name="Batch 01",
            dataset=self.dataset,
            project=self.project,
            cvat_task_id=101,
            status=WorkflowBatchStatus.PENDING,
            step_buffer_days={"qc1": 1, "qc2": 1},
            priority=4,
        )
        self.job1 = WorkflowJob.objects.create(
            code="j0001", cvat_job_id=5001, batch=self.batch, project=self.project, prelabel_cuboids=300, frames=100
        )
        self.job2 = WorkflowJob.objects.create(
            code="j0002", cvat_job_id=5002, batch=self.batch, project=self.project, prelabel_cuboids=200, frames=100
        )

        # Matching SyncedTask + SyncedJob to test defect/snapshot side effects too
        self.stask = SyncedTask.objects.create(cvat_task_id=101, name="Task 101", dimension="3d", total_frames=200)
        self.sjob1 = SyncedJob.objects.create(cvat_job_id=5001, task=self.stask, annotator_username="ann_a", frame_count=100)

    def test_full_workflow_rest_lifecycle_emits_transactional_qc_events(self) -> None:
        # 1. Hydrate initial state
        st = self.client.get("/api/workflow/state/")
        self.assertEqual(st.status_code, status.HTTP_200_OK)
        self.assertEqual(len(st.data["jobs"]), 2)
        self.assertEqual(st.data["currentUserId"], "u_pm")

        # 2. Preview & distribute batch (and test R3 assignBatchTeam, R6 setTeamPm, R7 moveMember)
        u_pm_real = WorkflowUser.objects.create(
            code="u_pm2", name="PM 2", cvat_username="pm_2", role=WorkflowRole.PM, is_qc=True, employee_id=102
        )
        r_set_pm = self.client.post("/api/workflow/teams/t1/pm/", {"pmId": u_pm_real.code}, format="json")
        self.assertEqual(r_set_pm.status_code, status.HTTP_200_OK)
        self.assertEqual(r_set_pm.data["teams"][0]["pmId"], u_pm_real.code)

        dist = self.client.post("/api/workflow/batches/b01/assign-team/", {"teamId": "t1"}, format="json")
        self.assertEqual(dist.status_code, status.HTTP_200_OK)
        self.job1.refresh_from_db()
        self.assertEqual(self.job1.stage, WorkflowJobStage.TEAM_POOL)
        self.assertEqual(dist.data["batches"][0]["teamId"], "t1")
        self.assertEqual(dist.data["schemaVersion"], 2)

        # 3. Assign job1
        r_assign = self.client.post(
            "/api/workflow/jobs/j0001/assign/",
            {"annotatorId": "u_ann", "qc1Id": "u_qc1"},
            format="json",
        )
        self.assertEqual(r_assign.status_code, status.HTTP_200_OK)

        # 4. First submit credits KPI daily once
        r_sub1 = self.client.post("/api/workflow/jobs/j0001/submit/", {"editedCuboids": 150}, format="json")
        self.assertEqual(r_sub1.status_code, status.HTTP_200_OK)
        kpi_val = WorkflowKpiDaily.objects.get(user=self.u_ann).edited_cuboids
        self.assertEqual(kpi_val, 150)

        # 5. QC1 return (requires reason + errorCategory)
        r_bad = self.client.post("/api/workflow/jobs/j0001/qc1-return/", {"reason": "", "errorCategory": "Yaw"}, format="json")
        self.assertEqual(r_bad.status_code, status.HTTP_400_BAD_REQUEST)

        r_ret = self.client.post(
            "/api/workflow/jobs/j0001/qc1-return/",
            {"reason": "Lệch Yaw 15 độ", "errorCategory": "Sai hướng (Yaw)"},
            format="json",
        )
        self.assertEqual(r_ret.status_code, status.HTTP_200_OK)
        self.job1.refresh_from_db()
        self.assertEqual(self.job1.rework_count, 1)
        self.assertEqual(self.job1.stage, WorkflowJobStage.ANNO_IN_PROGRESS)

        # 6. Resubmit does NOT double-credit KPI
        r_sub2 = self.client.post("/api/workflow/jobs/j0001/submit/", {"editedCuboids": 999}, format="json")
        self.assertEqual(r_sub2.status_code, status.HTTP_200_OK)
        self.assertEqual(WorkflowKpiDaily.objects.get(user=self.u_ann).edited_cuboids, 150)

        # 7. QC1 pass -> QC2 audit -> pass -> close -> deliver
        self.assertEqual(self.client.post("/api/workflow/jobs/j0001/qc1-pass/", {}, format="json").status_code, status.HTTP_200_OK)

        r_au = self.client.post("/api/workflow/audits/", {"batchIds": ["b01"], "percent": 100}, format="json")
        self.assertEqual(r_au.status_code, status.HTTP_201_CREATED)
        au_id = r_au.data["createdAuditId"]

        self.assertEqual(
            self.client.post(f"/api/workflow/audits/{au_id}/pass-job/", {"jobId": "j0001"}, format="json").status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(f"/api/workflow/audits/{au_id}/close/", {}, format="json").status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(WorkflowAudit.objects.get(code=au_id).status, WorkflowAudit.Status.PASSED)

        self.assertEqual(
            self.client.post("/api/workflow/jobs/deliver/", {"jobIds": ["j0001"]}, format="json").status_code,
            status.HTTP_200_OK,
        )
        self.job1.refresh_from_db()
        self.assertEqual(self.job1.stage, WorkflowJobStage.DELIVERED)

        # Verify transactional QcEvents were emitted along the entire chain
        scopes = set(QcEvent.objects.filter(job_id=5001).values_list("scope", flat=True))
        for expected in (
            "qc:job_distributed",
            "qc:job_assigned",
            "qc:job_submitted",
            "qc:job_returned_for_rework",
            "qc:job_accepted_l1",
            "qc:audit_job_passed",
            "qc:job_completed_l2",
            "qc:job_delivered",
        ):
            self.assertIn(expected, scopes)

    def test_qc_events_idempotency_and_side_effects(self) -> None:
        # Advance job1 into ANNO_IN_PROGRESS first
        self.job1.team = self.team
        self.job1.annotator = self.u_ann
        self.job1.qc1 = self.u_qc1
        self.job1.stage = WorkflowJobStage.ANNO_IN_PROGRESS
        self.job1.save()

        # 1. preqc_ingest creates DefectRecord(source="pre_qc_auto")
        r_preqc = self.client.post(
            "/api/qc-events/",
            {
                "idempotency_key": "preqc_5001_iss1",
                "event_type": "preqc_ingest",
                "job_id": 5001,
                "task_id": 101,
                "actor_role": "bot",
                "username": "preqc_bot",
                "issue_id": 7701,
                "defect_code": "GEO-HDG",
                "severity": "major",
                "frame_number": 15,
            },
            format="json",
        )
        self.assertEqual(r_preqc.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r_preqc.data["created"])
        self.assertEqual(r_preqc.data["event"]["scope"], "qc:preqc_ingest")
        defect = DefectRecord.objects.get(cvat_issue_id=7701)
        self.assertEqual(defect.source, "pre_qc_auto")
        self.sjob1.refresh_from_db()
        self.assertEqual(self.sjob1.open_issues, 1)

        # 2. qc_fixed resolves defect and increments snapshot qc_fixed_issues + issues_tp
        r_fix = self.client.post(
            "/api/qc-events/",
            {
                "idempotency_key": "fix_5001_iss1",
                "scope": "qc:qc_fixed",
                "job_id": 5001,
                "issue_id": 7701,
                "username": "qc1_a",
                "actor_role": "l1_qc",
            },
            format="json",
        )
        self.assertEqual(r_fix.status_code, status.HTTP_201_CREATED)
        defect.refresh_from_db()
        self.assertEqual(defect.lifecycle_status, "resolved")
        snap = JobQualitySnapshot.objects.get(job=self.sjob1)
        self.assertEqual(snap.qc_fixed_issues, 1)
        self.assertEqual(snap.issues_tp, 1)

        # 3. job_submitted transitions WorkflowJob + credits KPI; duplicate replay is a no-op
        sub_payload = {
            "idempotency_key": "sub_5001_r1",
            "scope": "qc:job_submitted",
            "job_id": 5001,
            "task_id": 101,
            "username": "ann_a",
            "actor_role": "annotator",
            "params": {"edited_cuboids": 140},
        }
        r1 = self.client.post("/api/qc-events/", sub_payload, format="json")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertTrue(r1.data["created"])
        self.job1.refresh_from_db()
        self.assertEqual(self.job1.stage, WorkflowJobStage.QC1_PENDING)
        self.assertEqual(WorkflowKpiDaily.objects.get(user=self.u_ann).edited_cuboids, 140)

        r2 = self.client.post("/api/qc-events/", sub_payload, format="json")
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertFalse(r2.data["created"])
        self.assertEqual(WorkflowKpiDaily.objects.get(user=self.u_ann).edited_cuboids, 140)
        self.assertEqual(WorkflowJobEvent.objects.filter(job=self.job1, type="submit").count(), 1)

    def test_qc_events_batch_is_acid_transactional_all_or_nothing(self) -> None:
        self.job1.team = self.team
        self.job1.annotator = self.u_ann
        self.job1.stage = WorkflowJobStage.ANNO_IN_PROGRESS
        self.job1.save()

        # Batch has 1 valid event followed by 1 invalid event (job_id=0) -> entire batch must roll back
        resp = self.client.post(
            "/api/qc-events/",
            {
                "events": [
                    {
                        "idempotency_key": "batch_ok_1",
                        "scope": "qc:job_submitted",
                        "job_id": 5001,
                        "username": "ann_a",
                    },
                    {
                        "idempotency_key": "batch_bad_2",
                        "scope": "qc:job_accepted_l1",
                        "job_id": 0,  # invalid
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(QcEvent.objects.filter(idempotency_key="batch_ok_1").count(), 0)
        self.job1.refresh_from_db()
        self.assertEqual(self.job1.stage, WorkflowJobStage.ANNO_IN_PROGRESS)

    @override_settings(CVAT_WEBHOOK_SECRET="qc_event_secret")
    def test_qc_events_hmac_auth_and_jsonl_backfill_and_activity(self) -> None:
        self.client.force_authenticate(user=None)
        body = json.dumps({
            "idempotency_key": "hmac_dwell_1",
            "event_type": "qc_frame_dwell",
            "job_id": 5001,
            "task_id": 101,
            "username": "qc1_a",
            "actor_role": "l1_qc",
            "frame_number": 9,
            "params": {"dwell_ms": 3500},
        }).encode("utf-8")
        sig = "sha256=" + hmac.new(b"qc_event_secret", body, hashlib.sha256).hexdigest()

        r = self.client.post(
            "/api/qc-events/",
            data=body,
            content_type="application/json",
            HTTP_X_SIGNATURE_256=sig,
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r.data["event"]["dwell_ms"], 3500)

        # Re-authenticate to test JSONL backfill deduplication & activity endpoint
        self.client.force_authenticate(user=self.dj_admin)
        jsonl = "\n".join([
            json.dumps({"timestamp_utc": "2026-11-19T08:00:00Z", "event_type": "issue_created", "job_id": 5001, "task_id": 101, "username": "qc1_a", "defect_code": "GEO-YAW"}),
            json.dumps({"timestamp_utc": "2026-11-19T08:05:00Z", "event_type": "qc_frame_dwell", "job_id": 5001, "task_id": 101, "username": "qc1_a", "params": {"dwell_ms": 1500}}),
        ])
        bf1 = self.client.post("/api/qc-events/backfill/", {"jsonl": jsonl}, format="json")
        self.assertEqual(bf1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(bf1.data["created"], 2)

        bf2 = self.client.post("/api/qc-events/backfill/", {"jsonl": jsonl}, format="json")
        self.assertEqual(bf2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(bf2.data["created"], 0)
        self.assertEqual(bf2.data["skipped_duplicates"], 2)

        act = self.client.get("/api/qc-events/activity/?days=30&task_id=101")
        self.assertEqual(act.status_code, status.HTTP_200_OK)
        self.assertTrue(act.data["transactional"])
        self.assertEqual(act.data["totals"]["qc_events"], 3)
        self.assertEqual(act.data["totals"]["dwell_ms"], 5000)
        self.assertEqual(act.data["defect_codes"][0]["code"], "GEO-YAW")

    def test_annotator_rbac_restrictions_and_client_event_isolation(self) -> None:
        # Create a non-staff Django user linked to Annotator A (`u_ann`, is_qc=False)
        dj_ann = User.objects.create_user(
            username="ann_a", password="pw", is_staff=False, is_superuser=False
        )
        self.u_ann.django_user = dj_ann
        self.u_ann.save(update_fields=["django_user"])
        self.client.force_authenticate(user=dj_ann)

        # 1. Annotator cannot distribute batches, create teams, or run QC1/QC2 actions
        r_dist = self.client.post("/api/workflow/batches/b01/distribute/", {"teamIds": ["t1"]}, format="json")
        self.assertEqual(r_dist.status_code, status.HTTP_403_FORBIDDEN)

        r_team = self.client.post(
            "/api/workflow/teams/",
            {"name": "Rogue Team", "allowedSteps": ["annotate"], "canQa": False},
            format="json",
        )
        self.assertEqual(r_team.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Annotator cannot view anti-gaming scorecard, QC activity analytics, or run JSONL backfill
        self.assertEqual(self.client.get("/api/scorecard/").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get("/api/qc-events/activity/").status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(
            self.client.post("/api/qc-events/backfill/", {"events": []}, format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(
                "/api/delivery-batches/",
                {"batch_code": "B-ROGUE", "title": "Rogue"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # 3. Annotator posting a raw event or `client_*` event cannot trigger workflow stage side effects
        self.job1.team = self.team
        self.job1.annotator = self.u_ann
        self.job1.stage = WorkflowJobStage.ANNO_IN_PROGRESS
        self.job1.save()

        r_spoof = self.client.post(
            "/api/qc-events/",
            {
                "idempotency_key": "spoof_submit_5001",
                "scope": "qc:job_submitted",
                "job_id": 5001,
                "username": "ann_a",
            },
            format="json",
        )
        self.assertEqual(r_spoof.status_code, status.HTTP_201_CREATED)
        self.assertFalse(r_spoof.data["event"]["applied_to_workflow"])
        self.job1.refresh_from_db()
        self.assertEqual(self.job1.stage, WorkflowJobStage.ANNO_IN_PROGRESS)

        # Even as admin, a `client_*` telemetry event never mutates workflow stage
        self.client.force_authenticate(user=self.dj_admin)
        r_client_ev = self.client.post(
            "/api/qc-events/",
            {
                "idempotency_key": "client_telemetry_5001",
                "event_type": "client_job_submitted",
                "job_id": 5001,
                "username": "ann_a",
                "params": {"action": "escalate_l2"},
            },
            format="json",
        )
        self.assertEqual(r_client_ev.status_code, status.HTTP_201_CREATED)
        self.assertFalse(r_client_ev.data["event"]["applied_to_workflow"])
        self.job1.refresh_from_db()
        self.assertEqual(self.job1.stage, WorkflowJobStage.ANNO_IN_PROGRESS)

    @override_settings(CVAT_WEBHOOK_SECRET="stage_hook_secret")
    def test_cvat_stage_webhook_supports_cvat_signature_header_and_idempotency(self) -> None:
        self.client.force_authenticate(user=None)
        body = json.dumps({
            "event_id": "evt_stage_5001_1",
            "job_id": 5001,
            "task_id": 101,
            "event": "stage.submitted",
            "from_step": "annotator",
            "to_step": "l1_qc",
            "actor": "ann_a",
            "actor_role": "annotator",
        }).encode("utf-8")
        sig = "sha256=" + hmac.new(b"stage_hook_secret", body, hashlib.sha256).hexdigest()

        r1 = self.client.post(
            "/api/webhooks/cvat-stage/",
            data=body,
            content_type="application/json",
            HTTP_X_CVAT_SIGNATURE_256=sig,
        )
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        self.assertEqual(r1.data["status"], "received")

        # Replay with same event_id is idempotent
        r2 = self.client.post(
            "/api/webhooks/cvat-stage/",
            data=body,
            content_type="application/json",
            HTTP_X_CVAT_SIGNATURE_256=sig,
        )
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.data["status"], "duplicate_ignored")
        self.assertEqual(self.sjob1.transitions.filter(event_id="evt_stage_5001_1").count(), 1)
