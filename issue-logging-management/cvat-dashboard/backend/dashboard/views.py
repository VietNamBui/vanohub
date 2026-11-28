from __future__ import annotations

import hashlib
import hmac
import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict, Unpack, cast

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Count, Manager, Q, QuerySet
from django.http import HttpResponse, JsonResponse
from django.utils import timezone as dj_timezone
from django.views.generic import View
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action  # type: ignore[reportUnknownVariableType]
from rest_framework.response import Response
from rest_framework.views import APIView

from .metrics import percentile, wilson_score_interval
from .modalities import (
    all_modality_profiles,
    default_annotation_type_for,
    get_modality_profile,
    normalize_dimension,
    summarize_geometry_metrics,
)
from .models import (
    BatchDimension,
    DailyUserMetrics,
    DefectRecord,
    DeliverStatus,
    DeliveryBatch,
    JobQualitySnapshot,
    PipelineStep,
    StageTransition,
    SyncedJob,
    SyncedTask,
    WorkflowUser,
)
from .serializers import DeliveryBatchSerializer

logger = logging.getLogger(__name__)


def _is_supervisor_or_staff(request: Any) -> bool:
    """Returns True if `request.user` is staff/superuser or mapped to a QC/Lead/PM/Admin `WorkflowUser`."""
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True
    wf_user = (
        WorkflowUser.objects.filter(django_user=user).first()
        or WorkflowUser.objects.filter(cvat_username__iexact=getattr(user, "username", "")).first()
    )
    if wf_user is None:
        return False
    return bool(wf_user.role in ("admin", "pm", "lead") or wf_user.is_qc)


class SpaEntryView(View):
    """Entry view for the React SPA; serves Vite dist/index.html, static/index.html, or fallback JSON."""

    def get(self, request: Any, *args: Any, **kwargs: Any) -> HttpResponse:
        for candidate in (
            settings.PROJECT_ROOT / "frontend" / "dist" / "index.html",
            settings.BASE_DIR / "static" / "index.html",
        ):
            if candidate.is_file():
                return HttpResponse(candidate.read_text(encoding="utf-8"), content_type="text/html")
        payload: dict[str, Any] = {
            "name": "CVAT Internal QA/QC Data Cycle Dashboard API",
            "version": "2.0.0",
            "status": "ready",
        }
        if settings.DEBUG:
            payload["endpoints"] = [
                "/api/auth/login/",
                "/api/auth/logout/",
                "/api/auth/user/",
                "/api/modalities/",
                "/api/workflow/state/",
                "/api/qc-events/",
                "/api/qc-events/activity/",
                "/api/qc-events/backfill/",
                "/api/funnel/",
                "/api/productivity/",
                "/api/scorecard/",
                "/api/defects/",
                "/api/delivery-batches/",
                "/api/webhooks/cvat-stage/",
            ]
        return JsonResponse(payload)


