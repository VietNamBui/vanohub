"""Dashboard & KPI. Tổng hợp dữ liệu từ projects, jobs, quality, teams.

QUY ƯỚC: chỉ số nào chưa chốt công thức thì trả về value=None kèm status="pending_definition".
Chỉ số "tạm tính" (provisional) có ghi rõ công thức đang dùng.
"""

from bisect import bisect_right
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.datetime_utils import app_timezone, format_rfc3339_utc, parse_rfc3339_datetime
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
from jobs.views import _count_unique_error_targets, order_by_db06_priority
from projects.models import ActivityLog, Batch, DataStatus
from quality.models import Audit, AuditSample, ErrorVerdict, ReviewError, ReviewStage, Severity
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
SEVERITY_RANK: dict[str, int] = {
    Severity.MINOR.value: 1,
    Severity.MAJOR.value: 2,
    Severity.CRITICAL.value: 3,
}


def _metric(value: Any, *, status: str = "ok", formula: str = "", **extra: Any) -> dict[str, Any]:
    return {"value": value, "status": status, "formula": formula, **extra}


def _pct(part: int | float, whole: int | float, digits: int = 1) -> float | None:
    return round(part * 100 / whole, digits) if whole else None


def _period_start(request, *, now: datetime | None = None) -> datetime:
    days = PERIODS.get(request.query_params.get("period", "week"), 7)
    return (now or timezone.now()) - timedelta(days=days)


def _user_timezone(user: Any = None) -> ZoneInfo:
    return app_timezone()


def _local_day_start(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, datetime.min.time()))


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
    """RW02: job từng bị trả rework (không bị mất khi PM resolve-escalation đặt lại rework_round=0)."""
    return Q(total_rework_rounds__gt=0) | Q(rework_round__gt=0)


def _fpy_stats(jobs_qs) -> dict[str, Any]:
    """CL01: FPY tại QC1 theo trường bất biến first_qc1_result (có fallback cho fixture cũ)."""
    explicit_pass = Q(first_qc1_result=FirstQc1Result.PASS)
    explicit_reject = Q(first_qc1_result=FirstQc1Result.REJECT)
    fallback_pass = Q(
        first_qc1_result="",
        status__in=REACHED_QC2,
        total_rework_rounds=0,
        rework_round=0,
    )
    fallback_reject = Q(first_qc1_result="") & _reworked_q()
    agg = jobs_qs.aggregate(
        passed=Count("id", filter=explicit_pass | fallback_pass),
        total=Count("id", filter=explicit_pass | explicit_reject | fallback_pass | fallback_reject),
    )
    passed = agg["passed"] or 0
    total = agg["total"] or 0
    return {"passed": passed, "total": total, "value": _pct(passed, total)}


def _severity_breakdown(errors_qs) -> dict[str, int]:
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


