"""Dashboard & KPI. Tổng hợp dữ liệu từ projects, jobs, quality, teams.

QUY ƯỚC:
- Chỉ số chưa chốt định nghĩa (CL02, CL05, CL11, NS04, DB02/DB03) trả về value=None kèm status="pending_definition".
- Múi giờ nghiệp vụ cắt ngày cố định theo Asia/Ho_Chi_Minh (settings.APP_TIME_ZONE).
"""

from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import (
    Case,
    Count,
    Exists,
    F,
    IntegerField,
    Max,
    OuterRef,
    Prefetch,
    Q,
    Sum,
    When,
)
from django.db.models.functions import Coalesce, Greatest, TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.datetime_utils import (
    app_timezone,
    format_local_datetime,
    format_rfc3339_utc,
    local_date,
    parse_query_date_range,
    parse_rfc3339_datetime,
)
from accounts.models import Role, RoleAssignment, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from jobs.models import (
    ACTIVE_ANNOTATOR_STATUSES,
    OPEN_STATUSES,
    STAGE_STATUSES,
    SUBMITTED_OR_DONE_STATUSES,
    AnnotatorRequest,
    DailyOutputRecord,
    FirstQc1Result,
    Job,
    JobStatus,
    ReworkScope,
)
from jobs.serializers import AnnotatorRequestSerializer, JobSerializer, ReviewErrorBriefSerializer
from jobs.views import order_by_db06_priority
from projects.models import ActivityLog, Batch, DataStatus, Delivery, EscalationPolicy
from projects.notifications import user_team_ids
from quality.models import Audit, AuditSample, ErrorVerdict, JobIssue, ReviewError, ReviewStage, Severity
from quality.qc2 import ANNOTATOR_EVENTS
from teams.models import Team, TeamMember

PERIODS = {"day": 1, "week": 7, "month": 30}
DONE = STAGE_STATUSES["done"]
REACHED_QC2 = [JobStatus.QC1_PASSED, JobStatus.PENDING_QC2, *DONE]
BLOCKING_QC2_STATUSES = [
    JobStatus.PENDING_ANNOTATION,
    JobStatus.ANNOTATING,
    JobStatus.REWORK,
    JobStatus.PENDING_QC1,
    JobStatus.QC1_REVIEWING,
]
ACTIVE_QC1_STATUSES = [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING]


def _metric(value: Any, *, status: str = "ok", formula: str = "", **extra: Any) -> dict[str, Any]:
    return {"value": value, "status": status, "formula": formula, **extra}


def _pending_quality_cl() -> dict[str, Any]:
    return _metric(
        None,
        status="pending_definition",
        formula="Chờ định nghĩa phân loại Cuboid Pass / Edge / Fail trên các frame được kiểm (CL11).",
    )


def _pending_defect_error_rate() -> dict[str, Any]:
    return _metric(
        None,
        status="pending_definition",
        formula="Chờ định nghĩa mẫu số cuboid trên các frame được kiểm (CL02).",
    )


def _pending_defect_rate_by_severity() -> dict[str, Any]:
    return _metric(
        None,
        status="pending_definition",
        formula="Chờ định nghĩa mẫu số cuboid theo mức độ trên các frame được kiểm (CL05).",
    )


def _pct(part: int | float, whole: int | float, digits: int = 1) -> float | None:
    return round(part * 100 / whole, digits) if whole else None


def _format_decimal(value: Decimal | None) -> str | None:
    """Định dạng Decimal nhất quán với DRF DecimalField(max_digits=5, decimal_places=2)."""
    return f"{value:.2f}" if value is not None else None


def _local_day_start(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, datetime.min.time()), app_timezone())


def _period_window(request: Any, *, now: datetime | None = None) -> tuple[datetime, datetime, datetime, int]:
    """Trả về (current_start, current_end, prev_start, trend_days).

    Hỗ trợ ?date_from=&date_to= (chuẩn hóa qua parse_query_date_range) hoặc ?period=day|week|month.
    Với ?period=day: cắt từ 00:00:00 theo giờ Việt Nam (Asia/Ho_Chi_Minh).
    """
    current = now or timezone.now()
    custom_start, custom_end = parse_query_date_range(
        request.query_params, from_key="date_from", to_key="date_to"
    )
    if custom_start is not None or custom_end is not None:
        end = custom_end or current
        start = custom_start or (end - timedelta(days=7))
        span = max(end - start, timedelta(days=1))
        trend_days = 30 if span.days >= 30 else 7
        return start, end, start - span, trend_days

    period = request.query_params.get("period", "week")
    if period == "day":
        start = _local_day_start(local_date(current))
        return start, current, start - timedelta(days=1), 7
    days = PERIODS.get(period, 7)
    start = current - timedelta(days=days)
    trend_days = 30 if days >= 30 else 7
    return start, current, start - timedelta(days=days), trend_days


def _delta_metrics(current_val: int | float, previous_val: int | float) -> dict[str, Any]:
    """KPI08 (chênh lệch) & KPI09 (% tăng/giảm, kỳ trước = 0 thì None)."""
    delta = current_val - previous_val
    pct_change = round(delta * 100 / previous_val, 1) if previous_val > 0 else None
    return {"delta": delta, "pct_change": pct_change}


def _kpi_progress(actual: int, target: int | None) -> dict[str, Any]:
    """KPI02 (gộp KPI07) + KPI03 (shortfall) + KPI04 (surplus)."""
    if target:
        return {
            "actual": actual,
            "target": target,
            "achievement_pct": _pct(actual, target),
            "shortfall": max(0, target - actual),
            "surplus": max(0, actual - target),
        }
    return {
        "actual": actual,
        "target": target,
        "achievement_pct": None,
        "shortfall": 0,
        "surplus": 0,
    }


def _reworked_q() -> Q:
    """RW02: job từng bị trả rework (không mất khi PM resolve-escalation đặt lại rework_round=0)."""
    return Q(total_rework_rounds__gt=0) | Q(rework_round__gt=0)


def _count_unique_error_targets(errors: list[ReviewError]) -> tuple[int, int]:
    """Đếm mục tiêu lỗi duy nhất: (existing_cuboid_targets, missing_object_targets)."""
    existing: set[tuple[object, ...]] = set()
    missing: set[tuple[object, ...]] = set()
    for err in errors:
        if err.is_missing_object:
            if err.frame_number is not None:
                missing.add(("missing", err.frame_number, err.category_id))
            else:
                missing.add(("missing_err", err.id))
        elif err.frame_number is not None and err.cvat_object_id is not None:
            existing.add(("obj", err.frame_number, err.cvat_object_id))
        elif err.location and err.location.strip():
            existing.add(("loc", err.location.strip().lower()))
        else:
            existing.add(("err", err.id))
    return len(existing), len(missing)


def _fpy_stats(jobs_qs: Any) -> dict[str, Any]:
    """CL01: FPY tại QC1 theo first_qc1_result bất biến, có fallback an toàn cho dữ liệu cũ / đồng bộ CVAT.

    - Tin tuyệt đối first_qc1_result khi đã ghi ("pass" hoặc "reject").
    - Khi first_qc1_result == "":
      - Nếu có bằng chứng đạt QC1 vòng 0 (AuditSample/QC2 error/qc1.pass vòng 0) và không bị QC1 reject vòng 0
        → tính đạt lần đầu (không đổ oan QC2 reject cũ thành QC1 reject).
      - Nếu bị QC1 reject vòng 0 hoặc từng rework / đang REWORK mà không qua QC1 vòng 0 → tính trượt lần đầu.
      - Nếu đã tới REACHED_QC2 với total_rework_rounds=0 và rework_round=0 và không có QC1 reject vòng 0 → đạt lần đầu.
    """
    passed_r0_evidence = (
        Exists(AuditSample.objects.filter(job_id=OuterRef("pk"), rework_round=0))
        | Exists(ReviewError.objects.filter(job_id=OuterRef("pk"), stage=ReviewStage.QC2, rework_round=0))
        | Exists(ActivityLog.objects.filter(job_id=OuterRef("pk"), action="qc1.pass", after__rework_round=0))
    )
    rejected_r0_at_qc1 = Exists(
        ReviewError.objects.filter(job_id=OuterRef("pk"), stage=ReviewStage.QC1, rework_round=0)
    ) | Exists(ActivityLog.objects.filter(job_id=OuterRef("pk"), action="qc1.reject", after__rework_round=0))

    annotated = jobs_qs.annotate(
        _legacy_r0_passed_qc1=passed_r0_evidence,
        _legacy_r0_rejected_qc1=rejected_r0_at_qc1,
    )
    explicit_pass = Q(first_qc1_result=FirstQc1Result.PASS)
    explicit_reject = Q(first_qc1_result=FirstQc1Result.REJECT)
    fallback_base = Q(first_qc1_result="")
    fallback_pass = fallback_base & (
        (
            Q(status__in=REACHED_QC2, total_rework_rounds=0, rework_round=0)
            & Q(_legacy_r0_rejected_qc1=False)
        )
        | (Q(_legacy_r0_passed_qc1=True) & Q(_legacy_r0_rejected_qc1=False))
    )
    fallback_reject = fallback_base & (
        Q(_legacy_r0_rejected_qc1=True)
        | ((_reworked_q() | Q(status=JobStatus.REWORK)) & Q(_legacy_r0_passed_qc1=False))
    )

    agg = annotated.aggregate(
        passed=Count("id", filter=explicit_pass | fallback_pass),
        total=Count("id", filter=explicit_pass | explicit_reject | fallback_pass | fallback_reject),
    )
    passed = agg["passed"] or 0
    total = agg["total"] or 0
    return {"passed": passed, "total": total, "value": _pct(passed, total)}


