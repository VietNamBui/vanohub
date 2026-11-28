from __future__ import annotations

from datetime import timedelta
from typing import Any

from dashboard.models import (
    Dimension,
    WorkflowBatch,
    WorkflowBatchEvent,
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
from dashboard.qc_events import record_qc_event_transactional
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds normalized 2D & 3D workflow data + transactional QcEvents for the React dashboard."

    def handle(self, *args: Any, **options: Any) -> None:
        now = timezone.now()

        with transaction.atomic():
            # 1. DataTypes (3D Cuboid + 2D BBox)
            dt3d, _ = WorkflowDataType.objects.update_or_create(
                code="dt3d",
                defaults={
                    "name": "LiDAR 3D Cuboid",
                    "dimension": Dimension.DIM_3D,
                    "shape_type": "cuboid",
                    "kpi_per_day": 1200,
                    "threshold_cm": 5.0,
                    "threshold_deg": 3.0,
                    "error_categories": [
                        "Sai kích thước",
                        "Sai hướng (Yaw)",
                        "Thiếu object",
                        "Nhầm nhãn",
                        "Thuộc tính occluded",
                    ],
                },
            )
            dt2d, _ = WorkflowDataType.objects.update_or_create(
                code="dt2d",
                defaults={
                    "name": "2D Bounding Box",
                    "dimension": Dimension.DIM_2D,
                    "shape_type": "rectangle",
                    "kpi_per_day": 3000,
                    "threshold_cm": 2.0,
                    "threshold_deg": 0.0,
                    "error_categories": [
                        "Khung vượt biên",
                        "Box trùng lặp",
                        "Thiếu object",
                        "Nhầm nhãn",
                        "Sai landmark",
                    ],
                },
            )

            # 2. Users (linked to Django auth users so /api/auth/login/ works directly)
            user_specs = [
                ("u1", "Nguyễn Quản Trị", "admin_cvat", WorkflowRole.ADMIN, True, 1001, True),
                ("u2", "Trần Minh PM", "pm_minh", WorkflowRole.PM, True, 1002, True),
                ("u3", "Lê Hoàng Lead", "lead_alpha", WorkflowRole.LEAD, True, 2001, False),
                ("u4", "Phạm Quang Lead", "lead_beta", WorkflowRole.LEAD, True, 2002, False),
                ("u5", "Vũ Thị QC1", "qc_alpha", WorkflowRole.ANNOTATOR, True, 2101, False),
                ("u6", "Đặng Văn QC1", "qc_beta", WorkflowRole.ANNOTATOR, True, 2102, False),
                ("u7", "Bùi Anh Annotator", "ann_anh", WorkflowRole.ANNOTATOR, False, 3001, False),
                ("u8", "Đỗ Bình Annotator", "ann_binh", WorkflowRole.ANNOTATOR, False, 3002, False),
                ("u9", "Ngô Chi Annotator", "ann_chi", WorkflowRole.ANNOTATOR, False, 3003, False),
                ("u10", "Hoàng Dũng Annotator", "ann_dung", WorkflowRole.ANNOTATOR, False, 3004, False),
            ]
            users: dict[str, WorkflowUser] = {}
            for code, name, uname, role, is_qc, emp_id, is_staff in user_specs:
                dj_user, _ = User.objects.get_or_create(
                    username=uname,
                    defaults={"email": f"{uname}@company.local", "is_staff": is_staff, "is_superuser": role == WorkflowRole.ADMIN},
                )
                dj_user.set_password("dashboard123")
                dj_user.save()
                wf_u, _ = WorkflowUser.objects.update_or_create(
                    code=code,
                    defaults={
                        "django_user": dj_user,
                        "name": name,
                        "cvat_username": uname,
                        "role": role,
                        "is_qc": is_qc,
                        "employee_id": emp_id,
                    },
                )
                users[code] = wf_u

            # Also link existing qa_manager / qc_lead if present
            qa_mgr = User.objects.filter(username="qa_manager").first()
            if qa_mgr and not WorkflowUser.objects.filter(django_user=qa_mgr).exists():
                WorkflowUser.objects.update_or_create(
                    code="u_qa_manager",
                    defaults={
                        "django_user": qa_mgr,
                        "name": "QA Manager",
                        "cvat_username": "qa_manager",
                        "role": WorkflowRole.ADMIN,
                        "is_qc": True,
                        "employee_id": 1000,
                    },
                )

            # 3. Teams
            t1, _ = WorkflowTeam.objects.update_or_create(
                code="t1",
                defaults={"name": "Team Alpha (3D)", "lead": users["u3"], "pm": users["u2"], "allowed_steps": ["annotate", "qc1", "qc2"], "can_qa": True},
            )
            t1.members.set([users["u3"], users["u5"], users["u7"], users["u8"]])

            t2, _ = WorkflowTeam.objects.update_or_create(
                code="t2",
                defaults={"name": "Team Beta (2D & 3D)", "lead": users["u4"], "pm": users["u2"], "allowed_steps": ["annotate", "qc1"], "can_qa": False},
            )
            t2.members.set([users["u4"], users["u6"], users["u9"], users["u10"]])

            # 4. Projects
            p1, _ = WorkflowProject.objects.update_or_create(
                code="p1",
                defaults={
                    "display_code": "PRJ-P1-301",
                    "name": "Autonomous LiDAR 3D L4",
                    "data_type": dt3d,
                    "pm_order": ["u2"],
                    "partner": {"name": "AutoDrive Lab", "contact": "Chị Minh Anh", "email": "contact@autodrive.example", "contractNote": "Giao lô hàng tuần"},
                    "assigned_at": now - timedelta(days=25),
                    "due_at": now + timedelta(days=20),
                    "status": WorkflowProject.Status.RUNNING,
                },
            )
            p1.pms.set([users["u2"]])
            p1.teams.set([t1, t2])

            p2, _ = WorkflowProject.objects.update_or_create(
                code="p2",
                defaults={
                    "display_code": "PRJ-P2-201",
                    "name": "Urban Perception 2D BBox",
                    "data_type": dt2d,
                    "pm_order": ["u2"],
                    "partner": {"name": "Urban Vision", "contact": "Ms. Lan", "email": "lan@urbanvision.example", "contractNote": "Kiểm thu mẫu 30%"},
                    "assigned_at": now - timedelta(days=18),
                    "due_at": now + timedelta(days=15),
                    "status": WorkflowProject.Status.RUNNING,
                },
            )
            p2.pms.set([users["u2"]])
            p2.teams.set([t2])

            # 5. Datasets & Batches
            d1, _ = WorkflowDataset.objects.update_or_create(
                code="d1",
                defaults={
                    "name": "Waymo_Highway_Batch_01",
                    "nas_path": "/nas/lidar/waymo_01",
                    "data_type": dt3d,
                    "project": p1,
                    "file_count": 1200,
                    "frame_count": 1200,
                    "received_at": now - timedelta(days=10),
                    "last_distributed_at": now - timedelta(days=5),
                    "due_at": now + timedelta(days=10),
                    "preprocessed_pct": 100,
                    "on_cvat_pct": 100,
                    "scene_count": 42,
                    "partner_note": "Ưu tiên cảnh đêm",
                },
            )
            d2, _ = WorkflowDataset.objects.update_or_create(
                code="d2",
                defaults={
                    "name": "BDD100K_Urban_2D_01",
                    "nas_path": "/nas/2d/bdd100k_01",
                    "data_type": dt2d,
                    "project": p2,
                    "file_count": 2000,
                    "frame_count": 2000,
                    "received_at": now - timedelta(days=8),
                    "last_distributed_at": now - timedelta(days=3),
                    "due_at": now + timedelta(days=7),
                    "preprocessed_pct": 100,
                    "on_cvat_pct": 95,
                    "scene_count": 65,
                    "partner_note": "Kiểm tra kỹ nhãn rider",
                },
            )

            b01, _ = WorkflowBatch.objects.update_or_create(
                code="b01",
                defaults={
                    "name": "Task 3D Urban #101",
                    "dataset": d1,
                    "project": p1,
                    "team": t1,
                    "cvat_task_id": 101,
                    "status": WorkflowBatchStatus.IN_PROGRESS,
                    "step_pic": {"annotate": ["t1", "t2"], "qc1": "u5", "qc2": "u2"},
                    "due_at": now + timedelta(days=5),
                    "step_buffer_days": {"qc1": 1, "qc2": 1},
                    "priority": 4,
                },
            )
            b02, _ = WorkflowBatch.objects.update_or_create(
                code="b02",
                defaults={
                    "name": "Task 3D Unassigned #102",
                    "dataset": d1,
                    "project": p1,
                    "team": None,
                    "cvat_task_id": 102,
                    "status": WorkflowBatchStatus.PENDING,
                    "step_pic": {},
                    "due_at": now + timedelta(days=8),
                    "step_buffer_days": {"qc1": 1, "qc2": 1},
                    "priority": 5,
                },
            )
            b03, _ = WorkflowBatch.objects.update_or_create(
                code="b03",
                defaults={
                    "name": "Task 2D Urban #201",
                    "dataset": d2,
                    "project": p2,
                    "team": t2,
                    "cvat_task_id": 201,
                    "status": WorkflowBatchStatus.IN_PROGRESS,
                    "step_pic": {"annotate": ["t2"], "qc1": "u6", "qc2": "u2"},
                    "due_at": now + timedelta(days=4),
                    "step_buffer_days": {"qc1": 1, "qc2": 1},
                    "priority": 3,
                },
            )

            # 6. Jobs across all stages
            job_specs = [
                ("j0001", 1001, b01, p1, t1, users["u7"], users["u5"], None, WorkflowJobStage.ANNO_IN_PROGRESS, 420, 0, 100, 0, None, ""),
                ("j0002", 1002, b01, p1, t1, users["u8"], users["u5"], None, WorkflowJobStage.QC1_PENDING, 380, 160, 100, 0, now - timedelta(hours=6), ""),
                ("j0003", 1003, b01, p1, t1, users["u7"], users["u5"], None, WorkflowJobStage.QC2_PENDING, 450, 210, 100, 1, now - timedelta(hours=18), ""),
                ("j0004", 1004, b01, p1, t1, users["u8"], users["u5"], users["u2"], WorkflowJobStage.READY_TO_DELIVER, 400, 190, 100, 0, now - timedelta(days=1), ""),
                ("j0005", 1005, b01, p1, t1, users["u7"], users["u5"], users["u2"], WorkflowJobStage.DELIVERED, 390, 175, 100, 0, now - timedelta(days=2), ""),
                ("j0006", 1006, b01, p1, t1, None, None, None, WorkflowJobStage.TEAM_POOL, 410, 0, 100, 0, None, "CVAT stage lệch: validation vs team_pool"),
                # Unassigned batch b02 for DistributePage
                ("j0007", 1007, b02, p1, None, None, None, None, WorkflowJobStage.UNASSIGNED_POOL, 500, 0, 100, 0, None, ""),
                ("j0008", 1008, b02, p1, None, None, None, None, WorkflowJobStage.UNASSIGNED_POOL, 320, 0, 100, 0, None, ""),
                ("j0009", 1009, b02, p1, None, None, None, None, WorkflowJobStage.UNASSIGNED_POOL, 440, 0, 100, 0, None, ""),
                ("j0010", 1010, b02, p1, None, None, None, None, WorkflowJobStage.UNASSIGNED_POOL, 280, 0, 100, 0, None, ""),
                # 2D batch b03
                ("j0011", 2001, b03, p2, t2, users["u9"], users["u6"], None, WorkflowJobStage.ANNO_IN_PROGRESS, 920, 0, 200, 0, None, ""),
                ("j0012", 2002, b03, p2, t2, users["u10"], users["u6"], None, WorkflowJobStage.QC1_PENDING, 880, 410, 200, 0, now - timedelta(hours=5), ""),
                ("j0013", 2003, b03, p2, t2, users["u9"], users["u6"], None, WorkflowJobStage.QC2_PENDING, 950, 460, 200, 0, now - timedelta(hours=12), ""),
                ("j0014", 2004, b03, p2, t2, users["u10"], users["u6"], users["u2"], WorkflowJobStage.READY_TO_DELIVER, 900, 430, 200, 0, now - timedelta(days=1), ""),
            ]
            jobs: dict[str, WorkflowJob] = {}
            for code, cj, batch, proj, team, ann, qc1, qc2, stg, pre, ed, fr, rw, fsub, drift in job_specs:
                j, _ = WorkflowJob.objects.update_or_create(
                    code=code,
                    defaults={
                        "cvat_job_id": cj,
                        "batch": batch,
                        "project": proj,
                        "team": team,
                        "annotator": ann,
                        "qc1": qc1,
                        "qc2": qc2,
                        "stage": stg,
                        "prelabel_cuboids": pre,
                        "edited_cuboids": ed,
                        "frames": fr,
                        "rework_count": rw,
                        "first_submitted_at": fsub,
                        "cvat_drift": drift,
                    },
                )
                jobs[code] = j

            # 7. Seed sample JobEvents + KpiDaily
            if not WorkflowJobEvent.objects.exists():
                WorkflowJobEvent.objects.create(
                    code="ev00001", job=jobs["j0002"], at=now - timedelta(hours=6),
                    actor=users["u8"], actor_code="u8", type="submit",
                    from_stage=WorkflowJobStage.ANNO_IN_PROGRESS, to_stage=WorkflowJobStage.QC1_PENDING,
                )
                WorkflowJobEvent.objects.create(
                    code="ev00002", job=jobs["j0003"], at=now - timedelta(hours=22),
                    actor=users["u7"], actor_code="u7", type="submit",
                    from_stage=WorkflowJobStage.ANNO_IN_PROGRESS, to_stage=WorkflowJobStage.QC1_PENDING,
                )
                WorkflowJobEvent.objects.create(
                    code="ev00003", job=jobs["j0003"], at=now - timedelta(hours=20),
                    actor=users["u5"], actor_code="u5", type="qc1_return",
                    from_stage=WorkflowJobStage.QC1_IN_PROGRESS, to_stage=WorkflowJobStage.ANNO_IN_PROGRESS,
                    reason="Lệch góc Yaw xe ở frame 45", error_category="Sai hướng (Yaw)", rework_against=["u7"],
                )
                WorkflowJobEvent.objects.create(
                    code="ev00004", job=jobs["j0003"], at=now - timedelta(hours=18),
                    actor=users["u7"], actor_code="u7", type="resubmit",
                    from_stage=WorkflowJobStage.ANNO_IN_PROGRESS, to_stage=WorkflowJobStage.QC1_PENDING,
                )
                WorkflowJobEvent.objects.create(
                    code="ev00005", job=jobs["j0003"], at=now - timedelta(hours=16),
                    actor=users["u5"], actor_code="u5", type="qc1_pass",
                    from_stage=WorkflowJobStage.QC1_IN_PROGRESS, to_stage=WorkflowJobStage.QC2_PENDING,
                )
                WorkflowJobEvent.objects.create(
                    code="ev00006", job=jobs["j0013"], at=now - timedelta(hours=12),
                    actor=users["u9"], actor_code="u9", type="submit",
                    from_stage=WorkflowJobStage.ANNO_IN_PROGRESS, to_stage=WorkflowJobStage.QC1_PENDING,
                )
                WorkflowJobEvent.objects.create(
                    code="ev00007", job=jobs["j0013"], at=now - timedelta(hours=10),
                    actor=users["u6"], actor_code="u6", type="qc1_pass",
                    from_stage=WorkflowJobStage.QC1_IN_PROGRESS, to_stage=WorkflowJobStage.QC2_PENDING,
                )

            if not WorkflowBatchEvent.objects.exists():
                WorkflowBatchEvent.objects.create(
                    code="be0001", batch=b01, at=now - timedelta(days=5),
                    actor=users["u2"], actor_code="u2", type="distribute",
                    detail="Chia 6 job cho Team Alpha (3D)",
                )

            for offset in range(7):
                day = (now - timedelta(days=offset)).date()
                for ucode, val in (("u7", 1180), ("u8", 1260), ("u9", 2950), ("u10", 3120)):
                    WorkflowKpiDaily.objects.update_or_create(
                        user=users[ucode],
                        date=day,
                        defaults={"edited_cuboids": val + offset * 25},
                    )

            # 8. Seed sample transactional QcEvents (idempotent)
            sample_qc_events = [
                {
                    "idempotency_key": "seed_qc_preqc_1001",
                    "scope": "qc:preqc_ingest",
                    "job_id": 1001,
                    "task_id": 101,
                    "stage": "annotation",
                    "actor_role": "bot",
                    "username": "preqc_bot",
                    "issue_id": 9001,
                    "defect_code": "GEO-HDG",
                    "severity": "major",
                    "frame_number": 12,
                },
                {
                    "idempotency_key": "seed_qc_submit_1002",
                    "scope": "qc:job_submitted",
                    "job_id": 1002,
                    "task_id": 101,
                    "stage": "validation",
                    "actor_role": "annotator",
                    "username": "ann_binh",
                },
                {
                    "idempotency_key": "seed_qc_dwell_1002",
                    "scope": "qc:qc_frame_dwell",
                    "job_id": 1002,
                    "task_id": 101,
                    "stage": "validation",
                    "actor_role": "l1_qc",
                    "username": "qc_alpha",
                    "frame_number": 24,
                    "params": {"dwell_ms": 4200, "track_ids": [11, 14]},
                },
            ]
            for ev in sample_qc_events:
                record_qc_event_transactional(ev, apply_side_effects=False)

        self.stdout.write(self.style.SUCCESS("Workflow & transactional QcEvent demo data seeded successfully!"))
        self.stdout.write("Demo workflow users (password: dashboard123): admin_cvat, pm_minh, lead_alpha, qc_alpha, ann_anh")