class ModalityConfigView(APIView):
    """Returns declarative 3D / 2D / All modality profiles and active task counts."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Any) -> Response:
        counts = dict(
            SyncedJob.objects.values_list("task__dimension").annotate(c=Count("id"))
        )
        return Response({
            "default_dimension": "all",
            "profiles": all_modality_profiles(),
            "job_counts": {
                "3d": counts.get("3d", 0),
                "2d": counts.get("2d", 0),
                "all": sum(counts.values()),
            },
        })


class DataCycleFunnelView(APIView):
    """
    Live WIP per stage across the 5-stage Data Cycle:
    job -> annotation -> qc1 -> qc2 -> deliver
    Includes avg/P95 stage lead time, SLA breach alerts, and rework loops.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Any) -> Response:
        task_id = request.query_params.get("task_id")
        dimension = normalize_dimension(request.query_params.get("dimension"), allow_all=True)
        modality = get_modality_profile(dimension)

        jobs_qs = SyncedJob.objects.select_related("task").all()
        transitions_qs = StageTransition.objects.select_related("job", "job__task").all()

        if not _is_supervisor_or_staff(request):
            uname = getattr(request.user, "username", "")
            jobs_qs = jobs_qs.filter(annotator_username__iexact=uname)
            transitions_qs = transitions_qs.filter(job__annotator_username__iexact=uname)

        if dimension != "all":
            jobs_qs = jobs_qs.filter(task__dimension=dimension)
            transitions_qs = transitions_qs.filter(job__task__dimension=dimension)

        if task_id and str(task_id).isdigit():
            jobs_qs = jobs_qs.filter(task__cvat_task_id=int(task_id))
            transitions_qs = transitions_qs.filter(job__task__cvat_task_id=int(task_id))

        now = dj_timezone.now()
        sla_config = getattr(settings, "DATA_CYCLE_SLA_HOURS", {
            "pre_qc": 4.0,
            "annotator": 24.0,
            "l1_qc": 12.0,
            "l2_qc": 12.0,
            "dept_head": 12.0,
        })

        # 1. Live WIP by 5-stage cycle
        wip = {
            "job": {"jobs": 0, "frames": 0, "items": 0, "cuboids": 0},
            "annotation": {"jobs": 0, "frames": 0, "items": 0, "cuboids": 0},
            "qc1": {"jobs": 0, "frames": 0, "items": 0, "cuboids": 0},
            "qc2": {"jobs": 0, "frames": 0, "items": 0, "cuboids": 0},
            "deliver": {"jobs": 0, "frames": 0, "items": 0, "cuboids": 0},
        }

        sla_breaches: list[dict[str, Any]] = []
        for job in jobs_qs:
            stage = job.cycle_stage
            wip[stage]["jobs"] += 1
            wip[stage]["frames"] += job.frame_count
            wip[stage]["items"] += job.total_items
            wip[stage]["cuboids"] += job.total_cuboids

            # Check SLA breach for active non-delivered jobs
            if job.deliver_status == DeliverStatus.NOT_READY and job.pipeline_step != PipelineStep.COMPLETED:
                step_key = job.pipeline_step
                allowed_hours = float(sla_config.get(step_key, 24.0))
                elapsed_hours = (now - job.step_entered_at).total_seconds() / 3600.0
                if elapsed_hours > allowed_hours:
                    sla_breaches.append({
                        "job_id": job.cvat_job_id,
                        "task_id": job.task.cvat_task_id,
                        "dimension": job.task.dimension,
                        "annotation_type": job.task.annotation_type,
                        "pipeline_step": job.pipeline_step,
                        "cycle_stage": stage,
                        "elapsed_hours": round(elapsed_hours, 1),
                        "allowed_hours": allowed_hours,
                        "assigned_user": (
                            job.annotator_username if step_key == "annotator"
                            else (job.l1_qc_username if step_key == "l1_qc" else job.l2_qc_username)
                        ),
                    })

        # 2. Stage Lead Times (Avg & P95) from StageTransition
        lead_times: dict[str, list[float]] = {
            "annotator": [],
            "l1_qc": [],
            "l2_qc": [],
            "dept_head": [],
        }
        for tr in transitions_qs.filter(duration_prev_step_sec__isnull=False):
            if tr.from_step in lead_times and tr.duration_prev_step_sec is not None:
                lead_times[tr.from_step].append(tr.duration_prev_step_sec / 3600.0)

        stage_benchmarks = {}
        for step_name, durations in lead_times.items():
            if durations:
                stage_benchmarks[step_name] = {
                    "count": len(durations),
                    "avg_hours": round(sum(durations) / len(durations), 2),
                    "p50_hours": percentile(durations, 50),
                    "p95_hours": percentile(durations, 95),
                }
            else:
                stage_benchmarks[step_name] = {
                    "count": 0,
                    "avg_hours": 0.0,
                    "p50_hours": 0.0,
                    "p95_hours": 0.0,
                }

        # 3. Rework Loops
        qc1_to_annotator = transitions_qs.filter(
            from_step="l1_qc", to_step="annotator"
        ).count()
        qc2_to_qc1 = transitions_qs.filter(
            from_step__in=["l2_qc", "dept_head"], to_step__in=["l1_qc", "annotator"]
        ).count()

        top_reasons = list(
            transitions_qs.filter(reason__gt="")
            .values("reason")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )

        return Response({
            "dimension": dimension,
            "modality": modality.to_dict(),
            "wip": wip,
            "sla_breaches_count": len(sla_breaches),
            "sla_breaches": sla_breaches[:20],
            "stage_lead_times": stage_benchmarks,
            "rework_loops": {
                "qc1_to_annotation": qc1_to_annotator,
                "qc2_to_qc1": qc2_to_qc1,
                "top_return_reasons": top_reasons,
            },
        })