def _severity_breakdown(errors_qs: Any) -> dict[str, int]:
    """CL04: phân bố lỗi chưa bị hủy theo mức độ minor / major / critical."""
    counts = dict(errors_qs.values_list("severity").annotate(n=Count("id")))
    return {
        Severity.MINOR.value: counts.get(Severity.MINOR.value, 0),
        Severity.MAJOR.value: counts.get(Severity.MAJOR.value, 0),
        Severity.CRITICAL.value: counts.get(Severity.CRITICAL.value, 0),
    }


def _merged_hours(intervals: list[tuple[datetime, datetime]]) -> float:
    """Hợp nhất các khoảng thời gian làm việc chồng lấn (tránh cộng đúp giờ khi WIP >= 2)."""
    if not intervals:
        return 0.0
    ordered = sorted(intervals, key=lambda pair: pair[0])
    cur_start, cur_end = ordered[0]
    total_secs = 0.0
    for s, e in ordered[1:]:
        if s <= cur_end:
            if e > cur_end:
                cur_end = e
        else:
            total_secs += (cur_end - cur_start).total_seconds()
            cur_start, cur_end = s, e
    total_secs += (cur_end - cur_start).total_seconds()
    return total_secs / 3600.0


def _extract_log_deadline(ev: ActivityLog) -> datetime | None:
    raw_dl = (ev.after or {}).get("deadline")
    if isinstance(raw_dl, str) and raw_dl:
        try:
            return parse_rfc3339_datetime(raw_dl)
        except ValueError:
            pass
    if ev.job is not None:
        return ev.job.deadline
    return None


def _daily_output_breakdown(
    project: Any,
    user: Any,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Tổng hợp DailyOutputRecord (user__is_active=True) tách rõ first_pass/rework và SUBMIT vs CVAT_SYNC."""
    rows = (
        DailyOutputRecord.objects.filter(
            project=project,
            user=user,
            user__is_active=True,
            work_date__gte=start_date,
            work_date__lte=end_date,
        )
        .values("work_date", "job_id", "is_rework", "source")
        .annotate(total=Sum("object_count"))
    )
    fp_total: dict[date, int] = defaultdict(int)
    rw_total: dict[date, int] = defaultdict(int)
    submitted_total: dict[date, int] = defaultdict(int)
    cvat_sync_total: dict[date, int] = defaultdict(int)
    fp_by_job: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    rw_by_job: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))

    for r in rows:
        d: date = r["work_date"]
        jid: int = r["job_id"]
        val = int(r["total"] or 0)
        if r["is_rework"]:
            rw_total[d] += val
            rw_by_job[d][jid] += val
        else:
            fp_total[d] += val
            fp_by_job[d][jid] += val
        if r["source"] == DailyOutputRecord.Source.CVAT_SYNC:
            cvat_sync_total[d] += val
        else:
            submitted_total[d] += val

    return {
        "fp_total": fp_total,
        "rw_total": rw_total,
        "submitted_total": submitted_total,
        "cvat_sync_total": cvat_sync_total,
        "fp_by_job": fp_by_job,
        "rw_by_job": rw_by_job,
    }


class ProjectOverviewView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/overview/?period=day|week|month"""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request: Any, project_id: Any) -> Response:
        project = self.project
        now = timezone.now()
        since, until, _, _ = _period_window(request, now=now)
        jobs = Job.objects.filter(project=project)

        totals = jobs.aggregate(
            total=Count("id"),
            objects=Sum("object_count"),
            frames=Sum("frame_count"),
            done=Count("id", filter=Q(status__in=DONE)),
            anno_passed=Count("id", filter=Q(status__in=SUBMITTED_OR_DONE_STATUSES)),
            qc1_passed=Count("id", filter=Q(status__in=REACHED_QC2)),
            reworked=Count("id", filter=_reworked_q()),
            escalated=Count("id", filter=Q(is_escalated=True)),
            overdue=Count("id", filter=Q(deadline__lt=now, status__in=OPEN_STATUSES)),
        )
        total_jobs = totals["total"] or 0
        done_jobs = totals["done"] or 0
        remaining_jobs = total_jobs - done_jobs

        by_status = dict(jobs.values_list("status").annotate(n=Count("id")))
        by_stage = {stage: sum(by_status.get(s, 0) for s in statuses) for stage, statuses in STAGE_STATUSES.items()}

        stage_progress = {
            "annotation_passed": _pct(totals["anno_passed"] or 0, total_jobs),
            "qc1_passed": _pct(totals["qc1_passed"] or 0, total_jobs),
            "qc2_approved": _pct(done_jobs, total_jobs),
        }

        batch_rows = list(
            Batch.objects.filter(project=project)
            .select_related("dataset")
            .annotate(
                job_count=Count("jobs", distinct=True),
                approved_count=Count("jobs", filter=Q(jobs__status=JobStatus.APPROVED), distinct=True),
                qc1_passed_count=Count("jobs", filter=Q(jobs__status=JobStatus.QC1_PASSED), distinct=True),
                blocking_qc2_count=Count("jobs", filter=Q(jobs__status__in=BLOCKING_QC2_STATUSES), distinct=True),
                locked_jobs=Count("jobs", filter=Q(jobs__is_locked=True), distinct=True),
                pending_qc2_samples=Count(
                    "audits__samples",
                    filter=Q(audits__samples__result=AuditSample.Result.PENDING),
                    distinct=True,
                ),
            )
        )
        total_batches = len(batch_rows)
        delivered_batches = sum(1 for b in batch_rows if b.status == DataStatus.DELIVERED)
        ready_batches = sum(
            1
            for b in batch_rows
            if b.status != DataStatus.DELIVERED
            and b.status == DataStatus.ACTIVE
            and b.dataset.status == DataStatus.ACTIVE
            and b.job_count > 0
            and b.approved_count == b.job_count
            and b.pending_qc2_samples == 0
            and b.locked_jobs == 0
        )
        batches_ready_for_qc2_confirm = sum(
            1
            for b in batch_rows
            if b.status == DataStatus.ACTIVE
            and b.dataset.status == DataStatus.ACTIVE
            and b.job_count > 0
            and b.qc1_passed_count > 0
            and b.blocking_qc2_count == 0
            and b.locked_jobs == 0
        )
        deliveries = list(
            Delivery.objects.filter(project=project).values_list("batch_id", "delivered_at", "batch__deadline")
        )
        delivered_batch_ids = {batch_id for batch_id, _, _ in deliveries}
        due_delivered = [(delivered_at, dl) for _, delivered_at, dl in deliveries if dl is not None]
        on_time_deliveries = sum(
            1 for delivered_at, dl in due_delivered if delivered_at is not None and delivered_at <= dl
        )
        late_deliveries = len(due_delivered) - on_time_deliveries
        overdue_undelivered = sum(
            1
            for b in batch_rows
            if b.status != DataStatus.DELIVERED
            and b.id not in delivered_batch_ids
            and b.deadline is not None
            and b.deadline < now
        )
        due_deliveries = len(due_delivered) + overdue_undelivered
        pending_qc2_samples = AuditSample.objects.filter(
            audit__project=project,
            audit__status=Audit.Status.IN_PROGRESS,
            result=AuditSample.Result.PENDING,
        ).count()
        pending_requests = AnnotatorRequest.objects.filter(
            project=project, status=AnnotatorRequest.Status.PENDING_PM
        ).count()
        pending_issue_rulings = JobIssue.objects.filter(
            project=project,
            authority_status=JobIssue.AuthorityStatus.VALID,
            source_missing=False,
            status=JobIssue.Status.UNCLEAR,
        ).count()
        escalated_jobs = totals["escalated"] or 0
        pending_decisions = {
            "batches_ready_for_qc2_confirm": batches_ready_for_qc2_confirm,
            "batches_ready_for_qc2": batches_ready_for_qc2_confirm,
            "pending_qc2_samples": pending_qc2_samples,
            "pending_requests": pending_requests,
            "pending_issue_rulings": pending_issue_rulings,
            "escalated_jobs": escalated_jobs,
            "escalated": escalated_jobs,
            "total": (
                batches_ready_for_qc2_confirm
                + pending_qc2_samples
                + pending_requests
                + pending_issue_rulings
                + escalated_jobs
            ),
        }

        fpy = _fpy_stats(jobs)
        active_errors = ReviewError.objects.filter(job__project=project, is_voided=False)
        errors_by_category = [
            {"category": r["category__name"], "count": r["n"]}
            for r in active_errors.values("category__name").annotate(n=Count("id")).order_by("-n")[:10]
        ]
        errors_by_severity = _severity_breakdown(active_errors)

        dispute_agg = AnnotatorRequest.objects.filter(
            project=project,
            request_type=AnnotatorRequest.RequestType.ERROR_DISPUTE,
            status__in=[AnnotatorRequest.Status.RESOLVED, AnnotatorRequest.Status.REJECTED],
        ).aggregate(
            total=Count("id"),
            resolved=Count("id", filter=Q(status=AnnotatorRequest.Status.RESOLVED)),
        )
        dispute_overturn = _pct(dispute_agg["resolved"] or 0, dispute_agg["total"] or 0)

        samples = AuditSample.objects.filter(audit__project=project).exclude(result=AuditSample.Result.PENDING)
        qc2 = samples.aggregate(decided=Count("id"), passed=Count("id", filter=Q(result=AuditSample.Result.PASS)))

        submitted = ActivityLog.objects.filter(
            project=project,
            action="job.status",
            after__status=JobStatus.PENDING_QC1,
            created_at__gte=since,
            created_at__lte=until,
        ).count()

        active_user_ids = (
            set(
                jobs.filter(status__in=ACTIVE_ANNOTATOR_STATUSES, annotator__isnull=False).values_list(
                    "annotator_id", flat=True
                )
            )
            | set(
                jobs.filter(status__in=ACTIVE_QC1_STATUSES, qc1_reviewer__isnull=False).values_list(
                    "qc1_reviewer_id", flat=True
                )
            )
            | set(
                AuditSample.objects.filter(
                    audit__project=project,
                    audit__status=Audit.Status.IN_PROGRESS,
                    result=AuditSample.Result.PENDING,
                    auditor__isnull=False,
                ).values_list("auditor_id", flat=True)
            )
        )
        active_members = len(active_user_ids)

        alerts = []
        for job in jobs.filter(is_escalated=True).select_related("batch")[:10]:
            alerts.append({
                "level": "error",
                "type": "escalated",
                "job": job.id,
                "message": f"{job.name} vượt số vòng rework ({job.rework_round})",
            })
        for job in jobs.filter(deadline__lt=now, status__in=OPEN_STATUSES).order_by("deadline")[:10]:
            alerts.append({
                "level": "warning",
                "type": "overdue",
                "job": job.id,
                "message": f"{job.name} quá hạn từ {format_local_datetime(job.deadline)}",
            })
        for job in jobs.filter(
            deadline__gte=now, deadline__lte=now + timedelta(hours=24), status__in=OPEN_STATUSES
        ).order_by("deadline")[:10]:
            alerts.append({
                "level": "info",
                "type": "due_soon",
                "job": job.id,
                "message": f"{job.name} đến hạn lúc {format_local_datetime(job.deadline)}",
            })

        return Response({
            "counts": {
                "datasets": project.datasets.count(),
                "batches": total_batches,
                "ready_batches": ready_batches,
                "delivered_batches": delivered_batches,
                "overdue_batches": overdue_undelivered,
                "jobs": total_jobs,
                "remaining_jobs": remaining_jobs,
                "escalated": escalated_jobs,
                "overdue": totals["overdue"],
            },
            "by_status": by_status,
            "by_stage": by_stage,
            "stage_progress": stage_progress,
            "pending_decisions": pending_decisions,
            "errors_by_category": errors_by_category,
            "errors_by_severity": errors_by_severity,
            "metrics": {
                "total_objects": _metric(totals["objects"] or 0, formula="Tổng object-frame đồng bộ từ CVAT"),
                "total_frames": _metric(totals["frames"] or 0),
                "progress": _metric(
                    _pct(done_jobs, total_jobs),
                    formula="Job Đã duyệt + Đã bàn giao ÷ tổng job",
                ),
                "remaining_jobs": _metric(remaining_jobs, formula="Tổng job − job Đã duyệt/Đã bàn giao (TD07)"),
                "delivery_readiness": _metric(
                    _pct(ready_batches + delivered_batches, total_batches),
                    formula="Batch sẵn sàng giao + đã giao ÷ tổng batch (TD08)",
                    ready_batches=ready_batches,
                    delivered_batches=delivered_batches,
                    total_batches=total_batches,
                ),
                "delivered_rate": _metric(
                    _pct(delivered_batches, total_batches),
                    formula="Batch đã bàn giao ÷ tổng batch (TD09)",
                ),
                "delivery_on_time_rate": _metric(
                    _pct(on_time_deliveries, due_deliveries),
                    formula="Batch bàn giao đúng hạn ÷ (batch đã giao có deadline + batch quá hạn chưa giao) × 100% (DH07)",
                    on_time_deliveries=on_time_deliveries,
                    due_deliveries=due_deliveries,
                    late_deliveries=late_deliveries,
                    overdue_undelivered=overdue_undelivered,
                ),
                "rework_rate": _metric(
                    _pct(totals["reworked"] or 0, total_jobs),
                    formula="Job từng bị rework (total_rework_rounds > 0) ÷ tổng job (RW02)",
                ),
                "first_pass_yield": _metric(
                    fpy["value"],
                    formula="Job đạt QC1 lần đầu ÷ job đã có kết quả QC1 lần đầu (CL01)",
                    passed=fpy["passed"],
                    total=fpy["total"],
                ),
                "qc2_pass_rate": _metric(
                    _pct(qc2["passed"], qc2["decided"]),
                    formula="Mẫu QC2 Pass ÷ mẫu đã audit (AU05)",
                ),
                "quality_cl": _pending_quality_cl(),
                "defect_error_rate": _pending_defect_error_rate(),
                "defect_rate_by_severity": _pending_defect_rate_by_severity(),
                "dispute_overturn_rate": _metric(
                    dispute_overturn,
                    formula="error_dispute resolved ÷ (resolved + rejected) × 100% (CL09)",
                    resolved=dispute_agg["resolved"] or 0,
                    total=dispute_agg["total"] or 0,
                ),
                "estimated_completion": _metric(
                    None, status="pending_definition", formula="Chưa chốt cách ước tính (DB02/DB03)"
                ),
                "submitted_in_period": _metric(submitted, formula="Số lần job chuyển sang Chờ QC1 trong kỳ"),
                "active_members": _metric(
                    active_members,
                    formula="Số người duy nhất đang giữ việc mở trên Anno, QC1 và QC2 (TD11)",
                ),
            },
            "thresholds": {
                "quality_cl": _format_decimal(project.quality_cl_threshold),
                "defect_error_rate": _format_decimal(project.defect_rate_threshold),
            },
            "alerts": alerts,
        })


