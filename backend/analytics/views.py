"""Dashboard & KPI. Không có model riêng: tổng hợp từ dữ liệu của projects, jobs, quality, teams.

QUY ƯỚC: chỉ số nào chưa chốt công thức thì trả về value=None kèm status="pending_definition".
Chỉ số "tạm tính" (provisional) có ghi công thức đang dùng để nhóm kiểm tra.
"""

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from jobs.models import OPEN_STATUSES, STAGE_STATUSES, Job, JobStatus
from projects.models import ActivityLog
from quality.models import Audit, AuditSample, ReviewError, ReviewStage
from teams.models import Team

PERIODS = {"day": 1, "week": 7, "month": 30}
DONE = STAGE_STATUSES["done"]
REACHED_QC2 = [JobStatus.PENDING_QC2, *DONE]


def _metric(value, *, status="ok", formula=""):
    return {"value": value, "status": status, "formula": formula}


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def _period_start(request):
    days = PERIODS.get(request.query_params.get("period", "week"), 7)
    return timezone.now() - timedelta(days=days)


class ProjectOverviewView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/overview/?period=day|week|month"""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request, project_id):
        project = self.project
        now = timezone.now()
        since = _period_start(request)
        jobs = Job.objects.filter(project=project)

        totals = jobs.aggregate(
            total=Count("id"), objects=Sum("object_count"), frames=Sum("frame_count"),
            done=Count("id", filter=Q(status__in=DONE)),
            reached_qc2=Count("id", filter=Q(status__in=REACHED_QC2)),
            first_pass=Count("id", filter=Q(status__in=REACHED_QC2, rework_round=0)),
            reworked=Count("id", filter=Q(rework_round__gt=0)),
            escalated=Count("id", filter=Q(is_escalated=True)),
            overdue=Count("id", filter=Q(deadline__lt=now, status__in=OPEN_STATUSES)),
        )
        by_status = dict(jobs.values_list("status").annotate(n=Count("id")))
        by_stage = {stage: sum(by_status.get(s, 0) for s in statuses) for stage, statuses in STAGE_STATUSES.items()}

        samples = AuditSample.objects.filter(audit__project=project).exclude(result=AuditSample.Result.PENDING)
        qc2 = samples.aggregate(decided=Count("id"), passed=Count("id", filter=Q(result=AuditSample.Result.PASS)))

        submitted = ActivityLog.objects.filter(
            project=project, action="job.status", after__status=JobStatus.PENDING_QC1, created_at__gte=since
        ).count()
        active_members = (
            jobs.filter(status__in=OPEN_STATUSES, annotator__isnull=False).values("annotator").distinct().count()
        )

        alerts = []
        for job in jobs.filter(is_escalated=True).select_related("batch")[:10]:
            alerts.append({"level": "error", "type": "escalated", "job": job.id,
                           "message": f"{job.name} vượt số vòng rework ({job.rework_round})"})
        for job in jobs.filter(deadline__lt=now, status__in=OPEN_STATUSES).order_by("deadline")[:10]:
            alerts.append({"level": "warning", "type": "overdue", "job": job.id,
                           "message": f"{job.name} quá hạn từ {timezone.localtime(job.deadline):%d/%m %H:%M}"})
        for job in jobs.filter(deadline__gte=now, deadline__lte=now + timedelta(hours=24),
                               status__in=OPEN_STATUSES).order_by("deadline")[:10]:
            alerts.append({"level": "info", "type": "due_soon", "job": job.id,
                           "message": f"{job.name} đến hạn lúc {timezone.localtime(job.deadline):%d/%m %H:%M}"})

        return Response({
            "counts": {
                "datasets": project.datasets.count(),
                "batches": project.batches.count(),
                "jobs": totals["total"],
                "escalated": totals["escalated"],
                "overdue": totals["overdue"],
            },
            "by_status": by_status,
            "by_stage": by_stage,
            "metrics": {
                "total_objects": _metric(totals["objects"] or 0, formula="Tổng object_count đồng bộ từ CVAT"),
                "total_frames": _metric(totals["frames"] or 0),
                "progress": _metric(_pct(totals["done"], totals["total"]), status="provisional",
                                    formula="Job Đã duyệt/Đã bàn giao ÷ tổng job"),
                "delivery_readiness": _metric(_pct(by_status.get(JobStatus.APPROVED, 0) + by_status.get(JobStatus.DELIVERED, 0), totals["total"]),
                                              status="provisional", formula="Job Đã duyệt + Đã bàn giao ÷ tổng job"),
                "rework_rate": _metric(_pct(totals["reworked"], totals["total"]), status="provisional",
                                       formula="Job từng bị rework ÷ tổng job"),
                "first_pass_yield": _metric(_pct(totals["first_pass"], totals["reached_qc2"]), status="provisional",
                                            formula="Job tới QC2 mà chưa rework lần nào ÷ job đã tới QC2"),
                "qc2_pass_rate": _metric(_pct(qc2["passed"], qc2["decided"]), status="provisional",
                                         formula="Mẫu QC2 Pass ÷ mẫu đã audit"),
                "quality_cl": _metric(None, status="pending_definition",
                                      formula="(Object Pass + Object Edge) ÷ Object đã check — chưa chốt cách phân loại"),
                "defect_error_rate": _metric(None, status="pending_definition", formula="Chưa chốt"),
                "estimated_completion": _metric(None, status="pending_definition", formula="Chưa chốt cách ước tính"),
                "submitted_in_period": _metric(submitted, formula="Số lần job chuyển sang Chờ QC1 trong kỳ"),
                "active_members": _metric(active_members, formula="Người đang giữ ít nhất 1 job chưa xong"),
            },
            "thresholds": {
                "quality_cl": project.quality_cl_threshold, "defect_error_rate": project.defect_rate_threshold,
            },
            "alerts": alerts,
        })


class TeamRankingView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/team-ranking/ — so sánh team (KPI tạm tính)."""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request, project_id):
        rows = []
        for team in Team.objects.filter(project=self.project).prefetch_related("members"):
            member_ids = [m.user_id for m in team.members.all()]
            jobs = Job.objects.filter(project=self.project, annotator_id__in=member_ids)
            s = jobs.aggregate(
                total=Count("id"), done=Count("id", filter=Q(status__in=DONE)),
                objects=Sum("object_count", filter=Q(status__in=DONE)),
                reworked=Count("id", filter=Q(rework_round__gt=0)),
                escalated=Count("id", filter=Q(is_escalated=True)),
            )
            qc2_errors = ReviewError.objects.filter(job__in=jobs, stage=ReviewStage.QC2).count()
            rows.append({
                "team": {"id": team.id, "name": team.name},
                "members": len(member_ids),
                "jobs": s["total"], "done": s["done"], "objects_done": s["objects"] or 0,
                "rework_rate": _pct(s["reworked"], s["total"]),
                "escalated": s["escalated"], "qc2_errors": qc2_errors,
            })
        # Xếp hạng tạm: nhiều object hoàn thành hơn trước, rework thấp hơn trước.
        rows.sort(key=lambda r: (-r["objects_done"], r["rework_rate"] or 0))
        for rank, row in enumerate(rows, 1):
            row["rank"] = rank
        return Response({"formula": "Tạm tính: object đã xong (giảm dần), rồi tỉ lệ rework (tăng dần)", "rows": rows})