class DailyProductivityView(APIView):
    """Daily output & throughput (jobs, frames, items/cuboids, working hours, speed) per day & user."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Any) -> Response:
        raw_days = request.query_params.get("days", "7")
        days = max(1, min(90, int(raw_days) if str(raw_days).isdigit() else 7))
        since_date = dj_timezone.now().date() - timedelta(days=days)
        dimension = normalize_dimension(request.query_params.get("dimension"), allow_all=True)
        modality = get_modality_profile(dimension)

        metrics_qs = DailyUserMetrics.objects.filter(date__gte=since_date)
        if not _is_supervisor_or_staff(request):
            metrics_qs = metrics_qs.filter(username__iexact=getattr(request.user, "username", ""))
        if dimension != "all":
            metrics_qs = metrics_qs.filter(dimension=dimension)

        role = request.query_params.get("role")
        if role:
            metrics_qs = metrics_qs.filter(role=role)

        username = request.query_params.get("username")
        if username:
            metrics_qs = metrics_qs.filter(username=username)

        # Timeline grouped by date
        dates_map: dict[str, dict[str, Any]] = {}
        for row in metrics_qs.order_by("date"):
            d_str = str(row.date)
            if d_str not in dates_map:
                dates_map[d_str] = {
                    "date": d_str,
                    "jobs_submitted": 0,
                    "jobs_accepted": 0,
                    "jobs_returned": 0,
                    "frames_processed": 0,
                    "items_inspected": 0,
                    "cuboids_inspected": 0,
                    "working_time_hours": 0.0,
                }
            dates_map[d_str]["jobs_submitted"] += row.jobs_submitted
            dates_map[d_str]["jobs_accepted"] += (row.jobs_accepted_l1 + row.jobs_accepted_l2 + row.jobs_completed)
            dates_map[d_str]["jobs_returned"] += row.jobs_returned_rework
            dates_map[d_str]["frames_processed"] += row.frames_processed
            dates_map[d_str]["items_inspected"] += row.items_inspected
            dates_map[d_str]["cuboids_inspected"] += row.cuboids_inspected
            dates_map[d_str]["working_time_hours"] += round(row.working_time_ms / 3600000.0, 2)

        # User aggregate breakdown
        users_map: dict[str, dict[str, Any]] = {}
        for row in metrics_qs:
            key = f"{row.username}@{row.role}"
            if key not in users_map:
                users_map[key] = {
                    "username": row.username,
                    "role": row.role,
                    "dimensions": set(),
                    "jobs_submitted": 0,
                    "jobs_accepted": 0,
                    "jobs_returned": 0,
                    "frames_processed": 0,
                    "items_inspected": 0,
                    "cuboids_inspected": 0,
                    "working_time_hours": 0.0,
                }
            users_map[key]["dimensions"].add(row.dimension)
            users_map[key]["jobs_submitted"] += row.jobs_submitted
            users_map[key]["jobs_accepted"] += (row.jobs_accepted_l1 + row.jobs_accepted_l2 + row.jobs_completed)
            users_map[key]["jobs_returned"] += row.jobs_returned_rework
            users_map[key]["frames_processed"] += row.frames_processed
            users_map[key]["items_inspected"] += row.items_inspected
            users_map[key]["cuboids_inspected"] += row.cuboids_inspected
            users_map[key]["working_time_hours"] += round(row.working_time_ms / 3600000.0, 2)

        user_rows = list(users_map.values())
        for u in user_rows:
            u["dimensions"] = sorted(u["dimensions"])
            hours = max(0.1, u["working_time_hours"])
            u["frames_per_hour"] = round(u["frames_processed"] / hours, 1)
            u["items_per_hour"] = round(u["items_inspected"] / hours, 1)
            u["cuboids_per_hour"] = round(u["cuboids_inspected"] / hours, 1)

        user_rows.sort(key=lambda x: (x["jobs_accepted"] + x["jobs_submitted"]), reverse=True)

        return Response({
            "dimension": dimension,
            "modality": modality.to_dict(),
            "window_days": days,
            "timeline": list(dates_map.values()),
            "users": user_rows,
        })


class QualityScorecardView(APIView):
    """
    QA/QC Accuracy & Red-Flag Scorecard.
    - Reviewers: Precision (Wilson 95% CI), L1->L2 escape rate, Made worse, Reviewer drift.
    - Annotators & Anti-gaming red flags:
      1. Low touch / low effort
      2. Missing attributes / occlusion edits
      3. Unfixed issues / rubber-stamping
      4. S0 pre-label deletion anti-gaming
      5. Track ID switches
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Any) -> Response:
        if not _is_supervisor_or_staff(request):
            return Response(
                {"detail": "Bảng điểm chất lượng và cảnh báo anti-gaming chỉ dành cho QC, Team Lead, PM hoặc Admin."},
                status=status.HTTP_403_FORBIDDEN,
            )
        task_id = request.query_params.get("task_id")
        dimension = normalize_dimension(request.query_params.get("dimension"), allow_all=True)
        modality = get_modality_profile(dimension)

        snaps_qs = JobQualitySnapshot.objects.select_related("job", "job__task").all()
        if dimension != "all":
            snaps_qs = snaps_qs.filter(job__task__dimension=dimension)
        if task_id and str(task_id).isdigit():
            snaps_qs = snaps_qs.filter(job__task__cvat_task_id=int(task_id))

        snaps_list = list(snaps_qs)
        total_jobs = len(snaps_list)
        total_tp = sum(s.issues_tp for s in snaps_list)
        total_fp = sum(s.issues_fp for s in snaps_list)
        precision_ci = wilson_score_interval(total_tp, total_tp + total_fp)

        total_escaped = sum(s.l1_escape_count for s in snaps_list)
        total_made_worse = sum(s.made_worse_count for s in snaps_list)
        drift_warnings_count = sum(1 for s in snaps_list if s.drift_warning)

        agreed = sum(s.ruling_agreed_count for s in snaps_list)
        disagreed = sum(s.ruling_disagreed_count for s in snaps_list)
        ruling_ci = wilson_score_interval(agreed, agreed + disagreed)

        geometry_summary = summarize_geometry_metrics(snaps_list, dimension)

        # 5 Anti-Gaming Red Flag Aggregates
        flag_low_touch = snaps_qs.filter(Q(rubber_stamp_strata_suspect=True) | Q(source_box_touch_rate__lt=0.08)).count()
        flag_missed_attr = snaps_qs.filter(attr_missed_count__gt=0).count()
        flag_rubber_stamping = snaps_qs.filter(Q(rubber_stamp_suspects__gt=0) | Q(qa_override_rate__gt=0.3)).count()
        flag_suspicious_deletion = snaps_qs.filter(suspicious_deletion_count__gt=0).count()
        flag_track_switch = snaps_qs.filter(track_id_switch_count__gt=0).count()

        # Detailed red-flag job items
        red_flag_jobs: list[dict[str, Any]] = []
        for s in snaps_list[:100]:
            flags: list[str] = []
            if s.rubber_stamp_strata_suspect or s.source_box_touch_rate < 0.08:
                flags.append("Low Touch / Low Effort")
            if s.attr_missed_count > 0:
                flags.append("Missing Attributes / Occlusion")
            if s.rubber_stamp_suspects > 0 or s.qa_override_rate > 0.3:
                flags.append("Rubber-Stamping Unfixed Issues")
            if s.suspicious_deletion_count > 0:
                flags.append("Suspicious S0 Pre-label Deletion")
            if s.track_id_switch_count > 0:
                flags.append("Track ID Switch")

            if flags:
                red_flag_jobs.append({
                    "job_id": s.job.cvat_job_id,
                    "task_id": s.job.task.cvat_task_id,
                    "dimension": s.job.task.dimension,
                    "annotation_type": s.job.task.annotation_type,
                    "annotator": s.job.annotator_username,
                    "flags": flags,
                    "touch_rate": round(s.source_box_touch_rate * 100, 1),
                    "attr_edit_rate": round(s.attr_edit_rate * 100, 1),
                    "s0_deleted": s.s0_deleted_count,
                    "track_switches": s.track_id_switch_count,
                })

        return Response({
            "dimension": dimension,
            "modality": modality.to_dict(),
            "total_evaluated_jobs": total_jobs,
            "geometry_summary": geometry_summary,
            "reviewer_scorecard": {
                "precision": precision_ci,
                "total_tp": total_tp,
                "total_fp": total_fp,
                "l1_escape_count": total_escaped,
                "l1_escape_rate": round(float(total_escaped) / max(1, total_jobs), 4),
                "made_worse_count": total_made_worse,
                "drift_warnings_count": drift_warnings_count,
                "ruling_agreement": ruling_ci,
            },
            "anti_gaming_red_flags": {
                "low_touch_suspects": flag_low_touch,
                "missing_attributes": flag_missed_attr,
                "rubber_stamp_unfixed": flag_rubber_stamping,
                "suspicious_s0_deletions": flag_suspicious_deletion,
                "track_id_switches": flag_track_switch,
                "flagged_jobs": red_flag_jobs[:25],
            },
        })