class TeamRankingView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/team-ranking/ — so sánh team theo sản lượng thực tế (SL05, KPI10, không N+1)."""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request: Any, project_id: Any) -> Response:
        teams = list(Team.objects.filter(project=self.project))
        team_members: dict[int, set[int]] = defaultdict(set)
        all_member_ids: set[int] = set()
        for team_id, user_id in TeamMember.objects.filter(team__project=self.project).values_list("team_id", "user_id"):
            team_members[team_id].add(user_id)
            all_member_ids.add(user_id)

        output_by_user: dict[int, dict[str, int]] = {}
        tracked_job_ids: set[int] = set()
        job_stats_by_user: dict[int, dict[str, Any]] = {}
        qc2_errors_by_user: dict[int, int] = {}

        if all_member_ids:
            tracked_job_ids = set(
                DailyOutputRecord.objects.filter(project=self.project)
                .values_list("job_id", flat=True)
                .distinct()
            )
            for r in (
                DailyOutputRecord.objects.filter(
                    project=self.project, user_id__in=all_member_ids, user__is_active=True
                )
                .values("user_id", "is_rework")
                .annotate(total=Sum("object_count"))
            ):
                bucket = output_by_user.setdefault(r["user_id"], {"fp": 0, "rw": 0})
                if r["is_rework"]:
                    bucket["rw"] += int(r["total"] or 0)
                else:
                    bucket["fp"] += int(r["total"] or 0)

            legacy_done_q = Q(status__in=DONE) & ~Q(pk__in=tracked_job_ids)
            job_stats_by_user = {
                row["annotator_id"]: row
                for row in Job.objects.filter(project=self.project, annotator_id__in=all_member_ids)
                .values("annotator_id")
                .annotate(
                    total=Count("id"),
                    done=Count("id", filter=Q(status__in=DONE)),
                    legacy_objects=Sum("object_count", filter=legacy_done_q),
                    reworked=Count("id", filter=_reworked_q()),
                    escalated=Count("id", filter=Q(is_escalated=True)),
                )
            }
            qc2_errors_by_user = dict(
                ReviewError.objects.filter(
                    job__project=self.project,
                    job__annotator_id__in=all_member_ids,
                    stage=ReviewStage.QC2,
                    is_voided=False,
                )
                .values("job__annotator_id")
                .annotate(n=Count("id"))
                .values_list("job__annotator_id", "n")
            )

        rows = []
        for team in teams:
            member_ids = team_members[team.id]
            total = sum(job_stats_by_user[uid]["total"] for uid in member_ids if uid in job_stats_by_user)
            done = sum(job_stats_by_user[uid]["done"] for uid in member_ids if uid in job_stats_by_user)
            legacy_objs = sum(
                int(job_stats_by_user[uid]["legacy_objects"] or 0) for uid in member_ids if uid in job_stats_by_user
            )
            reworked = sum(job_stats_by_user[uid]["reworked"] for uid in member_ids if uid in job_stats_by_user)
            escalated = sum(job_stats_by_user[uid]["escalated"] for uid in member_ids if uid in job_stats_by_user)
            qc2_errors = sum(qc2_errors_by_user.get(uid, 0) for uid in member_ids)
            fp_objs = sum(output_by_user.get(uid, {}).get("fp", 0) for uid in member_ids)
            rw_objs = sum(output_by_user.get(uid, {}).get("rw", 0) for uid in member_ids)
            produced = fp_objs + rw_objs
            objects_done = produced + legacy_objs
            rows.append({
                "team": {"id": team.id, "name": team.name},
                "members": len(member_ids),
                "jobs": total,
                "done": done,
                "objects_done": objects_done,
                "objects_produced": produced,
                "first_pass_objects": fp_objs,
                "rework_objects": rw_objs,
                "rework_rate": _pct(reworked, total),
                "escalated": escalated,
                "qc2_errors": qc2_errors,
            })

        # Team có sản lượng thực tế (> 0) luôn xếp trên team có objects_done == 0.
        rows.sort(
            key=lambda r: (
                r["objects_done"] == 0,
                -r["objects_done"],
                r["rework_rate"] if r["rework_rate"] is not None else 101.0,
                r["qc2_errors"],
                r["team"]["id"],
            )
        )
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        return Response({
            "formula": "Sản lượng cuboid thực hiện (giảm dần), rồi tỷ lệ rework (tăng dần)",
            "rows": rows,
        })


class Qc2SummaryView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/qc2-summary/ — dashboard QC2 (QC2-01). PM xem toàn dự án, QC2 xem của mình."""

    required_capabilities = {"*": [Cap.PERFORM_AUDIT, Cap.VIEW_DASHBOARD]}

    def get(self, request: Any, project_id: Any) -> Response:
        project = self.project
        user = request.user
        base_samples = AuditSample.objects.filter(audit__project=project)
        can_project_scope = self.has_cap(Cap.MANAGE_AUDITS) or self.has_cap(Cap.VIEW_DASHBOARD)
        scope = "project" if can_project_scope and request.query_params.get("scope") != "mine" else "mine"

        # Không tính cover hộ & không đếm trùng:
        # - Hàng chờ đang giữ (pending/overdue/due_soon/assigned): theo auditor được giao.
        # - Sản lượng & lỗi đã kiểm (passed/rejected/audited/kpi/trend/errors): theo đúng reviewed_by.
        if scope == "mine":
            queue_samples = base_samples.filter(auditor=user)
            reviewed_samples = base_samples.filter(reviewed_by=user)
            progress_samples = base_samples.filter(
                Q(result=AuditSample.Result.PENDING, auditor=user)
                | Q(result__in=[AuditSample.Result.PASS, AuditSample.Result.REJECT], reviewed_by=user)
            )
        else:
            queue_samples = base_samples
            reviewed_samples = base_samples
            progress_samples = base_samples

        now = timezone.now()
        since, until, prev_start, trend_days = _period_window(request, now=now)
        tz = app_timezone()
        today = local_date(now)
        today_start = _local_day_start(today)
        cutoff = now + timedelta(hours=24)
        pending_filter = Q(result=AuditSample.Result.PENDING, audit__status=Audit.Status.IN_PROGRESS)

        queue_stats = queue_samples.aggregate(
            assigned=Count("id"),
            pending=Count("id", filter=pending_filter),
            overdue=Count("id", filter=pending_filter & Q(job__deadline__lt=now)),
            due_soon=Count("id", filter=pending_filter & Q(job__deadline__gte=now, job__deadline__lte=cutoff)),
        )
        review_stats = reviewed_samples.aggregate(
            passed=Count("id", filter=Q(result=AuditSample.Result.PASS)),
            rejected=Count("id", filter=Q(result=AuditSample.Result.REJECT)),
            audited_in_period=Count("id", filter=Q(reviewed_at__gte=since, reviewed_at__lte=until)),
            audited_today=Count("id", filter=Q(reviewed_at__gte=today_start)),
        )
        stats = {
            "assigned": queue_stats["assigned"],
            "pending": queue_stats["pending"],
            "passed": review_stats["passed"],
            "rejected": review_stats["rejected"],
            "audited_in_period": review_stats["audited_in_period"],
            "audited_today": review_stats["audited_today"],
            "overdue": queue_stats["overdue"],
            "due_soon": queue_stats["due_soon"],
        }

        errors = ReviewError.objects.filter(audit_sample__in=reviewed_samples, is_voided=False)
        by_category = list(errors.values("category__name").annotate(n=Count("id")).order_by("-n")[:10])
        by_severity = _severity_breakdown(errors)
        by_batch = list(
            progress_samples.values("audit__batch_id", "audit__batch__name", "audit__batch__dataset__name")
            .annotate(total=Count("id"), done=Count("id", filter=~Q(result=AuditSample.Result.PENDING)))
            .order_by("audit__batch__dataset__name", "audit__batch__name")
        )
        reworked_after_audit = reviewed_samples.filter(result=AuditSample.Result.REJECT).values("job").distinct().count()

        current_win = self._window(reviewed_samples, errors, since, until, inclusive_end=True)
        prev_win = self._window(reviewed_samples, errors, prev_start, since, inclusive_end=False)
        kpi = {
            "current": current_win,
            "previous": prev_win,
            "comparison": {
                "audited": _delta_metrics(current_win["audited"], prev_win["audited"]),
                "passed": _delta_metrics(current_win["passed"], prev_win["passed"]),
                "rejected": _delta_metrics(current_win["rejected"], prev_win["rejected"]),
                "errors": _delta_metrics(current_win["errors"], prev_win["errors"]),
            },
        }

        start = today - timedelta(days=trend_days - 1)
        start_dt = _local_day_start(start)
        daily = {
            r["day"]: r
            for r in reviewed_samples.filter(reviewed_at__gte=start_dt)
            .annotate(day=TruncDate("reviewed_at", tzinfo=tz))
            .values("day")
            .annotate(audited=Count("id"), rejected=Count("id", filter=Q(result=AuditSample.Result.REJECT)))
        }
        daily_errors = dict(
            errors.filter(created_at__gte=start_dt)
            .annotate(day=TruncDate("created_at", tzinfo=tz))
            .values("day")
            .annotate(n=Count("id"))
            .values_list("day", "n")
        )
        trend = []
        for i in range(trend_days):
            day = start + timedelta(days=i)
            row = daily.get(day, {})
            trend.append({
                "date": day.isoformat(),
                "audited": row.get("audited", 0),
                "rejected": row.get("rejected", 0),
                "errors": daily_errors.get(day, 0),
            })

        return Response({
            "kpi": kpi,
            "kpi_target": project.kpi_qc2_target,
            "kpi_summary": _kpi_progress(review_stats["audited_today"] or 0, project.kpi_qc2_target),
            "trend": trend,
            "error_percent_in_job": _pending_defect_error_rate(),
            "defect_error_rate": _pending_defect_error_rate(),
            "quality_cl": _pending_quality_cl(),
            "defect_rate_by_severity": _pending_defect_rate_by_severity(),
            "audit_speed": _metric(
                None,
                status="pending_definition",
                formula="Chưa có dữ liệu thời gian bắt đầu / kết thúc audit từng job (NS04).",
            ),
            "scope": scope,
            "stats": stats,
            "pass_rate": _pct(stats["passed"], stats["passed"] + stats["rejected"]),
            "qc1_missed_errors": errors.count(),
            "reworked_after_audit": reworked_after_audit,
            "errors_by_category": [{"category": r["category__name"], "count": r["n"]} for r in by_category],
            "errors_by_severity": by_severity,
            "progress_by_batch": [
                {
                    "batch_id": r["audit__batch_id"],
                    "batch": r["audit__batch__name"],
                    "dataset_name": r["audit__batch__dataset__name"],
                    "total": r["total"],
                    "done": r["done"],
                }
                for r in by_batch
            ],
        })

    @staticmethod
    def _window(
        samples: Any, errors: Any, start: datetime, end: datetime, *, inclusive_end: bool = False
    ) -> dict[str, Any]:
        sample_end_q = Q(reviewed_at__lte=end) if inclusive_end else Q(reviewed_at__lt=end)
        err_end_q = Q(created_at__lte=end) if inclusive_end else Q(created_at__lt=end)
        stats = samples.filter(Q(reviewed_at__gte=start) & sample_end_q).aggregate(
            audited=Count("id"),
            passed=Count("id", filter=Q(result=AuditSample.Result.PASS)),
            rejected=Count("id", filter=Q(result=AuditSample.Result.REJECT)),
        )
        stats["pass_rate"] = _pct(stats["passed"], stats["audited"])
        stats["errors"] = errors.filter(Q(created_at__gte=start) & err_end_q).count()
        return stats