def _quality_cuboid_metrics(jobs_qs, errors_qs, *, sample_qs=None) -> dict[str, Any]:
    """CL02 (Defect Error Rate), CL05 (theo mức độ) & CL11 (Quality CL = (Pass + Edge) / Tổng).

    - Khử trùng nhiều lỗi trên cùng (job_id, frame_number, cvat_object_id) — hoặc theo từng
      audit_sample khi tính trên tập mẫu QC2 (dùng snapshot checked_object_count tại lúc chấm).
    - Chỉ tính trên các job/mẫu đã kiểm và đã có object_count > 0; loại bỏ lỗi đã hủy (is_voided=True).
    - verdict='edge' được tính vào (Pass + Edge) của CL11, KHÔNG tính vào Fail của CL02.
    - Chỉ lỗi có cờ tường minh is_missing_object=True mới cộng vào mẫu số N_missing (tránh nhầm lỗi thiếu ID).
    """
    if sample_qs is not None:
        decided_samples = sample_qs.exclude(result=AuditSample.Result.PENDING)
        checked_objects = (
            decided_samples.aggregate(s=Sum(Coalesce("checked_object_count", "job__object_count")))["s"] or 0
        )
        scoped_errors = errors_qs.filter(is_voided=False, audit_sample__in=decided_samples)
        per_sample = True
    else:
        checked_jobs = (
            jobs_qs.filter(
                Q(first_qc1_result__in=[FirstQc1Result.PASS, FirstQc1Result.REJECT])
                | Q(status__in=REACHED_QC2)
                | Q(audit_samples__result__in=[AuditSample.Result.PASS, AuditSample.Result.REJECT])
            )
            .filter(object_count__gt=0)
            .distinct()
        )
        checked_objects = checked_jobs.aggregate(s=Sum("object_count"))["s"] or 0
        scoped_errors = errors_qs.filter(is_voided=False, job__in=checked_jobs)
        per_sample = False

    targets: dict[tuple[object, ...], dict[str, Any]] = {}
    for err in scoped_errors.only(
        "id",
        "job_id",
        "audit_sample_id",
        "category_id",
        "frame_number",
        "cvat_object_id",
        "is_missing_object",
        "location",
        "verdict",
        "severity",
    ):
        scope_id = err.audit_sample_id if per_sample else err.job_id
        is_missing = bool(err.is_missing_object)
        if is_missing:
            if err.frame_number is not None:
                key: tuple[object, ...] = ("missing", scope_id, err.frame_number, err.category_id)
            else:
                key = ("missing_err", scope_id, err.id)
        elif err.frame_number is not None and err.cvat_object_id is not None:
            key = ("obj", scope_id, err.frame_number, err.cvat_object_id)
        elif err.location and err.location.strip():
            key = ("loc", scope_id, err.location.strip().lower())
        else:
            key = ("err", scope_id, err.id)

        entry = targets.get(key)
        rank = SEVERITY_RANK.get(err.severity, 1)
        if entry is None:
            targets[key] = {
                "verdict": err.verdict,
                "is_missing": is_missing,
                "severity": err.severity,
                "severity_rank": rank,
            }
        else:
            if err.verdict == ErrorVerdict.FAIL:
                if entry["verdict"] != ErrorVerdict.FAIL or rank > entry["severity_rank"]:
                    entry["severity"] = err.severity
                    entry["severity_rank"] = rank
                entry["verdict"] = ErrorVerdict.FAIL
            elif entry["verdict"] != ErrorVerdict.FAIL and rank > entry["severity_rank"]:
                entry["severity"] = err.severity
                entry["severity_rank"] = rank

    missing_objects = sum(1 for t in targets.values() if t["is_missing"])
    fail_targets = [t for t in targets.values() if t["verdict"] == ErrorVerdict.FAIL]
    edge_objects = sum(1 for t in targets.values() if t["verdict"] == ErrorVerdict.EDGE)
    fail_objects = len(fail_targets)
    denom = checked_objects + missing_objects

    if checked_objects <= 0 or denom <= 0:
        return {
            "checked_objects": 0,
            "missing_objects": 0,
            "total_objects": 0,
            "fail_objects": 0,
            "edge_objects": 0,
            "defect_error_rate": None,
            "quality_cl": None,
            "defect_rate_by_severity": {
                Severity.MINOR.value: None,
                Severity.MAJOR.value: None,
                Severity.CRITICAL.value: None,
            },
        }

    effective_fail = min(fail_objects, denom)
    defect_rate = round(effective_fail * 100 / denom, 2)
    quality_cl = round(100.0 - defect_rate, 2)

    # CL05: phân bổ theo mức độ nặng nhất (ưu tiên critical -> major -> minor nếu fail_objects > denom để tổng <= 100%)
    remaining_budget = effective_fail
    by_sev: dict[str, float | None] = {}
    for sev in (Severity.CRITICAL.value, Severity.MAJOR.value, Severity.MINOR.value):
        raw_count = sum(1 for t in fail_targets if t["severity"] == sev)
        capped = min(raw_count, remaining_budget)
        remaining_budget -= capped
        by_sev[sev] = round(capped * 100 / denom, 2)
    by_sev = {
        Severity.MINOR.value: by_sev[Severity.MINOR.value],
        Severity.MAJOR.value: by_sev[Severity.MAJOR.value],
        Severity.CRITICAL.value: by_sev[Severity.CRITICAL.value],
    }

    return {
        "checked_objects": checked_objects,
        "missing_objects": missing_objects,
        "total_objects": denom,
        "fail_objects": effective_fail,
        "edge_objects": edge_objects,
        "defect_error_rate": defect_rate,
        "quality_cl": quality_cl,
        "defect_rate_by_severity": by_sev,
    }


def _daily_output_maps(project, user, start_date: date, end_date: date) -> tuple[dict[date, int], dict[date, int]]:
    """Tổng sản lượng theo ngày từ DailyOutputRecord (SL01 first_pass & SL03 rework)."""
    rows = (
        DailyOutputRecord.objects.filter(
            project=project,
            user=user,
            work_date__gte=start_date,
            work_date__lte=end_date,
        )
        .values("work_date", "is_rework")
        .annotate(total=Sum("object_count"))
    )
    first_map: dict[date, int] = {}
    rework_map: dict[date, int] = {}
    for r in rows:
        d = r["work_date"]
        val = int(r["total"] or 0)
        if r["is_rework"]:
            rework_map[d] = rework_map.get(d, 0) + val
        else:
            first_map[d] = first_map.get(d, 0) + val
    return first_map, rework_map