class DefectParetoView(APIView):
    """
    E1..E6 Pareto distribution with Wilson 95% CI upper bound & metadata-only root causes.
    """

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Any) -> Response:
        task_id = request.query_params.get("task_id")
        dimension = normalize_dimension(request.query_params.get("dimension"), allow_all=True)
        modality = get_modality_profile(dimension)

        defects_qs = DefectRecord.objects.select_related("job", "job__task").all()
        if not _is_supervisor_or_staff(request):
            defects_qs = defects_qs.filter(annotator_username__iexact=getattr(request.user, "username", ""))
        if dimension != "all":
            defects_qs = defects_qs.filter(job__task__dimension=dimension)
        if task_id and str(task_id).isdigit():
            defects_qs = defects_qs.filter(job__task__cvat_task_id=int(task_id))

        total_defects = defects_qs.count()

        # E1..E6 Pareto grouping
        categories_count = (
            defects_qs.values("primary_category")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        cumulative = 0.0
        pareto_items: list[dict[str, Any]] = []
        for cat in categories_count:
            c_name = cat["primary_category"] or "Other"
            c_count = cat["count"]
            pct = round((c_count / max(1, total_defects)) * 100, 2)
            cumulative = round(cumulative + pct, 2)
            ci = wilson_score_interval(c_count, total_defects)
            pareto_items.append({
                "category": c_name,
                "label": modality.category_labels.get(c_name, c_name),
                "count": c_count,
                "percentage": pct,
                "cumulative_percentage": min(100.0, cumulative),
                "rate_ci_upper": round(ci["upper"] * 100, 2),
            })

        # Top defect codes
        top_codes = list(
            defects_qs.values("defect_code")
            .annotate(count=Count("id"))
            .order_by("-count")[:10]
        )

        # Root causes breakdown
        root_causes = list(
            defects_qs.exclude(root_cause="")
            .values("root_cause")
            .annotate(count=Count("id"))
            .order_by("-count")[:8]
        )

        dim_breakdown = dict(
            defects_qs.values_list("job__task__dimension").annotate(count=Count("id"))
        )

        return Response({
            "dimension": dimension,
            "modality": modality.to_dict(),
            "total_defects": total_defects,
            "dimension_breakdown": {
                "3d": dim_breakdown.get("3d", 0),
                "2d": dim_breakdown.get("2d", 0),
            },
            "pareto": pareto_items,
            "top_defect_codes": top_codes,
            "root_causes": root_causes,
        })


class IsSupervisorOrReadOnlyPermission(permissions.BasePermission):
    """Allows read-only access to supervisors and blocks annotators from mutating delivery batches."""

    def has_permission(self, request: Any, view: Any) -> bool:
        if not getattr(request.user, "is_authenticated", False):
            return False
        return _is_supervisor_or_staff(request)


class DeliveryBatchViewSet(viewsets.ModelViewSet):
    """
    Delivery Batches and Quality Gate verification (supports 3D, 2D, and mixed batches).
    """

    queryset = DeliveryBatch.objects.prefetch_related("items", "items__job", "items__job__task").all()
    serializer_class = DeliveryBatchSerializer
    permission_classes = [permissions.IsAuthenticated, IsSupervisorOrReadOnlyPermission]

    id: int
    pk: int
    objects: _DeliveryBatchViewSetManager
    def get_queryset(self) -> Any:
        qs = super().get_queryset()
        dimension = normalize_dimension(self.request.query_params.get("dimension"), allow_all=True)
        if dimension != "all":
            qs = qs.filter(Q(dimension=dimension) | Q(items__job__task__dimension=dimension)).distinct()
        return qs

    def perform_create(self, serializer: Any) -> None:
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["POST"], url_path="verify-gate")
    def verify_gate(self, request: Any, pk: Any = None) -> Response:
        batch: DeliveryBatch = self.get_object()
        all_passed = True

        for item in batch.items.select_related("job", "job__task"):
            job: SyncedJob = item.job
            blockers: list[str] = []

            if batch.dimension in (BatchDimension.DIM_3D, BatchDimension.DIM_2D) and job.task.dimension != batch.dimension:
                blockers.append(
                    f"Sai loại dữ liệu: lô yêu cầu {batch.dimension.upper()} nhưng job là {job.task.dimension.upper()}"
                )
            if job.pipeline_step != PipelineStep.COMPLETED:
                blockers.append(f"Chưa hoàn tất quy trình (đang ở bước {job.get_pipeline_step_display()})")
            if job.open_issues > 0:
                blockers.append(f"Còn {job.open_issues} lỗi chưa xử lý")
            if not job.threshold_met:
                blockers.append("Chưa đạt chuẩn kiểm tra tự động / threshold")
            if job.l2_required and job.review_round < 1:
                blockers.append("Chưa hoàn thành kiểm định L2 bắt buộc")

            passed = len(blockers) == 0
            if not passed:
                all_passed = False

            item.gate_passed = passed
            item.gate_blockers = blockers
            item.save(update_fields=["gate_passed", "gate_blockers"])

        if all_passed and batch.items.exists():
            batch.status = DeliveryBatch.Status.GATE_READY
        else:
            batch.status = DeliveryBatch.Status.DRAFT
        batch.save(update_fields=["status"])

        return Response({
            "batch_code": batch.batch_code,
            "dimension": batch.dimension,
            "status": batch.status,
            "all_passed": all_passed,
            "items_count": batch.items.count(),
        })

    @action(detail=True, methods=["GET"], url_path="export-manifest")
    def export_manifest(self, request: Any, pk: Any = None) -> Response:
        batch: DeliveryBatch = self.get_object()
        manifest_items: list[dict[str, Any]] = []
        for it in batch.items.select_related("job", "job__task"):
            it_job: SyncedJob = it.job
            manifest_items.append({
                "job_id": it_job.cvat_job_id,
                "task_name": it_job.task.name,
                "dimension": it_job.task.dimension,
                "annotation_type": it_job.task.annotation_type,
                "frames": it_job.frame_count,
                "items_count": it_job.total_items,
                "cuboids": it_job.total_cuboids,
                "gate_passed": it.gate_passed,
            })

        manifest = {
            "batch_code": batch.batch_code,
            "title": batch.title,
            "client_name": batch.client_name,
            "dimension": batch.dimension,
            "status": batch.status,
            "delivered_at": batch.delivered_at.isoformat() if batch.delivered_at else None,
            "exported_at": dj_timezone.now().isoformat(),
            "items": manifest_items,
        }
        return Response(manifest)

    def __init__(self, *, id: int | None = ..., queryset: Any = ..., serializer_class: Any = ..., permission_classes: Any = ...) -> None: ...