class MemberPerformanceView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/member-performance/ — hiệu suất từng annotator theo đúng actor (SL04)."""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request: Any, project_id: Any) -> Response:
        tracked_job_ids = set(
            DailyOutputRecord.objects.filter(project=self.project)
            .values_list("job_id", flat=True)
            .distinct()
        )
        legacy_done_q = Q(status__in=DONE) & ~Q(pk__in=tracked_job_ids)
        job_stats = {
            r["annotator"]: r
            for r in Job.objects.filter(project=self.project, annotator__isnull=False)
            .values("annotator")
            .annotate(
                total=Count("id"),
                done=Count("id", filter=Q(status__in=DONE)),
                legacy_objects=Sum("object_count", filter=legacy_done_q),
                reworked=Count("id", filter=_reworked_q()),
            )
        }
        output_stats: dict[int, dict[str, int]] = {}
        for r in (
            DailyOutputRecord.objects.filter(project=self.project, user__is_active=True)
            .values("user_id", "is_rework")
            .annotate(total=Sum("object_count"))
        ):
            bucket = output_stats.setdefault(r["user_id"], {"fp": 0, "rw": 0})
            if r["is_rework"]:
                bucket["rw"] += int(r["total"] or 0)
            else:
                bucket["fp"] += int(r["total"] or 0)

        user_ids = set(job_stats) | set(output_stats)
        users = {u.id: u for u in User.objects.filter(pk__in=user_ids)}
        rows = []
        for uid in user_ids:
            if uid not in users:
                continue
            js = job_stats.get(uid, {})
            os_ = output_stats.get(uid, {})
            fp = os_.get("fp", 0)
            rw = os_.get("rw", 0)
            produced = fp + rw
            objects_done = produced + int(js.get("legacy_objects") or 0)
            total_jobs = js.get("total", 0)
            rows.append({
                "user": UserBriefSerializer(users[uid]).data,
                "jobs": total_jobs,
                "done": js.get("done", 0),
                "objects_done": objects_done,
                "first_pass_objects": fp,
                "rework_objects": rw,
                "total_objects": produced,
                "rework_rate": _pct(js.get("reworked", 0), total_jobs),
            })
        rows.sort(key=lambda r: (-r["objects_done"], r["user"]["username"]))
        return Response(rows)


class AnnotatorDashboardView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/annotator/dashboard/?period=day|week|month — dashboard cá nhân của Annotator."""

    required_capabilities = {"*": Cap.ANNOTATE_JOBS}

    def get(self, request: Any, project_id: Any) -> Response:
        project = self.project
        user = request.user
        now = timezone.now()
        today = local_date(now)
        since, until, _, _ = _period_window(request, now=now)

        jobs = Job.objects.filter(project=project, annotator=user)
        totals = jobs.aggregate(
            total=Count("id"),
            pending_annotation=Count("id", filter=Q(status=JobStatus.PENDING_ANNOTATION)),
            annotating=Count("id", filter=Q(status=JobStatus.ANNOTATING)),
            rework=Count("id", filter=Q(status=JobStatus.REWORK)),
            waiting_review=Count(
                "id",
                filter=Q(
                    status__in=[
                        JobStatus.PENDING_QC1,
                        JobStatus.QC1_REVIEWING,
                        JobStatus.QC1_PASSED,
                        JobStatus.PENDING_QC2,
                    ]
                ),
            ),
            done=Count("id", filter=Q(status__in=DONE)),
            objects_done=Sum("object_count", filter=Q(status__in=DONE)),
            reworked=Count("id", filter=_reworked_q()),
            overdue=Count("id", filter=Q(deadline__lt=now, status__in=ACTIVE_ANNOTATOR_STATUSES)),
            due_soon_only=Count(
                "id",
                filter=Q(
                    deadline__gte=now,
                    deadline__lte=now + timedelta(hours=24),
                    status__in=ACTIVE_ANNOTATOR_STATUSES,
                ),
            ),
            escalated=Count("id", filter=Q(is_escalated=True)),
        )
        fpy = _fpy_stats(jobs)

        submitted_in_period = ActivityLog.objects.filter(
            project=project,
            actor=user,
            action="job.status",
            after__status=JobStatus.PENDING_QC1,
            created_at__gte=since,
            created_at__lte=until,
        ).count()

        my_errors = ReviewError.objects.filter(job__project=project, job__annotator=user, is_voided=False)
        top_errors = list(my_errors.values("category__name").annotate(n=Count("id")).order_by("-n")[:10])
        errors_by_severity = _severity_breakdown(my_errors)

        due_soon = (
            jobs.filter(
                status__in=ACTIVE_ANNOTATOR_STATUSES,
                deadline__lte=now + timedelta(hours=24),
            )
            .select_related("batch")
            .order_by("deadline", "id")[:10]
        )

        membership = (
            TeamMember.objects.filter(user=user, team__project=project)
            .select_related("team")
            .first()
        )
        team_name = membership.team.name if membership else None
        last_sync = project.cvat_synced_at
        if last_sync is None:
            last_sync = (
                Batch.objects.filter(project=project, last_synced_at__isnull=False)
                .order_by("-last_synced_at")
                .values_list("last_synced_at", flat=True)
                .first()
            )

        # TD01: tính trên toàn bộ job đang giữ (không cắt [:10])
        active_base = jobs.filter(status__in=ACTIVE_ANNOTATOR_STATUSES)
        active_agg = active_base.aggregate(
            active_jobs_count=Count("id"),
            active_object_frames=Coalesce(
                Sum(
                    Case(
                        When(target_object_count__gt=0, then=F("target_object_count")),
                        default=F("object_count"),
                        output_field=IntegerField(),
                    )
                ),
                0,
            ),
            max_rework_round_active=Coalesce(Max("rework_round", filter=Q(status=JobStatus.REWORK)), 0),
        )
        active_jobs_count = active_agg["active_jobs_count"]
        active_object_frames = active_agg["active_object_frames"]
        max_rework_round_active = active_agg["max_rework_round_active"]

        active_qs = order_by_db06_priority(
            active_base.select_related("batch", "dataset", "annotator", "qc1_reviewer", "project")
            .annotate(
                _active_rework_error_count=Count(
                    "review_errors",
                    filter=Q(
                        status__in=[JobStatus.REWORK, JobStatus.ANNOTATING],
                        review_errors__is_voided=False,
                        review_errors__rework_round=Greatest(F("total_rework_rounds"), F("rework_round")) - 1,
                    )
                    & (Q(rework_round__gt=0) | Q(total_rework_rounds__gt=0)),
                    distinct=True,
                )
            )
            .prefetch_related(
                Prefetch(
                    "audit_samples",
                    queryset=AuditSample.objects.filter(
                        audit__status=Audit.Status.IN_PROGRESS,
                        result=AuditSample.Result.PENDING,
                    )
                    .select_related("auditor")
                    .order_by("-id"),
                    to_attr="open_samples",
                )
            ),
            now=now,
        )
        active_jobs = list(active_qs[:10])

        # RW04: tổng lỗi chưa hủy thuộc đúng vòng hiện tại (rework_round == active_round) trên job đang REWORK.
        # Không dùng Max("rework_round") để tránh hồi sinh lỗi vòng cũ khi toàn bộ lỗi vòng mới bị void.
        pending_rework_errors = (
            ReviewError.objects.filter(
                job__project=project,
                job__annotator=user,
                job__status=JobStatus.REWORK,
                is_voided=False,
            )
            .filter(Q(job__rework_round__gt=0) | Q(job__total_rework_rounds__gt=0))
            .filter(rework_round=Greatest(F("job__total_rework_rounds"), F("job__rework_round")) - 1)
            .count()
        )

        # Việc cần sửa nổi bật tìm trên toàn bộ active_base (không bỏ sót sau vị trí thứ 10)
        rework_job = (
            order_by_db06_priority(active_base.filter(status=JobStatus.REWORK).select_related("batch"), now=now).first()
            or order_by_db06_priority(
                active_base.filter(rework_round__gt=0).select_related("batch"), now=now
            ).first()
        )
        rework_focus = None
        if rework_job is not None:
            active_round = max(rework_job.total_rework_rounds, rework_job.rework_round) - 1
            if active_round >= 0:
                err_all = list(
                    rework_job.review_errors.filter(is_voided=False, rework_round=active_round)
                    .select_related("category", "reported_by")
                    .order_by("-created_at")
                )
            else:
                err_all = []
            err_list = err_all[:5]
            total_errs = len(err_all)
            if rework_job.rework_scope == ReworkScope.FULL:
                pending_frames = rework_job.object_count or rework_job.target_object_count
            else:
                ex_cnt, ms_cnt = _count_unique_error_targets(err_all)
                pending_frames = ex_cnt + ms_cnt
            rework_focus = {
                "job_id": rework_job.id,
                "job_name": rework_job.name,
                "batch_name": rework_job.batch.name,
                "deadline": format_rfc3339_utc(rework_job.deadline),
                "rework_round": rework_job.rework_round,
                "max_rework_rounds": project.max_rework_rounds,
                "rework_scope": rework_job.rework_scope,
                "rework_scope_label": rework_job.get_rework_scope_display(),
                "error_count": total_errs,
                "pending_object_frames": pending_frames,
                "errors": ReviewErrorBriefSerializer(err_list, many=True).data,
            }

        # Kết quả 7 ngày gần nhất theo giờ Việt Nam từ DailyOutputRecord (tách rõ SUBMIT vs CVAT_SYNC)
        start_day = today - timedelta(days=6)
        out = _daily_output_breakdown(project, user, start_day, today)
        daily_target = project.kpi_annotation_target or 0
        daily_results = []
        for offset in range(6, -1, -1):
            d = today - timedelta(days=offset)
            fp = out["fp_total"].get(d, 0)
            rw = out["rw_total"].get(d, 0)
            sub_d = out["submitted_total"].get(d, 0)
            sync_d = out["cvat_sync_total"].get(d, 0)
            total_d = fp + rw
            daily_results.append({
                "date": d.isoformat(),
                "label": d.strftime("%d/%m"),
                "first_pass_objects": fp,
                "rework_objects": rw,
                "submitted_objects": sub_d,
                "unsubmitted_cvat_objects": sync_d,
                "total_objects": total_d,
                "target_objects": daily_target,
                "is_off_day": total_d == 0 and d.weekday() == 6,
            })

        # DH06: tỷ lệ nộp đúng hạn theo lịch sử nộp (ưu tiên deadline snapshot lúc nộp) + job active quá hạn
        sub_events = list(
            ActivityLog.objects.filter(
                project=project,
                actor=user,
                action="job.status",
                after__status=JobStatus.PENDING_QC1,
            )
            .select_related("job")
            .only("created_at", "after", "job__deadline")
        )
        dated_events: list[tuple[datetime, datetime]] = []
        for ev in sub_events:
            dl = _extract_log_deadline(ev)
            if dl is not None:
                dated_events.append((ev.created_at, dl))

        active_overdue_count = totals["overdue"] or 0
        if dated_events:
            submitted_total = len(dated_events) + active_overdue_count
            on_time_count = sum(1 for created_at, dl in dated_events if created_at <= dl)
        else:
            active_overdue_q = Q(status__in=ACTIVE_ANNOTATOR_STATUSES, deadline__lt=now)
            on_time_agg = jobs.filter(deadline__isnull=False).aggregate(
                evaluated=Count("id", filter=Q(submitted_at__isnull=False) | active_overdue_q),
                on_time=Count(
                    "id",
                    filter=Q(submitted_at__isnull=False, submitted_at__lte=F("deadline")) & ~active_overdue_q,
                ),
            )
            submitted_total = on_time_agg["evaluated"]
            on_time_count = on_time_agg["on_time"]

        # Sản lượng hôm nay (không fallback sang tích luỹ toàn thời gian)
        today_first_pass = out["fp_total"].get(today, 0)
        today_rework = out["rw_total"].get(today, 0)
        today_submitted = out["submitted_total"].get(today, 0)
        today_unsubmitted = out["cvat_sync_total"].get(today, 0)
        actual_objects = today_first_pass + today_rework
        kpi_prog = _kpi_progress(actual_objects, project.kpi_annotation_target)

        req_qs = AnnotatorRequest.objects.filter(project=project, created_by=user).select_related(
            "job__batch", "review_error__category", "job_issue", "created_by", "handler"
        )
        pending_req_count = req_qs.filter(status=AnnotatorRequest.Status.PENDING_PM).count()
        recent_req_items = AnnotatorRequestSerializer(req_qs[:5], many=True).data

        return Response({
            "counts": {
                "total": totals["total"],
                "pending_annotation": totals["pending_annotation"],
                "annotating": totals["annotating"],
                "rework": totals["rework"],
                "waiting_review": totals["waiting_review"],
                "done": totals["done"],
                "overdue": totals["overdue"],
                "due_soon": totals["due_soon_only"],
                "escalated": totals["escalated"],
            },
            "objects_done": totals["objects_done"] or 0,
            "submitted_in_period": _metric(
                submitted_in_period,
                formula="Số lần bạn nộp bài sang Chờ QC1 trong kỳ",
            ),
            "rework_rate": _metric(
                _pct(totals["reworked"], totals["total"]),
                formula="Job từng bị trả rework (total_rework_rounds > 0) ÷ tổng job được giao (RW02)",
            ),
            "first_pass_yield": _metric(
                fpy["value"],
                formula="Job qua QC1 ngay lần đầu ÷ tổng job đã có kết quả QC1 lần đầu (CL01)",
                passed=fpy["passed"],
                total=fpy["total"],
            ),
            "kpi_target": project.kpi_annotation_target,
            "errors_by_category": [{"category": r["category__name"], "count": r["n"]} for r in top_errors],
            "errors_by_severity": errors_by_severity,
            "due_soon": [
                {
                    "id": j.id,
                    "name": j.name,
                    "batch_name": j.batch.name,
                    "status": j.status,
                    "deadline": format_rfc3339_utc(j.deadline),
                    "is_overdue": bool(j.deadline is not None and j.deadline < now),
                }
                for j in due_soon
            ],
            "meta": {
                "team_name": team_name,
                "project_name": project.name,
                "last_cvat_sync_at": format_rfc3339_utc(last_sync),
                "wip_limit": project.annotator_wip_limit,
                "active_jobs_count": active_jobs_count,
                "active_object_frames": active_object_frames,
            },
            "kpi_summary": {
                "actual_objects": actual_objects,
                "today_first_pass": today_first_pass,
                "today_rework": today_rework,
                "today_submitted_objects": today_submitted,
                "today_unsubmitted_cvat_objects": today_unsubmitted,
                "target_objects": kpi_prog["target"],
                "achievement_pct": kpi_prog["achievement_pct"],
                "shortfall": kpi_prog["shortfall"],
                "surplus": kpi_prog["surplus"],
                "rework_jobs_count": totals["rework"],
                "pending_rework_errors": pending_rework_errors,
                "max_rework_round_active": max_rework_round_active,
                "max_rework_rounds": project.max_rework_rounds,
                "due_soon_count": totals["due_soon_only"],
                "overdue_count": totals["overdue"],
                "fpy_pct": fpy["value"],
                "fpy_passed": fpy["passed"],
                "fpy_total": fpy["total"],
                "on_time_pct": _pct(on_time_count, submitted_total),
                "on_time_count": on_time_count,
                "submitted_total": submitted_total,
            },
            "next_jobs": JobSerializer(active_jobs, many=True).data,
            "rework_focus": rework_focus,
            "daily_results": daily_results,
            "recent_requests": {
                "pending_count": pending_req_count,
                "items": recent_req_items,
            },
        })