class ProjectOverviewView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/overview/?period=day|week|month"""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request, project_id):
        with timezone.override(_user_timezone(request.user)):
            return self._build(request)

    def _build(self, request):
        project = self.project
        now = timezone.now()
        since = _period_start(request, now=now)
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

        # TD05: tiến độ tích lũy qua từng mốc (Anno nộp, đạt QC1, đạt QC2/duyệt)
        stage_progress = {
            "annotation_passed": _pct(totals["anno_passed"] or 0, total_jobs),
            "qc1_passed": _pct(totals["qc1_passed"] or 0, total_jobs),
            "qc2_approved": _pct(done_jobs, total_jobs),
        }

        # TD08 (sẵn sàng bàn giao cấp batch) & TD09 (đã bàn giao cấp batch) & TD13 (việc chờ quyết định)
        batch_rows = list(
            Batch.objects.filter(dataset__project=project)
            .select_related("dataset")
            .annotate(
                job_count=Count("jobs", distinct=True),
                approved_count=Count("jobs", filter=Q(jobs__status=JobStatus.APPROVED), distinct=True),
                qc1_passed_count=Count("jobs", filter=Q(jobs__status=JobStatus.QC1_PASSED), distinct=True),
                blocking_qc2_count=Count("jobs", filter=Q(jobs__status__in=BLOCKING_QC2_STATUSES), distinct=True),
                open_audits=Count("audits", filter=Q(audits__status=Audit.Status.IN_PROGRESS), distinct=True),
            )
        )
        total_batches = len(batch_rows)
        delivered_batches = sum(1 for b in batch_rows if b.status == DataStatus.DELIVERED)
        ready_batches = sum(
            1
            for b in batch_rows
            if b.status == DataStatus.ACTIVE
            and b.dataset.status == DataStatus.ACTIVE
            and b.job_count > 0
            and b.approved_count == b.job_count
            and b.open_audits == 0
        )
        batches_ready_for_qc2 = sum(
            1
            for b in batch_rows
            if b.status == DataStatus.ACTIVE
            and b.job_count > 0
            and b.qc1_passed_count > 0
            and b.blocking_qc2_count == 0
        )
        audits_ready_to_complete = (
            Audit.objects.filter(project=project, status=Audit.Status.IN_PROGRESS)
            .annotate(
                total_samples=Count("samples"),
                pending_samples=Count("samples", filter=Q(samples__result=AuditSample.Result.PENDING)),
            )
            .filter(total_samples__gt=0, pending_samples=0)
            .count()
        )
        pending_requests = AnnotatorRequest.objects.filter(
            project=project, status=AnnotatorRequest.Status.PENDING_PM
        ).count()
        pending_decisions = {
            "batches_ready_for_qc2": batches_ready_for_qc2,
            "audits_ready_to_complete": audits_ready_to_complete,
            "pending_requests": pending_requests,
            "escalated": totals["escalated"] or 0,
            "total": batches_ready_for_qc2 + audits_ready_to_complete + pending_requests + (totals["escalated"] or 0),
        }

        fpy = _fpy_stats(jobs)
        active_errors = ReviewError.objects.filter(job__project=project, is_voided=False)
        quality_cuboids = _quality_cuboid_metrics(jobs, active_errors)
        errors_by_category = [
            {"category": r["category__name"], "count": r["n"]}
            for r in active_errors.values("category__name").annotate(n=Count("id")).order_by("-n")[:10]
        ]
        errors_by_severity = _severity_breakdown(active_errors)

        # CL09: tỷ lệ kết luận lỗi bị hủy qua error_dispute
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
            project=project, action="job.status", after__status=JobStatus.PENDING_QC1, created_at__gte=since
        ).count()

        # TD11: hợp nhất nhân sự đang giữ việc mở trên cả 3 vai trò (Anno + QC1 + QC2)
        active_user_ids = (
            set(
                jobs.filter(status__in=ACTIVE_ANNOTATOR_STATUSES, annotator__isnull=False).values_list(
                    "annotator_id", flat=True
                )
            )
            | set(
                jobs.filter(
                    status__in=[JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING], qc1_reviewer__isnull=False
                ).values_list("qc1_reviewer_id", flat=True)
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
            assert job.deadline is not None
            alerts.append({
                "level": "warning",
                "type": "overdue",
                "job": job.id,
                "message": f"{job.name} quá hạn từ {timezone.localtime(job.deadline):%d/%m %H:%M}",
            })
        for job in jobs.filter(
            deadline__gte=now, deadline__lte=now + timedelta(hours=24), status__in=OPEN_STATUSES
        ).order_by("deadline")[:10]:
            assert job.deadline is not None
            alerts.append({
                "level": "info",
                "type": "due_soon",
                "job": job.id,
                "message": f"{job.name} đến hạn lúc {timezone.localtime(job.deadline):%d/%m %H:%M}",
            })

        return Response({
            "counts": {
                "datasets": project.datasets.count(),
                "batches": total_batches,
                "ready_batches": ready_batches,
                "delivered_batches": delivered_batches,
                "jobs": total_jobs,
                "remaining_jobs": remaining_jobs,
                "escalated": totals["escalated"],
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
                "quality_cl": _metric(
                    quality_cuboids["quality_cl"],
                    formula="(Cuboid Pass + Cuboid Edge) ÷ (N_checked + N_missing) × 100% (CL11)",
                    checked_objects=quality_cuboids["checked_objects"],
                    missing_objects=quality_cuboids["missing_objects"],
                    edge_objects=quality_cuboids["edge_objects"],
                    fail_objects=quality_cuboids["fail_objects"],
                ),
                "defect_error_rate": _metric(
                    quality_cuboids["defect_error_rate"],
                    formula="Cuboid duy nhất verdict=fail ÷ (N_checked + N_missing) × 100% (CL02)",
                    checked_objects=quality_cuboids["checked_objects"],
                    missing_objects=quality_cuboids["missing_objects"],
                    fail_objects=quality_cuboids["fail_objects"],
                ),
                "defect_rate_by_severity": _metric(
                    quality_cuboids["defect_rate_by_severity"],
                    formula="Cuboid fail theo mức độ nặng nhất ÷ (N_checked + N_missing) × 100% (CL05)",
                ),
                "dispute_overturn_rate": _metric(
                    dispute_overturn,
                    formula="error_dispute resolved ÷ (resolved + rejected) × 100% (CL09)",
                    resolved=dispute_agg["resolved"] or 0,
                    total=dispute_agg["total"] or 0,
                ),
                "estimated_completion": _metric(None, status="pending_definition", formula="Chưa chốt cách ước tính (DB02/DB03)"),
                "submitted_in_period": _metric(submitted, formula="Số lần job chuyển sang Chờ QC1 trong kỳ"),
                "active_members": _metric(
                    active_members,
                    formula="Số người duy nhất đang giữ việc mở trên Anno, QC1 và QC2 (TD11)",
                ),
            },
            "thresholds": {
                "quality_cl": project.quality_cl_threshold,
                "defect_error_rate": project.defect_rate_threshold,
            },
            "alerts": alerts,
        })


class TeamRankingView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/team-ranking/ — so sánh team theo sản lượng thực tế (SL05, KPI10)."""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request, project_id):
        tracked_job_ids = set(
            DailyOutputRecord.objects.filter(project=self.project).values_list("job_id", flat=True).distinct()
        )
        output_by_user: dict[int, dict[str, int]] = {}
        for r in (
            DailyOutputRecord.objects.filter(project=self.project)
            .values("user_id", "is_rework")
            .annotate(total=Sum("object_count"))
        ):
            bucket = output_by_user.setdefault(r["user_id"], {"fp": 0, "rw": 0})
            if r["is_rework"]:
                bucket["rw"] += int(r["total"] or 0)
            else:
                bucket["fp"] += int(r["total"] or 0)

        rows = []
        for team in Team.objects.filter(project=self.project).prefetch_related("members"):
            member_ids = [m.user_id for m in team.members.all()]
            jobs = Job.objects.filter(project=self.project, annotator_id__in=member_ids)
            legacy_done_q = Q(status__in=DONE) & ~Q(pk__in=tracked_job_ids)
            s = jobs.aggregate(
                total=Count("id"),
                done=Count("id", filter=Q(status__in=DONE)),
                legacy_objects=Sum("object_count", filter=legacy_done_q),
                reworked=Count("id", filter=_reworked_q()),
                escalated=Count("id", filter=Q(is_escalated=True)),
            )
            fp_objs = sum(output_by_user.get(uid, {}).get("fp", 0) for uid in member_ids)
            rw_objs = sum(output_by_user.get(uid, {}).get("rw", 0) for uid in member_ids)
            produced = fp_objs + rw_objs
            objects_done = produced + int(s["legacy_objects"] or 0)
            qc2_errors = ReviewError.objects.filter(job__in=jobs, stage=ReviewStage.QC2, is_voided=False).count()
            rows.append({
                "team": {"id": team.id, "name": team.name},
                "members": len(member_ids),
                "jobs": s["total"],
                "done": s["done"],
                "objects_done": objects_done,
                "objects_produced": produced,
                "first_pass_objects": fp_objs,
                "rework_objects": rw_objs,
                "rework_rate": _pct(s["reworked"], s["total"]),
                "escalated": s["escalated"],
                "qc2_errors": qc2_errors,
            })
        rows.sort(
            key=lambda r: (
                -r["objects_done"],
                r["rework_rate"] if r["rework_rate"] is not None else 999.0,
                r["team"]["name"],
            )
        )
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        return Response({"formula": "Sản lượng cuboid thực hiện (giảm dần), rồi tỷ lệ rework (tăng dần)", "rows": rows})