class _DeliveryBatchViewSetLookups(TypedDict, total=False):
    pk: int
    pk__exact: int
    pk__iexact: int
    pk__gt: int
    pk__gte: int
    pk__lt: int
    pk__lte: int
    pk__in: list[int]
    pk__contains: str
    pk__icontains: str
    pk__startswith: str
    pk__istartswith: str
    pk__endswith: str
    pk__iendswith: str
    pk__range: tuple[int, int]
    pk__isnull: bool
    pk__regex: str
    pk__iregex: str
    queryset: Any
    queryset__exact: Any
    queryset__iexact: Any
    queryset__gt: Any
    queryset__gte: Any
    queryset__lt: Any
    queryset__lte: Any
    queryset__in: list[Any]
    queryset__contains: str
    queryset__icontains: str
    queryset__startswith: str
    queryset__istartswith: str
    queryset__endswith: str
    queryset__iendswith: str
    queryset__range: tuple[Any, Any]
    queryset__isnull: bool
    queryset__regex: str
    queryset__iregex: str
    serializer_class: Any
    serializer_class__exact: Any
    serializer_class__iexact: Any
    serializer_class__gt: Any
    serializer_class__gte: Any
    serializer_class__lt: Any
    serializer_class__lte: Any
    serializer_class__in: list[Any]
    serializer_class__contains: str
    serializer_class__icontains: str
    serializer_class__startswith: str
    serializer_class__istartswith: str
    serializer_class__endswith: str
    serializer_class__iendswith: str
    serializer_class__range: tuple[Any, Any]
    serializer_class__isnull: bool
    serializer_class__regex: str
    serializer_class__iregex: str
    permission_classes: Any
    permission_classes__exact: Any
    permission_classes__iexact: Any
    permission_classes__gt: Any
    permission_classes__gte: Any
    permission_classes__lt: Any
    permission_classes__lte: Any
    permission_classes__in: list[Any]
    permission_classes__contains: str
    permission_classes__icontains: str
    permission_classes__startswith: str
    permission_classes__istartswith: str
    permission_classes__endswith: str
    permission_classes__iendswith: str
    permission_classes__range: tuple[Any, Any]
    permission_classes__isnull: bool
    permission_classes__regex: str
    permission_classes__iregex: str