class AnnotatorAnalyticsView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/annotator/analytics/?range=7d|30d|week — Phân tích cá nhân P2 (PQ01, KPI10)."""

    required_capabilities = {"*": Cap.ANNOTATE_JOBS}

    def get(self, request: Any, project_id: Any) -> Response:
        project = self.project
        user = request.user
        now = timezone.now()
        today = local_date(now)
        iso_year, iso_week, _ = today.isocalendar()
        range_key = request.query_params.get("range", "7d")
        if range_key not in ("7d", "30d", "week"):
            range_key = "7d"

        if range_key == "30d":
            days = 30
            start_date = today - timedelta(days=29)
        elif range_key == "week":
            start_date = today - timedelta(days=today.weekday())
            days = (today - start_date).days + 1
        else:
            days = 7
            start_date = today - timedelta(days=6)

        week_start = today - timedelta(days=today.weekday())
        query_start_date = min(start_date, week_start)
        start_dt = _local_day_start(start_date)
        prev_start_date = start_date - timedelta(days=days)

        # 1. Sản lượng theo ngày từ DailyOutputRecord (tách rõ first_pass/rework & SUBMIT vs CVAT_SYNC)
        out = _daily_output_breakdown(project, user, query_start_date, today)

        # 2. Giờ làm phiên thực tế theo từng loại (NS01, NS03): tách riêng giờ lần đầu & giờ rework, hợp nhất khi WIP>=2
        logs = list(
            ActivityLog.objects.filter(
                project=project,
                actor=user,
                action="job.status",
                after__status=JobStatus.PENDING_QC1,
                created_at__gte=start_dt,
            )
            .select_related("job")
            .order_by("created_at")
        )
        job_ids = {log.job_id for log in logs if log.job_id}
        start_times_by_job: dict[int, list[datetime]] = {}
        if job_ids:
            for start_log in (
                ActivityLog.objects.filter(
                    project=project,
                    actor=user,
                    job_id__in=job_ids,
                    action="job.status",
                    after__status=JobStatus.ANNOTATING,
                    created_at__lte=now,
                )
                .order_by("created_at", "id")
                .only("job_id", "created_at")
            ):
                if start_log.job_id is not None:
                    start_times_by_job.setdefault(start_log.job_id, []).append(start_log.created_at)

        day_fp_intervals: dict[date, list[tuple[datetime, datetime]]] = defaultdict(list)
        day_rw_intervals: dict[date, list[tuple[datetime, datetime]]] = defaultdict(list)
        measured_fp_jobs: dict[date, set[int]] = defaultdict(set)
        measured_rw_jobs: dict[date, set[int]] = defaultdict(set)

        for log in logs:
            d = local_date(log.created_at)
            after = log.after or {}
            is_rw = after.get("event") == "annotator.resubmit" or (after.get("rework_round") or 0) > 0

            session_start = None
            starts = start_times_by_job.get(log.job_id) if log.job_id else None
            if starts:
                idx = bisect_right(starts, log.created_at) - 1
                if idx >= 0:
                    session_start = starts[idx]
            if (
                session_start is None
                and not is_rw
                and log.job
                and log.job.started_at
                and log.job.annotator_id == user.id
            ):
                session_start = log.job.started_at

            if session_start and log.created_at > session_start:
                clamped_end = max(
                    session_start + timedelta(minutes=15),
                    min(log.created_at, session_start + timedelta(hours=10)),
                )
                interval = (session_start, clamped_end)
                if is_rw:
                    day_rw_intervals[d].append(interval)
                    if log.job_id is not None:
                        measured_rw_jobs[d].add(log.job_id)
                else:
                    day_fp_intervals[d].append(interval)
                    if log.job_id is not None:
                        measured_fp_jobs[d].add(log.job_id)

        daily_productivity = []
        total_objects = 0
        total_submitted = 0
        total_unsubmitted_cvat = 0
        measured_objects = 0
        total_hours = 0.0
        active_days = 0
        for i in range(days):
            d = start_date + timedelta(days=i)
            fp = out["fp_total"].get(d, 0)
            rw = out["rw_total"].get(d, 0)
            sub_d = out["submitted_total"].get(d, 0)
            sync_d = out["cvat_sync_total"].get(d, 0)
            day_total = fp + rw
            is_off = day_total == 0 and d.weekday() == 6

            fp_iv = day_fp_intervals.get(d, [])
            rw_iv = day_rw_intervals.get(d, [])
            fp_hrs = min(24.0, _merged_hours(fp_iv))
            rw_hrs = min(24.0, _merged_hours(rw_iv))
            # Hợp nhất cả 2 nhánh (không bịa 7.5h, không cộng đúp khi WIP >= 2 chạy song song)
            hrs = min(24.0, _merged_hours(fp_iv + rw_iv))

            fp_measured = sum(
                cnt for jid, cnt in out["fp_by_job"].get(d, {}).items() if jid in measured_fp_jobs.get(d, set())
            )
            rw_measured = sum(
                cnt for jid, cnt in out["rw_by_job"].get(d, {}).items() if jid in measured_rw_jobs.get(d, set())
            )

            if day_total > 0:
                active_days += 1
                total_objects += day_total
                total_submitted += sub_d
                total_unsubmitted_cvat += sync_d
            if hrs > 0:
                total_hours += hrs
                if fp_hrs > 0:
                    measured_objects += fp_measured
                if rw_hrs > 0:
                    measured_objects += rw_measured

            day_measured = (fp_measured if fp_hrs > 0 else 0) + (rw_measured if rw_hrs > 0 else 0)
            daily_productivity.append({
                "date": d.isoformat(),
                "label": d.strftime("%d/%m"),
                "first_pass_objects": fp,
                "rework_objects": rw,
                "submitted_objects": sub_d,
                "unsubmitted_cvat_objects": sync_d,
                "measured_objects": day_measured,
                "first_pass_per_hour": round(fp_measured / fp_hrs, 1) if fp_hrs > 0 else None,
                "rework_per_hour": round(rw_measured / rw_hrs, 1) if rw_hrs > 0 else None,
                "hours": round(hrs, 1),
                "hours_status": "provisional" if hrs > 0 else "unavailable",
                "is_off_day": is_off,
            })

        objects_per_hour = round(measured_objects / total_hours) if total_hours > 0 else None

        # 3. Dự báo sản lượng tuần hiện tại (DB05 · KPI01)
        avg_daily = round(total_objects / active_days) if active_days > 0 else 0
        remaining_workdays = sum(
            1 for offset in range(7) if (week_start + timedelta(days=offset)) > today and offset < 6
        )
        estimated_objects = avg_daily * remaining_workdays
        daily_target = project.kpi_annotation_target or 0

        weekly_series = []
        for offset in range(7):
            d = week_start + timedelta(days=offset)
            if d <= today:
                actual = out["fp_total"].get(d, 0) + out["rw_total"].get(d, 0)
                weekly_series.append({
                    "date": d.isoformat(),
                    "day_label": d.strftime("%d"),
                    "actual_objects": actual,
                    "forecast_objects": 0,
                    "is_forecast": False,
                    "is_off_day": actual == 0 and d.weekday() == 6,
                })
            else:
                is_sun = d.weekday() == 6
                weekly_series.append({
                    "date": d.isoformat(),
                    "day_label": d.strftime("%d"),
                    "actual_objects": 0,
                    "forecast_objects": 0 if is_sun else avg_daily,
                    "is_forecast": True,
                    "is_off_day": is_sun,
                })

        # 4. Xếp hạng sản lượng cá nhân (KPI10) — tổng hợp trên DB từ DailyOutputRecord (chỉ user đang hoạt động)
        annotator_ids = list(
            RoleAssignment.objects.filter(project=project, role=Role.ANNOTATOR, user__is_active=True)
            .values_list("user_id", flat=True)
            .distinct()
        )
        if user.id not in annotator_ids:
            annotator_ids.append(user.id)

        def _rank_for_window(w_start: date, w_end_inclusive: date, *, none_if_empty: bool = False) -> int | None:
            rows = list(
                DailyOutputRecord.objects.filter(
                    project=project,
                    user_id__in=annotator_ids,
                    user__is_active=True,
                    work_date__gte=w_start,
                    work_date__lte=w_end_inclusive,
                )
                .values("user_id")
                .annotate(total=Sum("object_count"))
            )
            if not rows:
                return None if none_if_empty else 1
            scores = {uid: 0 for uid in annotator_ids}
            for row in rows:
                scores[row["user_id"]] = int(row["total"] or 0)
            if none_if_empty and all(v == 0 for v in scores.values()):
                return None
            my_score = scores.get(user.id, 0)
            return 1 + sum(1 for v in scores.values() if v > my_score)

        current_rank = _rank_for_window(start_date, today, none_if_empty=False)
        previous_rank = _rank_for_window(prev_start_date, start_date - timedelta(days=1), none_if_empty=True)

        return Response({
            "range": range_key,
            "week_label": f"Tuần {iso_week}",
            "iso_year": iso_year,
            "avg_productivity": {
                "objects_per_hour": objects_per_hour,
                "measured_objects": measured_objects,
                "total_objects": total_objects,
                "submitted_objects": total_submitted,
                "unsubmitted_cvat_objects": total_unsubmitted_cvat,
                "total_hours": round(total_hours, 1),
                "status": "provisional" if total_hours > 0 else "unavailable",
                "formula": (
                    "Sản lượng thuộc các phiên đã nộp có đo thời gian (measured_objects) "
                    "÷ tổng giờ phiên ước tính (NS03)"
                ),
                "hours_provenance": {
                    "source": "workflow_elapsed_session",
                    "status": "provisional" if total_hours > 0 else "unavailable",
                    "unit": "hours",
                    "clamp_min_minutes": 15,
                    "clamp_max_minutes": 600,
                    "description": (
                        "Ước tính từ khoảng phiên làm việc (ANNOTATING → PENDING_QC1, "
                        "giới hạn [15 phút, 10 giờ]/phiên, hợp nhất khi WIP ≥ 2)."
                    ),
                },
            },
            "forecast": {
                "estimated_objects": estimated_objects,
                "avg_daily_objects": avg_daily,
                "remaining_workdays": remaining_workdays,
                "daily_target": daily_target,
            },
            "ranking": {
                "rank": current_rank,
                "total_annotators": len(annotator_ids),
                "previous_rank": previous_rank,
            },
            "daily_productivity": daily_productivity,
            "weekly_forecast_series": weekly_series,
        })


class Qc1SummaryView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/qc1-summary/?period=day|week|month — dashboard Level 1 QC."""

    required_capabilities = {"*": [Cap.PERFORM_QC1, Cap.VIEW_DASHBOARD]}

    def get(self, request: Any, project_id: Any) -> Response:
        project = self.project
        user = request.user
        scope = "project" if self.has_cap(Cap.VIEW_DASHBOARD) and request.query_params.get("scope") != "mine" else "mine"

        now = timezone.now()
        since, until, prev_start, trend_days = _period_window(request, now=now)
        tz = app_timezone()
        today = local_date(now)
        today_start = _local_day_start(today)
        cutoff = now + timedelta(hours=24)

        jobs = Job.objects.filter(project=project)
        logs = ActivityLog.objects.filter(project=project, action__in=["qc1.pass", "qc1.reject"])
        qc1_errors = ReviewError.objects.filter(job__project=project, stage=ReviewStage.QC1, is_voided=False)

        pool_q = Q(
            qc1_reviewer__isnull=True,
            status=JobStatus.PENDING_QC1,
            is_locked=False,
            batch__status=DataStatus.ACTIVE,
            dataset__status=DataStatus.ACTIVE,
        )
        if project.escalation_policy == EscalationPolicy.BLOCK:
            pool_q &= Q(is_escalated=False)

        qc1_open = Q(status__in=ACTIVE_QC1_STATUSES)
        if scope == "mine":
            jobs = jobs.filter(qc1_reviewer=user)
            logs = logs.filter(actor=user)
            qc1_errors = qc1_errors.filter(reported_by=user)

            mine_agg = jobs.aggregate(
                assigned=Count("id", filter=qc1_open),
                my_pending=Count("id", filter=Q(status=JobStatus.PENDING_QC1)),
                reviewing=Count("id", filter=Q(status=JobStatus.QC1_REVIEWING)),
                qc1_passed=Count("id", filter=Q(status=JobStatus.QC1_PASSED)),
                overdue=Count("id", filter=qc1_open & Q(deadline__lt=now)),
                due_soon=Count("id", filter=qc1_open & Q(deadline__gte=now, deadline__lte=cutoff)),
            )
            hist_ann_job_ids = (
                ActivityLog.objects.filter(project=project, actor=user, job_id__isnull=False)
                .filter(
                    Q(action__in=ANNOTATOR_EVENTS)
                    | Q(action__in=("job.status", "job.assign"), after__event__in=ANNOTATOR_EVENTS)
                    | Q(action="job.status", after__status__in=[JobStatus.ANNOTATING, JobStatus.PENDING_QC1])
                )
                .values("job_id")
            )
            hist_qc2_sample_job_ids = (
                AuditSample.objects.filter(audit__project=project)
                .filter(Q(auditor=user) | Q(reviewed_by=user))
                .values("job_id")
            )
            hist_qc2_err_job_ids = ReviewError.objects.filter(
                job__project=project, stage=ReviewStage.QC2, reported_by=user
            ).values("job_id")
            hist_qc2_issue_job_ids = JobIssue.objects.filter(
                project=project,
                authority_status=JobIssue.AuthorityStatus.VALID,
                author_stage=JobIssue.AuthorStage.QC2,
                author=user,
            ).values("job_id")
            t_ids = user_team_ids(project, user)
            team_pool_q = (Q(batch__team_id__in=t_ids) | Q(batch__team__isnull=True)) if t_ids else Q(
                batch__team__isnull=True
            )
            pool_pending = (
                Job.objects.filter(project=project)
                .filter(pool_q & team_pool_q)
                .exclude(
                    Q(annotator=user)
                    | Q(pk__in=hist_ann_job_ids)
                    | Q(pk__in=hist_qc2_sample_job_ids)
                    | Q(pk__in=hist_qc2_err_job_ids)
                    | Q(pk__in=hist_qc2_issue_job_ids)
                )
                .count()
            )
            queue_stats = {
                "assigned": mine_agg["assigned"],
                "pending": mine_agg["my_pending"] + pool_pending,
                "pool_pending": pool_pending,
                "reviewing": mine_agg["reviewing"],
                "qc1_passed": mine_agg["qc1_passed"],
                "overdue": mine_agg["overdue"],
                "due_soon": mine_agg["due_soon"],
            }
        else:
            queue_stats = jobs.aggregate(
                assigned=Count("id", filter=qc1_open & Q(qc1_reviewer__isnull=False)),
                pending=Count("id", filter=Q(status=JobStatus.PENDING_QC1, qc1_reviewer__isnull=False) | pool_q),
                pool_pending=Count("id", filter=pool_q),
                reviewing=Count("id", filter=Q(status=JobStatus.QC1_REVIEWING)),
                qc1_passed=Count("id", filter=Q(status=JobStatus.QC1_PASSED)),
                overdue=Count("id", filter=qc1_open & Q(deadline__lt=now)),
                due_soon=Count("id", filter=qc1_open & Q(deadline__gte=now, deadline__lte=cutoff)),
            )

        # CL06 & CL07: neo thời điểm trên AuditSample.created_at (KHÔNG dùng Audit.created_at),
        # bao gồm cả job qua QC1 qua qc1.pass lẫn job đồng bộ CVAT sang QC1_PASSED / PENDING_QC2,
        # loại bỏ lỗi is_voided=True và verdict=EDGE, đồng bộ giữa qc2_escape_errors và escaped_jobs.
        qc1_pass_history: dict[int, tuple[list[datetime], list[int | None]]] = {}
        for jid, action, passed_at, actor_id, job_qc1_id in (
            ActivityLog.objects.filter(project=project, job_id__isnull=False)
            .filter(
                Q(action="qc1.pass", actor_id__isnull=False)
                | Q(action="job.status", after__status__in=[JobStatus.QC1_PASSED, JobStatus.PENDING_QC2])
            )
            .order_by("created_at", "id")
            .values_list("job_id", "action", "created_at", "actor_id", "job__qc1_reviewer_id")
        ):
            if jid is None:
                continue
            resp_id: int | None = actor_id if action == "qc1.pass" else job_qc1_id
            times, actors = qc1_pass_history.setdefault(jid, ([], []))
            times.append(passed_at)
            actors.append(resp_id)

        def _matches_scope(job_obj: Job, ref_time: datetime) -> bool:
            hist = qc1_pass_history.get(job_obj.pk)
            if hist:
                times, actors = hist
                idx = bisect_right(times, ref_time) - 1
                if idx < 0:
                    return False
                resp_uid = actors[idx]
                return True if scope == "project" else resp_uid == user.id
            # Fallback cho job nhập trực tiếp từ CVAT ở trạng thái QC1_PASSED hoặc fixture đặt sẵn
            if (
                job_obj.status in REACHED_QC2
                or job_obj.first_qc1_result == FirstQc1Result.PASS
                or job_obj.qc1_reviewer_id is not None
            ):
                return True if scope == "project" else job_obj.qc1_reviewer_id == user.id
            return scope == "project"

        decided_samples = list(
            AuditSample.objects.filter(
                audit__project=project,
                result__in=[AuditSample.Result.PASS, AuditSample.Result.REJECT],
                created_at__gte=since,
                created_at__lte=until,
            ).select_related("job")
        )
        audited_job_ids: set[int] = set()
        for sample in decided_samples:
            if _matches_scope(sample.job, sample.created_at):
                audited_job_ids.add(sample.job_id)

        qc2_errors_all = list(
            ReviewError.objects.filter(
                job__project=project,
                stage=ReviewStage.QC2,
                is_voided=False,
                verdict=ErrorVerdict.FAIL,
            )
            .filter(
                Q(
                    audit_sample__isnull=False,
                    audit_sample__result__in=[AuditSample.Result.PASS, AuditSample.Result.REJECT],
                    audit_sample__created_at__gte=since,
                    audit_sample__created_at__lte=until,
                )
                | Q(audit_sample__isnull=True, created_at__gte=since, created_at__lte=until)
            )
            .select_related("job", "job__batch", "audit_sample", "category", "reported_by")
            .order_by("-created_at", "-id")
        )
        matched_escape_errors: list[ReviewError] = []
        for err in qc2_errors_all:
            ref_time = err.audit_sample.created_at if err.audit_sample is not None else err.created_at
            if _matches_scope(err.job, ref_time):
                matched_escape_errors.append(err)

        escaped_job_ids = {err.job_id for err in matched_escape_errors}
        audited_job_ids |= escaped_job_ids
        audited_jobs_count = len(audited_job_ids)
        escaped_jobs_count = len(escaped_job_ids)
        qc1_escape_job_rate = _pct(escaped_jobs_count, audited_jobs_count)
        qc2_escape_error_count = len(matched_escape_errors)
        escape_errors = [
            {
                "id": err.id,
                "job_id": err.job_id,
                "job_name": err.job.name,
                "batch_name": err.job.batch.name,
                "category": err.category.name,
                "severity": err.severity,
                "verdict": err.verdict,
                "frame_number": err.frame_number,
                "cvat_object_id": err.cvat_object_id,
                "is_missing_object": err.is_missing_object,
                "location": err.location,
                "description": err.description,
                "reported_by": UserBriefSerializer(err.reported_by).data if err.reported_by else None,
                "created_at": format_rfc3339_utc(err.created_at),
            }
            for err in matched_escape_errors[:20]
        ]

        decision_stats = logs.aggregate(
            passed=Count("id", filter=Q(action="qc1.pass")),
            rejected=Count("id", filter=Q(action="qc1.reject")),
            reviewed_in_period=Count("id", filter=Q(created_at__gte=since, created_at__lte=until)),
            reviewed_today=Count("id", filter=Q(created_at__gte=today_start)),
        )
        stats = {
            **queue_stats,
            "passed": decision_stats["passed"],
            "rejected": decision_stats["rejected"],
            "reviewed_in_period": decision_stats["reviewed_in_period"],
            "reviewed_today": decision_stats["reviewed_today"],
        }

        # DH06 cho QC1: tỷ lệ hoàn tất kiểm QC1 đúng hạn trong kỳ
        qc1_dated: list[tuple[datetime, datetime]] = []
        for log in (
            logs.filter(created_at__gte=since, created_at__lte=until)
            .select_related("job")
            .only("created_at", "after", "job__deadline")
        ):
            dl = _extract_log_deadline(log)
            if dl is not None:
                qc1_dated.append((log.created_at, dl))
        on_time_total = len(qc1_dated)
        on_time_count = sum(1 for created_at, dl in qc1_dated if created_at <= dl)
        on_time_pct = _pct(on_time_count, on_time_total)

        current_win = self._window(logs, qc1_errors, since, until, inclusive_end=True)
        prev_win = self._window(logs, qc1_errors, prev_start, since, inclusive_end=False)
        kpi = {
            "current": current_win,
            "previous": prev_win,
            "comparison": {
                "reviewed": _delta_metrics(current_win["reviewed"], prev_win["reviewed"]),
                "passed": _delta_metrics(current_win["passed"], prev_win["passed"]),
                "rejected": _delta_metrics(current_win["rejected"], prev_win["rejected"]),
                "errors": _delta_metrics(current_win["errors"], prev_win["errors"]),
            },
        }

        start = today - timedelta(days=trend_days - 1)
        start_dt = _local_day_start(start)
        daily = {
            r["day"]: r
            for r in logs.filter(created_at__gte=start_dt)
            .annotate(day=TruncDate("created_at", tzinfo=tz))
            .values("day")
            .annotate(
                reviewed=Count("id"),
                rejected=Count("id", filter=Q(action="qc1.reject")),
            )
        }
        daily_errors = dict(
            qc1_errors.filter(created_at__gte=start_dt)
            .annotate(day=TruncDate("created_at", tzinfo=tz))
            .values("day")
            .annotate(n=Count("id"))
            .values_list("day", "n")
        )
        trend = []
        for i in range(trend_days):
            day = start + timedelta(days=i)
            row = daily.get(day, {})
            trend.append({
                "date": day.isoformat(),
                "reviewed": row.get("reviewed", 0),
                "rejected": row.get("rejected", 0),
                "errors": daily_errors.get(day, 0),
            })

        by_category = list(qc1_errors.values("category__name").annotate(n=Count("id")).order_by("-n")[:10])
        by_severity = _severity_breakdown(qc1_errors)
        fpy = _fpy_stats(jobs)

        return Response({
            "scope": scope,
            "stats": stats,
            "pass_rate": _pct(stats["passed"], stats["passed"] + stats["rejected"]),
            "on_time_pct": on_time_pct,
            "on_time_count": on_time_count,
            "on_time_total": on_time_total,
            "first_pass_yield": _metric(
                fpy["value"],
                formula="Job đạt QC1 ngay lần đầu ÷ tổng job đã có kết quả QC1 lần đầu (CL01)",
                passed=fpy["passed"],
                total=fpy["total"],
            ),
            "kpi": kpi,
            "kpi_summary": _kpi_progress(decision_stats["reviewed_today"] or 0, project.kpi_qc1_target),
            "trend": trend,
            "qc2_escape_errors": qc2_escape_error_count,
            "qc1_escape_job_rate": qc1_escape_job_rate,
            "escaped_jobs": escaped_jobs_count,
            "escaped_jobs_count": escaped_jobs_count,
            "audited_jobs_count": audited_jobs_count,
            "escape_errors": escape_errors,
            "errors_by_category": [{"category": r["category__name"], "count": r["n"]} for r in by_category],
            "errors_by_severity": by_severity,
            "kpi_target": project.kpi_qc1_target,
        })

    @staticmethod
    def _window(
        logs: Any, errors: Any, start: datetime, end: datetime, *, inclusive_end: bool = False
    ) -> dict[str, Any]:
        end_q = Q(created_at__lte=end) if inclusive_end else Q(created_at__lt=end)
        stats = logs.filter(Q(created_at__gte=start) & end_q).aggregate(
            reviewed=Count("id"),
            passed=Count("id", filter=Q(action="qc1.pass")),
            rejected=Count("id", filter=Q(action="qc1.reject")),
        )
        stats["pass_rate"] = _pct(stats["passed"], stats["reviewed"])
        stats["errors"] = errors.filter(Q(created_at__gte=start) & end_q).count()
        return stats