class Qc2SummaryView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/qc2-summary/ — dashboard QC2 (QC2-01). PM xem toàn dự án, QC2 xem của mình."""

    required_capabilities = {"*": [Cap.PERFORM_AUDIT, Cap.VIEW_DASHBOARD]}

    def get(self, request, project_id):
        with timezone.override(_user_timezone(request.user)):
            return self._build(request)

    def _build(self, request):
        project = self.project
        user = request.user
        base_samples = AuditSample.objects.filter(audit__project=project)
        can_project_scope = self.has_cap(Cap.MANAGE_AUDITS) or self.has_cap(Cap.VIEW_DASHBOARD)
        scope = "project" if can_project_scope and request.query_params.get("scope") != "mine" else "mine"

        # Không tính cover hộ:
        # - Hàng chờ đang giữ (pending/overdue/due_soon/assigned): theo auditor được giao.
        # - Sản lượng & lỗi đã kiểm (passed/rejected/audited/kpi/trend/errors): theo đúng reviewed_by.
        if scope == "mine":
            queue_samples = base_samples.filter(auditor=user)
            reviewed_samples = base_samples.filter(reviewed_by=user)
            progress_samples = base_samples.filter(Q(auditor=user) | Q(reviewed_by=user))
        else:
            queue_samples = base_samples
            reviewed_samples = base_samples
            progress_samples = base_samples

        now = timezone.now()
        since = _period_start(request, now=now)
        today = timezone.localdate(now)
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
            audited_in_period=Count("id", filter=Q(reviewed_at__gte=since)),
            audited_today=Count("id", filter=Q(reviewed_at__gte=today_start)),
        )
        stats = {
            "assigned": queue_stats["assigned"],
            "pending": queue_stats["pending"],
            "passed": review_stats["passed"],
            "rejected": review_stats["rejected"],
            "audited_in_period": review_stats["audited_in_period"],
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

        # Chất lượng mẫu kiểm (CL02, CL05, CL11) tính theo từng lượt AuditSample đã có kết quả
        quality_cuboids = _quality_cuboid_metrics(
            Job.objects.none(),
            errors,
            sample_qs=reviewed_samples,
        )

        # Bảng KPI: kỳ này so với kỳ trước (KPI08/KPI09)
        length = now - since
        current_win = self._window(reviewed_samples, errors, since, now)
        prev_win = self._window(reviewed_samples, errors, since - length, since)
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

        # Xu hướng theo ngày theo đúng múi giờ người dùng (CS08)
        trend_days = 30 if length.days >= 30 else 7
        start = today - timedelta(days=trend_days - 1)
        start_dt = _local_day_start(start)
        tz = timezone.get_current_timezone()
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
            "error_percent_in_job": _metric(
                quality_cuboids["defect_error_rate"],
                formula="Cuboid duy nhất verdict=fail ÷ (N_checked + N_missing) × 100% (CL02)",
                checked_objects=quality_cuboids["checked_objects"],
                missing_objects=quality_cuboids["missing_objects"],
                fail_objects=quality_cuboids["fail_objects"],
            ),
            "quality_cl": _metric(
                quality_cuboids["quality_cl"],
                formula="(Cuboid Pass + Cuboid Edge) ÷ (N_checked + N_missing) × 100% (CL11)",
                checked_objects=quality_cuboids["checked_objects"],
                missing_objects=quality_cuboids["missing_objects"],
                edge_objects=quality_cuboids["edge_objects"],
                fail_objects=quality_cuboids["fail_objects"],
            ),
            "defect_rate_by_severity": quality_cuboids["defect_rate_by_severity"],
            "audit_speed": {
                "value": None,
                "status": "pending_definition",
                "formula": "Chưa có dữ liệu thời gian bắt đầu / kết thúc audit từng job (NS04).",
            },
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
    def _window(samples, errors, start, end):
        stats = samples.filter(reviewed_at__gte=start, reviewed_at__lt=end).aggregate(
            audited=Count("id"),
            passed=Count("id", filter=Q(result=AuditSample.Result.PASS)),
            rejected=Count("id", filter=Q(result=AuditSample.Result.REJECT)),
        )
        stats["pass_rate"] = _pct(stats["passed"], stats["audited"])
        stats["errors"] = errors.filter(created_at__gte=start, created_at__lt=end).count()
        return stats


class MemberPerformanceView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/member-performance/ — hiệu suất từng annotator theo đúng actor (SL04)."""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request, project_id):
        tracked_job_ids = set(
            DailyOutputRecord.objects.filter(project=self.project).values_list("job_id", flat=True).distinct()
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
            DailyOutputRecord.objects.filter(project=self.project)
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

    def get(self, request, project_id):
        project = self.project
        user = request.user
        with timezone.override(_user_timezone(user)):
            return self._build(request, project, user)

    def _build(self, request, project, user):
        now = timezone.now()
        today = timezone.localdate(now)
        since = _period_start(request, now=now)

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
        last_sync = (
            Batch.objects.filter(dataset__project=project, last_synced_at__isnull=False)
            .order_by("-last_synced_at")
            .values_list("last_synced_at", flat=True)
            .first()
        )

        # TD01: tính trên TOÀN BỘ job đang giữ (không cắt top 10), hiển thị 10 job ưu tiên tiếp theo (DB06)
        active_base_qs = jobs.filter(status__in=ACTIVE_ANNOTATOR_STATUSES)
        active_agg = active_base_qs.aggregate(
            active_count=Count("id"),
            max_rw=Max("rework_round", filter=Q(status=JobStatus.REWORK)),
        )
        active_jobs_count = active_agg["active_count"] or 0
        active_object_frames = sum(
            (t or o) for t, o in active_base_qs.values_list("target_object_count", "object_count")
        )
        max_rework_round_active = active_agg["max_rw"] or 0

        active_qs = order_by_db06_priority(
            active_base_qs.select_related("batch__dataset", "annotator", "qc1_reviewer", "project").annotate(
                _open_error_count=Count("review_errors", filter=Q(review_errors__is_voided=False), distinct=True)
            ),
            now=now,
        )
        active_jobs = list(active_qs[:10])

        # RW04: tổng lỗi chưa hủy thuộc vòng hiện tại trên tất cả job đang ở trạng thái REWORK
        rework_job_ids = list(jobs.filter(status=JobStatus.REWORK).values_list("id", flat=True))
        pending_rework_errors = 0
        if rework_job_ids:
            latest_rounds = {
                r["job_id"]: r["max_r"]
                for r in ReviewError.objects.filter(job_id__in=rework_job_ids, is_voided=False)
                .values("job_id")
                .annotate(max_r=Max("rework_round"))
            }
            if latest_rounds:
                round_q = Q()
                for jid, mr in latest_rounds.items():
                    round_q |= Q(job_id=jid, rework_round=mr)
                pending_rework_errors = ReviewError.objects.filter(is_voided=False).filter(round_q).count()

        rework_job = (
            next((j for j in active_jobs if j.status == JobStatus.REWORK), None)
            or active_qs.filter(status=JobStatus.REWORK).first()
            or next((j for j in active_jobs if j.rework_round > 0), None)
        )
        rework_focus = None
        if rework_job:
            err_qs = rework_job.review_errors.filter(is_voided=False).select_related("category", "reported_by")
            latest_r = err_qs.aggregate(m=Max("rework_round"))["m"]
            if latest_r is not None:
                err_qs = err_qs.filter(rework_round=latest_r)
            err_qs = err_qs.order_by("-created_at")
            err_all = list(err_qs)
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

        # Kết quả theo ngày 7 ngày gần nhất từ DailyOutputRecord (SL01 · SL03 · SL06 · CS02/CS03)
        start_day = today - timedelta(days=6)
        daily_first, daily_rework = _daily_output_maps(project, user, start_day, today)

        daily_target = project.kpi_annotation_target or 0
        daily_results = []
        for offset in range(6, -1, -1):
            d = today - timedelta(days=offset)
            fp = daily_first.get(d, 0)
            rw = daily_rework.get(d, 0)
            total_d = fp + rw
            daily_results.append({
                "date": d.isoformat(),
                "label": d.strftime("%d/%m"),
                "first_pass_objects": fp,
                "rework_objects": rw,
                "total_objects": total_d,
                "target_objects": daily_target,
                "is_off_day": total_d == 0 and d.weekday() == 6,
            })

        # DH06: tỷ lệ nộp đúng hạn trên lịch sử các lượt nộp (ưu tiên deadline snapshot lúc nộp, fallback job.deadline)
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
            dl: datetime | None = None
            raw_dl = (ev.after or {}).get("deadline")
            if isinstance(raw_dl, str) and raw_dl:
                try:
                    dl = parse_rfc3339_datetime(raw_dl)
                except ValueError:
                    dl = None
            if dl is None and ev.job is not None:
                dl = ev.job.deadline
            if dl is not None:
                dated_events.append((ev.created_at, dl))

        if dated_events:
            submitted_total = len(dated_events)
            on_time_count = sum(1 for created_at, dl in dated_events if created_at <= dl)
        else:
            submitted_jobs = list(
                jobs.filter(
                    status__in=SUBMITTED_OR_DONE_STATUSES,
                    deadline__isnull=False,
                ).only("deadline", "submitted_at", "updated_at")
            )
            submitted_total = len(submitted_jobs)
            on_time_count = sum(
                1 for j in submitted_jobs if j.deadline is not None and (j.submitted_at or j.updated_at) <= j.deadline
            )

        # Sản lượng / chỉ tiêu hôm nay (SL06 · KPI02 · KPI03 · KPI04)
        actual_objects = daily_first.get(today, 0) + daily_rework.get(today, 0)
        kpi_prog = _kpi_progress(actual_objects, project.kpi_annotation_target)

        req_qs = AnnotatorRequest.objects.filter(project=project, created_by=user).select_related(
            "job__batch", "review_error__category", "created_by", "handler"
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

    def get(self, request, project_id):
        project = self.project
        user = request.user
        with timezone.override(_user_timezone(user)):
            return self._build(request, project, user)

    def _build(self, request, project, user):
        now = timezone.now()
        today = timezone.localdate(now)
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

        # 1. Sản lượng theo ngày từ DailyOutputRecord (tính cả trước và sau QC)
        day_fp, day_rw = _daily_output_maps(project, user, query_start_date, today)

        # 2. Giờ làm phiên theo từng loại (NS01, NS03): tách riêng giờ lần đầu và giờ rework, lọc theo đúng actor
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

        day_fp_intervals: dict[date, list[tuple[datetime, datetime]]] = {}
        day_rw_intervals: dict[date, list[tuple[datetime, datetime]]] = {}
        for log in logs:
            d = timezone.localdate(log.created_at)
            after = log.after or {}
            is_rw = after.get("event") == "annotator.resubmit" or (after.get("rework_round") or 0) > 0

            session_start = None
            starts = start_times_by_job.get(log.job_id) if log.job_id else None
            if starts:
                idx = bisect_right(starts, log.created_at) - 1
                if idx >= 0:
                    session_start = starts[idx]
            if session_start is None and not is_rw and log.job and log.job.started_at and log.job.annotator_id == user.id:
                session_start = log.job.started_at

            if session_start and log.created_at > session_start:
                clamped_end = max(
                    session_start + timedelta(minutes=15),
                    min(log.created_at, session_start + timedelta(hours=10)),
                )
                interval = (session_start, clamped_end)
                if is_rw:
                    day_rw_intervals.setdefault(d, []).append(interval)
                else:
                    day_fp_intervals.setdefault(d, []).append(interval)

        daily_productivity = []
        total_objects = 0
        measured_objects = 0
        total_hours = 0.0
        active_days = 0
        for i in range(days):
            d = start_date + timedelta(days=i)
            fp = day_fp.get(d, 0)
            rw = day_rw.get(d, 0)
            day_total = fp + rw
            is_off = day_total == 0 and d.weekday() == 6
            fp_iv = day_fp_intervals.get(d, [])
            rw_iv = day_rw_intervals.get(d, [])
            fp_hrs = _merged_hours(fp_iv)
            rw_hrs = _merged_hours(rw_iv)
            # Hợp nhất cả 2 nhánh (không bịa 7.5h, không cộng đúp khi WIP >= 2 chạy song song)
            hrs = _merged_hours(fp_iv + rw_iv)
            if day_total > 0:
                active_days += 1
                total_objects += day_total
            if hrs > 0:
                total_hours += hrs
                if fp_hrs > 0:
                    measured_objects += fp
                if rw_hrs > 0:
                    measured_objects += rw
            daily_productivity.append({
                "date": d.isoformat(),
                "label": d.strftime("%d/%m"),
                "first_pass_objects": fp,
                "rework_objects": rw,
                "first_pass_per_hour": round(fp / fp_hrs, 1) if fp_hrs > 0 else 0,
                "rework_per_hour": round(rw / rw_hrs, 1) if rw_hrs > 0 else 0,
                "hours": round(hrs, 1),
                "is_off_day": is_off,
            })

        objects_per_hour = round(measured_objects / total_hours) if total_hours > 0 else 0

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
                actual = day_fp.get(d, 0) + day_rw.get(d, 0)
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

        # 4. Xếp hạng sản lượng cá nhân (KPI10) — từ DailyOutputRecord cùng kỳ (hai cửa sổ bằng nhau)
        annotator_ids = list(
            RoleAssignment.objects.filter(project=project, role=Role.ANNOTATOR)
            .values_list("user_id", flat=True)
            .distinct()
        )
        if user.id not in annotator_ids:
            annotator_ids.append(user.id)

        def _rank_for_window(w_start: date, w_end_inclusive: date) -> int:
            scores = {uid: 0 for uid in annotator_ids}
            for row in (
                DailyOutputRecord.objects.filter(
                    project=project,
                    user_id__in=annotator_ids,
                    work_date__gte=w_start,
                    work_date__lte=w_end_inclusive,
                )
                .values("user_id")
                .annotate(total=Sum("object_count"))
            ):
                scores[row["user_id"]] = int(row["total"] or 0)
            my_score = scores.get(user.id, 0)
            return 1 + sum(1 for v in scores.values() if v > my_score)

        current_rank = _rank_for_window(start_date, today)
        previous_rank = _rank_for_window(prev_start_date, start_date - timedelta(days=1))

        return Response({
            "range": range_key,
            "week_label": f"Tuần {iso_week}",
            "iso_year": iso_year,
            "avg_productivity": {
                "objects_per_hour": objects_per_hour,
                "total_objects": total_objects,
                "total_hours": round(total_hours, 1),
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

    def get(self, request, project_id):
        project = self.project
        user = request.user
        with timezone.override(_user_timezone(user)):
            return self._build(request, project, user)

    def _build(self, request, project, user):
        scope = "project" if self.has_cap(Cap.VIEW_DASHBOARD) and request.query_params.get("scope") != "mine" else "mine"

        jobs = Job.objects.filter(project=project)
        logs = ActivityLog.objects.filter(project=project, action__in=["qc1.pass", "qc1.reject"])
        qc1_errors = ReviewError.objects.filter(job__project=project, stage=ReviewStage.QC1, is_voided=False)

        # CL06 & CL07: quy lỗi QC2 bỏ sót về ĐÚNG người QC1 duyệt pass gần nhất trước đợt audit (không đổ lỗi kép)
        qc1_pass_history: dict[int, tuple[list[datetime], list[int]]] = {}
        for jid, passed_at, actor_id in (
            ActivityLog.objects.filter(
                project=project, action="qc1.pass", job_id__isnull=False, actor_id__isnull=False
            )
            .order_by("created_at", "id")
            .values_list("job_id", "created_at", "actor_id")
        ):
            if jid is not None and actor_id is not None:
                times, actors = qc1_pass_history.setdefault(jid, ([], []))
                times.append(passed_at)
                actors.append(actor_id)

        def _responsible_qc1_at(job_obj: Job, ref_time: datetime) -> int | None:
            hist = qc1_pass_history.get(job_obj.pk)
            if hist:
                times, actors = hist
                idx = bisect_right(times, ref_time) - 1
                if idx >= 0:
                    return actors[idx]
                return None
            # Fallback cho fixture đặt thẳng status REACHED_QC2 mà không đi qua qc1_pass
            if job_obj.status in REACHED_QC2:
                return job_obj.qc1_reviewer_id
            return None

        if scope == "mine":
            jobs = jobs.filter(qc1_reviewer=user)
            logs = logs.filter(actor=user)
            qc1_errors = qc1_errors.filter(reported_by=user)

        decided_samples = list(
            AuditSample.objects.filter(
                audit__project=project,
                result__in=[AuditSample.Result.PASS, AuditSample.Result.REJECT],
            ).select_related("audit", "job")
        )
        audited_job_ids: set[int] = set()
        for sample in decided_samples:
            resp_uid = _responsible_qc1_at(sample.job, sample.audit.created_at)
            if resp_uid is None:
                continue
            if scope == "project" or resp_uid == user.id:
                audited_job_ids.add(sample.job_id)

        qc2_errors_all = list(
            ReviewError.objects.filter(
                job__project=project,
                stage=ReviewStage.QC2,
                is_voided=False,
            ).select_related("job", "audit_sample__audit")
        )
        matched_escape_errors: list[ReviewError] = []
        for err in qc2_errors_all:
            ref_time = err.audit_sample.audit.created_at if err.audit_sample is not None else err.created_at
            resp_uid = _responsible_qc1_at(err.job, ref_time)
            if resp_uid is None:
                continue
            if scope == "project" or resp_uid == user.id:
                matched_escape_errors.append(err)

        audited_jobs_count = len(audited_job_ids)
        escaped_jobs_count = len({err.job_id for err in matched_escape_errors if err.job_id in audited_job_ids})
        qc1_escape_job_rate = _pct(escaped_jobs_count, audited_jobs_count)
        qc2_escape_error_count = len(matched_escape_errors)

        now = timezone.now()
        since = _period_start(request, now=now)
        today = timezone.localdate(now)
        today_start = _local_day_start(today)
        length = now - since

        cutoff = now + timedelta(hours=24)
        qc1_open = Q(status__in=[JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING])
        queue_stats = jobs.aggregate(
            assigned=Count("id"),
            pending=Count("id", filter=Q(status=JobStatus.PENDING_QC1)),
            reviewing=Count("id", filter=Q(status=JobStatus.QC1_REVIEWING)),
            qc1_passed=Count("id", filter=Q(status=JobStatus.QC1_PASSED)),
            overdue=Count("id", filter=qc1_open & Q(deadline__lt=now)),
            due_soon=Count("id", filter=qc1_open & Q(deadline__gte=now, deadline__lte=cutoff)),
        )
        decision_stats = logs.aggregate(
            passed=Count("id", filter=Q(action="qc1.pass")),
            rejected=Count("id", filter=Q(action="qc1.reject")),
            reviewed_in_period=Count("id", filter=Q(created_at__gte=since)),
            reviewed_today=Count("id", filter=Q(created_at__gte=today_start)),
        )
        stats = {
            **queue_stats,
            "passed": decision_stats["passed"],
            "rejected": decision_stats["rejected"],
            "reviewed_in_period": decision_stats["reviewed_in_period"],
        }

        current_win = self._window(logs, qc1_errors, since, now)
        prev_win = self._window(logs, qc1_errors, since - length, since)
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

        trend_days = 30 if length.days >= 30 else 7
        start = today - timedelta(days=trend_days - 1)
        start_dt = _local_day_start(start)
        tz = timezone.get_current_timezone()
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
            "escaped_jobs_count": escaped_jobs_count,
            "audited_jobs_count": audited_jobs_count,
            "errors_by_category": [{"category": r["category__name"], "count": r["n"]} for r in by_category],
            "errors_by_severity": by_severity,
            "kpi_target": project.kpi_qc1_target,
        })

    @staticmethod
    def _window(logs, errors, start, end):
        stats = logs.filter(created_at__gte=start, created_at__lt=end).aggregate(
            reviewed=Count("id"),
            passed=Count("id", filter=Q(action="qc1.pass")),
            rejected=Count("id", filter=Q(action="qc1.reject")),
        )
        stats["pass_rate"] = _pct(stats["passed"], stats["reviewed"])
        stats["errors"] = errors.filter(created_at__gte=start, created_at__lt=end).count()
        return stats