class Qc2SummaryView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/qc2-summary/ — dashboard QC2 (QC2-01). PM xem toàn dự án, QC2 xem của mình."""

    required_capabilities = {"*": Cap.PERFORM_AUDIT}

    def get(self, request, project_id):
        samples = AuditSample.objects.filter(audit__project=self.project)
        scope = "project" if self.has_cap(Cap.MANAGE_AUDITS) and request.query_params.get("scope") != "mine" else "mine"
        if scope == "mine":
            samples = samples.filter(Q(auditor=request.user) | Q(reviewed_by=request.user))
        since = _period_start(request)
        stats = samples.aggregate(
            assigned=Count("id"),
            pending=Count("id", filter=Q(result=AuditSample.Result.PENDING, audit__status=Audit.Status.IN_PROGRESS)),
            passed=Count("id", filter=Q(result=AuditSample.Result.PASS)),
            rejected=Count("id", filter=Q(result=AuditSample.Result.REJECT)),
            audited_in_period=Count("id", filter=Q(reviewed_at__gte=since)),
        )
        errors = ReviewError.objects.filter(audit_sample__in=samples)
        by_category = list(errors.values("category__name").annotate(n=Count("id")).order_by("-n")[:10])
        by_batch = list(
            samples.values("audit__batch__name").annotate(
                total=Count("id"), done=Count("id", filter=~Q(result=AuditSample.Result.PENDING))
            ).order_by("audit__batch__name")
        )
        reworked_after_audit = samples.filter(result=AuditSample.Result.REJECT).values("job").distinct().count()

        # Bảng KPI: kỳ này so với kỳ trước (cùng độ dài), tính theo thời điểm audit.
        now = timezone.now()
        length = now - since
        kpi = {"current": self._window(samples, errors, since, now),
               "previous": self._window(samples, errors, since - length, since)}

        # Xu hướng theo ngày: số job bị reject (trả rework) và số lỗi ghi nhận.
        trend_days = 30 if length.days >= 30 else 7
        start = (now - timedelta(days=trend_days - 1)).date()
        tz = timezone.get_current_timezone()
        daily = {
            r["day"]: r for r in samples.filter(reviewed_at__date__gte=start)
            .annotate(day=TruncDate("reviewed_at", tzinfo=tz)).values("day")
            .annotate(audited=Count("id"), rejected=Count("id", filter=Q(result=AuditSample.Result.REJECT)))
        }
        daily_errors = dict(
            errors.filter(created_at__date__gte=start).annotate(day=TruncDate("created_at", tzinfo=tz))
            .values("day").annotate(n=Count("id")).values_list("day", "n")
        )
        trend = []
        for i in range(trend_days):
            day = start + timedelta(days=i)
            row = daily.get(day, {})
            trend.append({"date": day.isoformat(), "audited": row.get("audited", 0),
                          "rejected": row.get("rejected", 0), "errors": daily_errors.get(day, 0)})

        return Response({
            "kpi": kpi,
            "trend": trend,
            # Chưa có công thức / dữ liệu → trả rõ trạng thái để giao diện không bịa số.
            "error_percent_in_job": {"value": None, "status": "pending_definition",
                                     "formula": "Chưa chốt: % lỗi tính trên object, frame hay job?"},
            "audit_speed": {"value": None, "status": "pending_definition",
                            "formula": "Chưa có dữ liệu thời gian bắt đầu / kết thúc audit từng job."},
            "scope": scope,
            "stats": stats,
            "pass_rate": _pct(stats["passed"], stats["passed"] + stats["rejected"]),
            "qc1_missed_errors": errors.count(),  # mọi lỗi QC2 tìm thấy đều là lỗi QC1 đã bỏ sót
            "reworked_after_audit": reworked_after_audit,
            "errors_by_category": [{"category": r["category__name"], "count": r["n"]} for r in by_category],
            "progress_by_batch": [{"batch": r["audit__batch__name"], "total": r["total"], "done": r["done"]} for r in by_batch],
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
    """GET /api/projects/{id}/member-performance/ — hiệu suất từng annotator (tạm tính)."""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request, project_id):
        rows = (
            Job.objects.filter(project=self.project, annotator__isnull=False)
            .values("annotator")
            .annotate(
                total=Count("id"), done=Count("id", filter=Q(status__in=DONE)),
                objects_done=Sum("object_count", filter=Q(status__in=DONE)),
                reworked=Count("id", filter=Q(rework_round__gt=0)),
            )
        )
        users ={u.id: u for u in User.objects.filter(pk__in=[r["annotator"] for r in rows])}
        return Response([
            {
                "user": UserBriefSerializer(users[r["annotator"]]).data,
                "jobs": r["total"], "done": r["done"], "objects_done": r["objects_done"] or 0,
                "rework_rate": _pct(r["reworked"], r["total"]),
            }
            for r in sorted(rows, key=lambda r: -(r["objects_done"] or 0))
        ])