class _DeliveryBatchViewSetManager(Manager[DeliveryBatchViewSet]):
    def all(self, *args: Any, **kwargs: Any) -> QuerySet[DeliveryBatchViewSet]: ...
    def filter(self, *args: Any, **kwargs: Unpack[_DeliveryBatchViewSetLookups]) -> QuerySet[DeliveryBatchViewSet]: ...
    def exclude(self, *args: Any, **kwargs: Unpack[_DeliveryBatchViewSetLookups]) -> QuerySet[DeliveryBatchViewSet]: ...
    def get(self, *args: Any, **kwargs: Unpack[_DeliveryBatchViewSetLookups]) -> DeliveryBatchViewSet: ...
    def create(self, *args: Any, **kwargs: Unpack[_DeliveryBatchViewSetLookups]) -> DeliveryBatchViewSet: ...
    def get_or_create(self, *args: Any, **kwargs: Unpack[_DeliveryBatchViewSetLookups]) -> tuple[DeliveryBatchViewSet, bool]: ...
    def update_or_create(self, *args: Any, **kwargs: Unpack[_DeliveryBatchViewSetLookups]) -> tuple[DeliveryBatchViewSet, bool]: ...
    def first(self, *args: Any, **kwargs: Any) -> DeliveryBatchViewSet | None: ...


