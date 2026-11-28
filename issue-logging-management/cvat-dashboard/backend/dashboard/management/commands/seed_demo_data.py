from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from dashboard.models import (
    BatchDimension,
    DailyUserMetrics,
    DefectRecord,
    DeliverStatus,
    DeliveryBatch,
    DeliveryBatchItem,
    Dimension,
    JobQualitySnapshot,
    PipelineStep,
    StageTransition,
    SyncedJob,
    SyncedTask,
)
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

User = get_user_model()


class Command(BaseCommand):
    help = "Seeds comprehensive demo data for CVAT Internal QA/QC Data Cycle Dashboard"

    def handle(self, *args: Any, **options: Any) -> None:
        self.stdout.write("Creating demo staff & reviewers...")

        # 1. Users
        qa_manager, _ = User.objects.get_or_create(
            username="qa_manager",
            defaults={"email": "qa_manager@company.local", "is_staff": True, "is_superuser": True},
        )
        qa_manager.set_password("dashboard123")
        qa_manager.save()

        qc_lead, _ = User.objects.get_or_create(
            username="qc_lead",
            defaults={"email": "qc_lead@company.local", "is_staff": False, "is_superuser": False},
        )
        qc_lead.set_password("dashboard123")
        qc_lead.save()

        annotators = ["annotator_anh", "annotator_binh", "annotator_chi", "annotator_dung"]
        reviewers_l1 = ["qc_duc", "qc_giang"]
        reviewers_l2 = ["qc_lead", "dept_head_hai"]

        for u in annotators + reviewers_l1 + reviewers_l2:
            usr, _ = User.objects.get_or_create(username=u, defaults={"email": f"{u}@company.local"})
            usr.set_password("dashboard123")
            usr.save()

        now = timezone.now()

        # 2. Tasks (3D LiDAR + 2D BBox & DMS Landmark)
        t1, _ = SyncedTask.objects.update_or_create(
            cvat_task_id=101,
            defaults={
                "name": "Highway_LiDAR_Urban_01",
                "project_name": "Autonomous_3D_L4",
                "dimension": Dimension.DIM_3D,
                "annotation_type": "cuboid",
                "total_frames": 1200,
            },
        )
        t2, _ = SyncedTask.objects.update_or_create(
            cvat_task_id=102,
            defaults={
                "name": "Intersection_Dense_Rain_02",
                "project_name": "Autonomous_3D_L4",
                "dimension": Dimension.DIM_3D,
                "annotation_type": "cuboid",
                "total_frames": 800,
            },
        )
        t3, _ = SyncedTask.objects.update_or_create(
            cvat_task_id=201,
            defaults={
                "name": "BDD100K_Urban_2D_BBox_01",
                "project_name": "Perception_2D_BBox",
                "dimension": Dimension.DIM_2D,
                "annotation_type": "bbox",
                "total_frames": 1000,
            },
        )
        t4, _ = SyncedTask.objects.update_or_create(
            cvat_task_id=202,
            defaults={
                "name": "DMS_Facial_Landmarks_02",
                "project_name": "Cabin_DMS_2D",
                "dimension": Dimension.DIM_2D,
                "annotation_type": "skeleton",
                "total_frames": 600,
            },
        )

        # 3. Jobs across all stages (3D + 2D)
        job_specs = [
            # 3D jobs
            (1001, t1, 0, 99, 100, PipelineStep.PRE_QC, DeliverStatus.NOT_READY, "annotator_anh", "qc_duc", "qc_lead", 1, 0),
            (1002, t1, 100, 199, 100, PipelineStep.PRE_QC, DeliverStatus.NOT_READY, "annotator_binh", "qc_giang", "dept_head_hai", 1, 0),
            (1003, t1, 200, 299, 100, PipelineStep.ANNOTATOR, DeliverStatus.NOT_READY, "annotator_anh", "qc_duc", "qc_lead", 1, 0),
            (1004, t1, 300, 399, 100, PipelineStep.ANNOTATOR, DeliverStatus.NOT_READY, "annotator_chi", "qc_giang", "qc_lead", 2, 1),
            (1005, t2, 0, 99, 100, PipelineStep.ANNOTATOR, DeliverStatus.NOT_READY, "annotator_dung", "qc_duc", "dept_head_hai", 1, 0),
            (1006, t1, 400, 499, 100, PipelineStep.L1_QC, DeliverStatus.NOT_READY, "annotator_binh", "qc_duc", "qc_lead", 1, 0),
            (1007, t2, 100, 199, 100, PipelineStep.L1_QC, DeliverStatus.NOT_READY, "annotator_anh", "qc_giang", "qc_lead", 1, 0),
            (1008, t1, 500, 599, 100, PipelineStep.L2_QC, DeliverStatus.NOT_READY, "annotator_chi", "qc_duc", "qc_lead", 1, 0),
            (1009, t2, 200, 299, 100, PipelineStep.DEPT_HEAD, DeliverStatus.NOT_READY, "annotator_dung", "qc_giang", "dept_head_hai", 2, 1),
            (1010, t1, 600, 699, 100, PipelineStep.COMPLETED, DeliverStatus.READY, "annotator_anh", "qc_duc", "qc_lead", 1, 0),
            (1011, t1, 700, 799, 100, PipelineStep.COMPLETED, DeliverStatus.READY, "annotator_binh", "qc_giang", "dept_head_hai", 1, 0),
            (1012, t2, 300, 399, 100, PipelineStep.COMPLETED, DeliverStatus.IN_BATCH, "annotator_chi", "qc_duc", "qc_lead", 1, 0),
            # 2D jobs
            (2001, t3, 0, 199, 200, PipelineStep.PRE_QC, DeliverStatus.NOT_READY, "annotator_anh", "qc_duc", "qc_lead", 1, 0),
            (2002, t3, 200, 399, 200, PipelineStep.ANNOTATOR, DeliverStatus.NOT_READY, "annotator_binh", "qc_giang", "qc_lead", 2, 1),
            (2003, t3, 400, 599, 200, PipelineStep.L1_QC, DeliverStatus.NOT_READY, "annotator_chi", "qc_duc", "qc_lead", 1, 0),
            (2004, t4, 0, 199, 200, PipelineStep.L2_QC, DeliverStatus.NOT_READY, "annotator_dung", "qc_giang", "dept_head_hai", 1, 0),
            (2005, t4, 200, 399, 200, PipelineStep.COMPLETED, DeliverStatus.READY, "annotator_anh", "qc_duc", "qc_lead", 1, 0),
            (2006, t3, 600, 799, 200, PipelineStep.COMPLETED, DeliverStatus.IN_BATCH, "annotator_binh", "qc_giang", "dept_head_hai", 1, 0),
        ]

        created_jobs = []
        for jid, task_obj, sf, ef, fc, step, dstat, ann, l1, l2, rr, rc in job_specs:
            job, _ = SyncedJob.objects.update_or_create(
                cvat_job_id=jid,
                defaults={
                    "task": task_obj,
                    "start_frame": sf,
                    "stop_frame": ef,
                    "frame_count": fc,
                    "pipeline_step": step,
                    "deliver_status": dstat,
                    "annotator_username": ann,
                    "l1_qc_username": l1,
                    "l2_qc_username": l2,
                    "review_round": rr,
                    "rework_count": rc,
                    "open_issues": 0 if step == PipelineStep.COMPLETED else (2 if rc > 0 else 1),
                    "inspected_cuboids": 120 if step in (PipelineStep.COMPLETED, PipelineStep.L2_QC) else 60,
                    "required_cuboids": 100,
                    "total_cuboids": 150,
                    "threshold_met": True,
                    "step_entered_at": now - timedelta(hours=random.randint(2, 36)),
                },
            )
            created_jobs.append(job)

        # 4. Transitions & Lead times
        for job in created_jobs:
            StageTransition.objects.get_or_create(
                job=job,
                from_step="annotator",
                to_step="l1_qc",
                defaults={
                    "event_name": "stage.submitted",
                    "actor_username": job.annotator_username,
                    "actor_role": "annotator",
                    "occurred_at": now - timedelta(hours=14),
                    "duration_prev_step_sec": 3600 * 18,
                },
            )
            if job.rework_count > 0:
                StageTransition.objects.get_or_create(
                    job=job,
                    from_step="l1_qc",
                    to_step="annotator",
                    defaults={
                        "event_name": "stage.returned",
                        "actor_username": job.l1_qc_username,
                        "actor_role": "l1_qc",
                        "reason": "Sai lệch góc Yaw hộp cuboid và thiếu gán nhãn xe bị che khuất",
                        "occurred_at": now - timedelta(hours=10),
                        "duration_prev_step_sec": 3600 * 4,
                    },
                )

        # 5. Quality Snapshots with Anti-Gaming flags (3D + 2D geometry metrics)
        for job in created_jobs:
            is_suspect = job.cvat_job_id in (1004, 1005, 2002)
            is_2d = job.task.dimension == Dimension.DIM_2D
            geom = (
                {
                    "mean_iou_2d": 0.74 if is_suspect else 0.91,
                    "mean_center_shift_px": 14.5 if is_suspect else 3.2,
                    "mean_landmark_err_px": 6.8 if is_suspect else 1.4,
                    "out_of_bounds_count": 3 if is_suspect else 0,
                }
                if is_2d
                else {
                    "mean_bev_iou": 0.79 if is_suspect else 0.90,
                }
            )
            JobQualitySnapshot.objects.update_or_create(
                job=job,
                defaults={
                    "total_source_boxes": 260 if is_2d else 140,
                    "added_boxes": 24 if is_2d else 12,
                    "deleted_boxes": 8 if is_suspect else 2,
                    "unchanged_boxes": 210 if is_2d else 120,
                    "modified_boxes": (20 if is_2d else 10) if not is_suspect else 1,
                    "touched_rate": 0.05 if is_suspect else 0.42,
                    "source_box_touch_rate": 0.04 if is_suspect else 0.38,
                    "effort_score": 0.15 if is_suspect else 0.88,
                    "rubber_stamp_strata_suspect": is_suspect,
                    "attr_modified_count": 0 if is_suspect else 15,
                    "attr_edit_rate": 0.01 if is_suspect else 0.22,
                    "attr_missed_count": 4 if is_suspect else 0,
                    "rubber_stamp_suspects": 2 if is_suspect else 0,
                    "issues_tp": 18,
                    "issues_fp": 2,
                    "s0_deleted_count": 6 if is_suspect else 0,
                    "suspicious_deletion_count": 3 if is_suspect else 0,
                    "track_continuity_ratio": 0.78 if is_suspect else 0.99,
                    "track_id_switch_count": 3 if is_suspect else 0,
                    "l1_escape_count": 1 if is_suspect else 0,
                    "mean_dl_m": 0.0 if is_2d else (0.18 if is_suspect else 0.06),
                    "mean_dw_m": 0.0 if is_2d else (0.12 if is_suspect else 0.04),
                    "mean_dh_m": 0.0 if is_2d else (0.14 if is_suspect else 0.05),
                    "mean_center_shift_m": 0.0 if is_2d else (0.24 if is_suspect else 0.08),
                    "mean_abs_yaw_deg": 0.0 if is_2d else (8.4 if is_suspect else 2.1),
                    "drift_warning": is_suspect,
                    "geometry_metrics": geom,
                    "honeypot_evaluated": True,
                    "honeypot_passed": not is_suspect,
                    "honeypot_mean_iou": (0.76 if is_suspect else 0.91) if is_2d else (0.72 if is_suspect else 0.86),
                    "honeypot_mean_iou_3d": None if is_2d else (0.72 if is_suspect else 0.86),
                    "ruling_agreed_count": 8,
                    "ruling_disagreed_count": 1,
                },
            )

        # 6. Daily Productivity Metrics (last 7 days, both 3D and 2D)
        for i in range(7):
            d = now.date() - timedelta(days=i)
            for dim in (Dimension.DIM_3D, Dimension.DIM_2D):
                scale = 2 if dim == Dimension.DIM_2D else 1
                for ann in annotators:
                    DailyUserMetrics.objects.update_or_create(
                        date=d,
                        username=ann,
                        role="annotator",
                        dimension=dim,
                        defaults={
                            "jobs_submitted": random.randint(2, 5),
                            "frames_processed": random.randint(150, 400) * scale,
                            "cuboids_inspected": random.randint(200, 600) * scale,
                            "working_time_ms": random.randint(5 * 3600000, 8 * 3600000),
                        },
                    )
                for qc in reviewers_l1:
                    DailyUserMetrics.objects.update_or_create(
                        date=d,
                        username=qc,
                        role="l1_qc",
                        dimension=dim,
                        defaults={
                            "jobs_accepted_l1": random.randint(3, 7),
                            "jobs_returned_rework": random.randint(0, 2),
                            "frames_processed": random.randint(200, 500) * scale,
                            "cuboids_inspected": random.randint(300, 700) * scale,
                            "working_time_ms": random.randint(6 * 3600000, 8 * 3600000),
                        },
                    )

        # 7. E1..E6 Defect Records (3D + 2D)
        defect_specs = [
            # 3D defects
            (2001, 1006, 12, "E1", "E101_DIM_ERROR", "major", "Sai kích thước dài/rộng/cao quá ngưỡng 15cm"),
            (2002, 1006, 15, "E1", "E102_YAW_ERROR", "major", "Lệch hướng xoay Yaw trên 5 độ"),
            (2003, 1007, 24, "E2", "E201_FALSE_POSITIVE", "minor", "Hộp thừa gán nhãn vào nhiễu phản xạ điểm LiDAR"),
            (2004, 1008, 45, "E3", "E301_MISSED_BOX", "critical", "Bỏ sót người đi bộ sát lề đường"),
            (2005, 1009, 80, "E4", "E401_ATTR_MISSED", "minor", "Không đánh dấu cờ Occluded khi bị xe tải che một nửa"),
            (2006, 1004, 30, "E5", "E501_TRACK_SWITCH", "major", "Track ID bị nhảy sang phương tiện đối diện"),
            (2007, 1004, 32, "E6", "E601_WRONG_CLASS", "critical", "Nhầm phân lớp Truck thành Car"),
            # 2D defects
            (3001, 2002, 18, "E1", "BDD_BOX_OUT_OF_BOUNDS", "major", "Khung 2D vượt quá biên ảnh 1280x720"),
            (3002, 2003, 42, "E2", "BDD_DUPLICATE_BOX", "minor", "Hai khung 2D chồng lấn trên cùng phương tiện"),
            (3003, 2003, 55, "E3", "BDD_MISSED_OBJECT", "critical", "Bỏ sót người đi bộ ở làn đường bên phải"),
            (3004, 2004, 14, "E5", "DMS_001_EYEBROW_ORDER", "major", "Thứ tự landmark lông mày trái bị đảo ngược"),
            (3005, 2004, 22, "E4", "DMS_OCC_ATTR_MISSED", "minor", "Thiếu trạng thái mắt nhắm / che khuất"),
        ]
        job_map = {j.cvat_job_id: j for j in created_jobs}
        for cid, jid, f, cat, code, sev, summ in defect_specs:
            if jid in job_map:
                DefectRecord.objects.update_or_create(
                    cvat_issue_id=cid,
                    defaults={
                        "job": job_map[jid],
                        "frame": f,
                        "primary_category": cat,
                        "defect_code": code,
                        "severity": sev,
                        "summary_text": summ,
                        "root_cause": "Sensor Glare" if cat == "E2" else "Human Oversight",
                        "annotator_username": job_map[jid].annotator_username,
                        "owner_username": job_map[jid].l1_qc_username,
                    },
                )

        # 8. Delivery Batches (3D + 2D)
        b1, _ = DeliveryBatch.objects.update_or_create(
            batch_code="BATCH-202611-L4-01",
            defaults={
                "title": "Gói nghiệm thu bàn giao đợt 1 - Autonomous L4 (3D)",
                "client_name": "Tier-1 Autonomous OEM",
                "dimension": BatchDimension.DIM_3D,
                "status": DeliveryBatch.Status.DRAFT,
                "notes": "Kiểm định 100% chuẩn bàn giao không còn issue mở",
                "created_by": qa_manager,
            },
        )
        for jid in (1010, 1011):
            if jid in job_map:
                DeliveryBatchItem.objects.get_or_create(
                    batch=b1,
                    job=job_map[jid],
                    defaults={"gate_passed": True, "gate_blockers": []},
                )

        b2, _ = DeliveryBatch.objects.update_or_create(
            batch_code="BATCH-202611-2D-01",
            defaults={
                "title": "Gói nghiệm thu bàn giao đợt 1 - Perception & DMS (2D)",
                "client_name": "Cabin Vision OEM",
                "dimension": BatchDimension.DIM_2D,
                "status": DeliveryBatch.Status.DRAFT,
                "notes": "Kiểm định 2D BBox + DMS Landmarks",
                "created_by": qa_manager,
            },
        )
        for jid in (2005, 2006):
            if jid in job_map:
                DeliveryBatchItem.objects.get_or_create(
                    batch=b2,
                    job=job_map[jid],
                    defaults={"gate_passed": True, "gate_blockers": []},
                )

        self.stdout.write(self.style.SUCCESS("Demo data seeded successfully!"))
        self.stdout.write("Credentials: qa_manager / dashboard123 (staff) and qc_lead / dashboard123")