def _parse_webhook_timestamp(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ValueError("invalid timestamp")
    if isinstance(raw, (int, float)):
        val = float(raw)
        if not math.isfinite(val):
            raise ValueError("invalid timestamp")
        return datetime.fromtimestamp(val, tz=UTC)
    text = str(raw).strip()
    if not text:
        return None
    try:
        val = float(text)
        if math.isfinite(val):
            return datetime.fromtimestamp(val, tz=UTC)
    except ValueError:
        pass
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


class WebhookCvatStageView(APIView):
    """
    Receives stage transition events from CVAT (e.g. stage.submitted, stage.accepted, stage.returned).
    Verifies HMAC when CVAT_WEBHOOK_SECRET is configured, or requires authenticated staff/superuser
    otherwise (fail closed). Enforces idempotency via `event_id` / `X-CVAT-Delivery`.
    """

    permission_classes = [permissions.AllowAny]
    throttle_scope = "webhook"

    def post(self, request: Any) -> Response:
        secret = getattr(settings, "CVAT_WEBHOOK_SECRET", "")
        if secret:
            sig = str(
                request.headers.get("X-Signature-256")
                or request.headers.get("X-CVAT-Signature-256")
                or ""
            ).strip()
            raw_body = request.body
            computed = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
            if not sig or not hmac.compare_digest(sig, computed):
                return Response({"detail": "Chữ ký webhook không hợp lệ."}, status=status.HTTP_401_UNAUTHORIZED)
        else:
            user = getattr(request, "user", None)
            if not getattr(user, "is_authenticated", False):
                return Response(
                    {"detail": "Webhook secret chưa được cấu hình; yêu cầu xác thực."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            if not (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
                return Response(
                    {"detail": "Webhook secret chưa được cấu hình; chỉ staff được phép gửi."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        raw_payload: Any = request.data
        if not isinstance(raw_payload, dict):
            return Response({"detail": "Payload phải là JSON object."}, status=status.HTTP_400_BAD_REQUEST)

        payload: dict[str, Any] = cast("dict[str, Any]", raw_payload)

        # Optional / configurable replay protection via X-CVAT-Timestamp (or payload timestamp when strict)
        hdr_ts = request.headers.get("X-CVAT-Timestamp")
        require_ts = bool(getattr(settings, "CVAT_WEBHOOK_REQUIRE_TIMESTAMP", False))
        raw_ts = hdr_ts if hdr_ts is not None else (payload.get("timestamp") if require_ts else None)
        if require_ts and (raw_ts is None or str(raw_ts).strip() == ""):
            return Response({"detail": "Thiếu X-CVAT-Timestamp."}, status=status.HTTP_401_UNAUTHORIZED)
        if raw_ts is not None and str(raw_ts).strip() != "":
            try:
                hook_ts = _parse_webhook_timestamp(raw_ts)
            except (TypeError, ValueError, OverflowError):
                return Response({"detail": "Timestamp webhook không hợp lệ."}, status=status.HTTP_400_BAD_REQUEST)
            if hook_ts is not None:
                max_age = max(1, int(getattr(settings, "CVAT_WEBHOOK_MAX_AGE_SECONDS", 300)))
                if abs((dj_timezone.now() - hook_ts).total_seconds()) > max_age:
                    return Response({"detail": "Webhook timestamp đã hết hạn (replay window)."}, status=status.HTTP_401_UNAUTHORIZED)

        raw_job_id: Any = payload.get("job_id")
        raw_task_id: Any = payload.get("task_id", 0)
        task_id: int = int(raw_task_id) if not isinstance(raw_task_id, bool) and str(raw_task_id).isdigit() else 0
        task_name: str = str(payload.get("task_name") or f"Task #{task_id}")[:255]
        raw_dim: str = str(payload.get("dimension") or "")
        task_dimension: str = normalize_dimension(raw_dim, allow_all=False)
        task_annotation_type: str = str(
            payload.get("annotation_type") or default_annotation_type_for(task_dimension)
        )[:32]
        event_name: str = str(payload.get("event") or payload.get("event_name") or "stage.updated")[:48]
        from_step: str = str(payload.get("from_step") or "").strip()[:24]
        to_step: str = str(payload.get("to_step") or payload.get("stage") or "").strip()
        actor: str = str(payload.get("actor") or payload.get("username") or "")[:150]
        actor_role: str = str(payload.get("actor_role") or "")[:24]
        reason: str = str(payload.get("reason") or "")
        raw_event_id: Any = (
            payload.get("event_id")
            or payload.get("idempotency_key")
            or request.headers.get("X-CVAT-Delivery")
        )
        event_id: str | None = str(raw_event_id).strip()[:64] if raw_event_id and str(raw_event_id).strip() else None

        if not raw_job_id or not to_step:
            return Response({"detail": "Thiếu job_id hoặc to_step."}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(raw_job_id, bool) or not str(raw_job_id).isdigit():
            return Response({"detail": "job_id không hợp lệ."}, status=status.HTTP_400_BAD_REQUEST)
        job_id = int(raw_job_id)
        if job_id <= 0:
            return Response({"detail": "job_id không hợp lệ."}, status=status.HTTP_400_BAD_REQUEST)
        if to_step not in PipelineStep.values:
            return Response({"detail": f"to_step không hợp lệ: {to_step}"}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            if event_id:
                existing_tr = StageTransition.objects.select_for_update().filter(event_id=event_id).first()
                if existing_tr is not None:
                    return Response({
                        "status": "duplicate_ignored",
                        "deduplicated": True,
                        "event_id": event_id,
                        "job_id": job_id,
                        "pipeline_step": existing_tr.to_step,
                    })

            task, _ = SyncedTask.objects.get_or_create(
                cvat_task_id=task_id,
                defaults={
                    "name": task_name,
                    "dimension": task_dimension,
                    "annotation_type": task_annotation_type,
                },
            )
            job, created = SyncedJob.objects.select_for_update().get_or_create(
                cvat_job_id=job_id,
                defaults={
                    "task": task,
                    "pipeline_step": to_step,
                    "step_entered_at": dj_timezone.now(),
                },
            )

            prev_entered = job.step_entered_at
            prev_step = job.pipeline_step
            now = dj_timezone.now()
            duration_sec = (now - prev_entered).total_seconds() if prev_entered else None

            if not created and job.pipeline_step != to_step:
                job.pipeline_step = to_step
                job.step_entered_at = now
                if to_step == PipelineStep.COMPLETED:
                    job.completed_at = now
                    job.deliver_status = DeliverStatus.READY
                job.save(update_fields=["pipeline_step", "step_entered_at", "completed_at", "deliver_status", "updated_at"])

            try:
                with transaction.atomic():
                    StageTransition.objects.create(
                        job=job,
                        event_id=event_id,
                        event_name=event_name,
                        from_step=from_step or prev_step,
                        to_step=to_step,
                        actor_username=actor,
                        actor_role=actor_role,
                        reason=reason,
                        occurred_at=now,
                        duration_prev_step_sec=duration_sec,
                    )
            except IntegrityError:
                if event_id:
                    existing_tr = StageTransition.objects.filter(event_id=event_id).first()
                    return Response({
                        "status": "duplicate_ignored",
                        "deduplicated": True,
                        "event_id": event_id,
                        "job_id": job_id,
                        "pipeline_step": existing_tr.to_step if existing_tr else job.pipeline_step,
                    })
                raise

        return Response({"status": "received", "event_id": event_id, "job_id": job_id, "pipeline_step": to_step})
