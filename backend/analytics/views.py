"""Dashboard & KPI. Không có model riêng: tổng hợp từ dữ liệu của projects, jobs, quality, teams.

QUY ƯỚC: chỉ số nào chưa chốt công thức thì trả về value=None kèm status="pending_definition".
Chỉ số "tạm tính" (provisional) có ghi công thức đang dùng để nhóm kiểm tra.
"""

from bisect import bisect_right
from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.datetime_utils import app_timezone, format_rfc3339_utc
from accounts.models import Role, RoleAssignment, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, OPEN_STATUSES, STAGE_STATUSES, AnnotatorRequest, Job, JobStatus
from jobs.serializers import AnnotatorRequestSerializer, JobSerializer, ReviewErrorBriefSerializer
from jobs.views import order_by_db06_priority
from projects.models import ActivityLog, Batch
from quality.models import Audit, AuditSample, ReviewError, ReviewStage
from teams.models import Team, TeamMember

PERIODS = {"day": 1, "week": 7, "month": 30}
DONE = STAGE_STATUSES["done"]
REACHED_QC2 = [JobStatus.QC1_PASSED, JobStatus.PENDING_QC2, *DONE]


def _metric(value, *, status="ok", formula=""):
    return {"value": value, "status": status, "formula": formula}


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def _period_start(request):
    days = PERIODS.get(request.query_params.get("period", "week"), 7)
    return timezone.now() - timedelta(days=days)


def _user_timezone(user=None):
    return app_timezone()


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
                           "message": f"{job.name} quá hạn từ {timezone.localtime(job.deadline, app_timezone()):%d/%m %H:%M}"})
        for job in jobs.filter(deadline__gte=now, deadline__lte=now + timedelta(hours=24),
                               status__in=OPEN_STATUSES).order_by("deadline")[:10]:
            alerts.append({"level": "info", "type": "due_soon", "job": job.id,
                           "message": f"{job.name} đến hạn lúc {timezone.localtime(job.deadline, app_timezone()):%d/%m %H:%M}"})

        return Response({
            "counts": {
                "datasets": project.datasets.count(),
                "batches": project.datasets.aggregate(n=Count("batches"))["n"],
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

    required_capabilities = {"*": [Cap.PERFORM_AUDIT, Cap.VIEW_DASHBOARD]}

    def get(self, request, project_id):
        samples = AuditSample.objects.filter(audit__project=self.project)
        can_project_scope = self.has_cap(Cap.MANAGE_AUDITS) or self.has_cap(Cap.VIEW_DASHBOARD)
        scope = "project" if can_project_scope and request.query_params.get("scope") != "mine" else "mine"
        if scope == "mine":
            samples = samples.filter(Q(auditor=request.user) | Q(reviewed_by=request.user))
        since = _period_start(request)
        now = timezone.now()
        cutoff = now + timedelta(hours=24)
        pending_filter = Q(result=AuditSample.Result.PENDING, audit__status=Audit.Status.IN_PROGRESS)
        stats = samples.aggregate(
            assigned=Count("id"),
            pending=Count("id", filter=pending_filter),
            passed=Count("id", filter=Q(result=AuditSample.Result.PASS)),
            rejected=Count("id", filter=Q(result=AuditSample.Result.REJECT)),
            audited_in_period=Count("id", filter=Q(reviewed_at__gte=since)),
            overdue=Count("id", filter=pending_filter & Q(job__deadline__lt=now)),
            due_soon=Count("id", filter=pending_filter & Q(job__deadline__gte=now, job__deadline__lte=cutoff)),
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
        since = _period_start(request)

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
            reached_qc2=Count("id", filter=Q(status__in=REACHED_QC2)),
            first_pass=Count("id", filter=Q(status__in=REACHED_QC2, rework_round=0)),
            reworked=Count("id", filter=Q(rework_round__gt=0)),
            overdue=Count("id", filter=Q(deadline__lt=now, status__in=OPEN_STATUSES)),
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

        submitted_in_period = ActivityLog.objects.filter(
            project=project,
            actor=user,
            action="job.status",
            after__status=JobStatus.PENDING_QC1,
            created_at__gte=since,
        ).count()

        top_errors = list(
            ReviewError.objects.filter(job__project=project, job__annotator=user)
            .values("category__name")
            .annotate(n=Count("id"))
            .order_by("-n")[:10]
        )

        due_soon = (
            jobs.filter(
                status__in=ACTIVE_ANNOTATOR_STATUSES,
                deadline__lte=now + timedelta(hours=24),
            )
            .select_related("batch")
            .order_by("deadline", "id")[:10]
        )

        # --- Dữ liệu mở rộng theo thiết kế Tổng quan cá nhân ---
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

        # Công việc tiếp theo (sắp xếp DB06: quá hạn → sắp hạn → rework → còn lại)
        active_qs = order_by_db06_priority(
            jobs.filter(status__in=ACTIVE_ANNOTATOR_STATUSES)
            .select_related("batch__dataset", "annotator", "qc1_reviewer", "project")
            .annotate(_open_error_count=Count("review_errors", distinct=True)),
            now=now,
        )
        active_jobs = list(active_qs[:10])
        active_jobs_count = jobs.filter(status__in=ACTIVE_ANNOTATOR_STATUSES).count()
        active_object_frames = sum(
            (j.target_object_count or j.object_count) for j in active_jobs
        )
        max_rework_round_active = max((j.rework_round for j in active_jobs if j.status == JobStatus.REWORK), default=0)

        # Việc cần sửa nổi bật (CL04 · RW01 · RW04 · L8)
        rework_job = next((j for j in active_jobs if j.status == JobStatus.REWORK), None) or next(
            (j for j in active_jobs if j.rework_round > 0), None
        )
        rework_focus = None
        if rework_job:
            err_qs = rework_job.review_errors.select_related("category", "reported_by").order_by("-created_at")
            err_list = list(err_qs[:5])
            total_errs = err_qs.count()
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
                "pending_object_frames": total_errs,
                "errors": ReviewErrorBriefSerializer(err_list, many=True).data,
            }

        # Kết quả theo ngày 7 ngày gần nhất (SL01 · SL03 · KPI01 · CS03)
        start_7d = timezone.make_aware(
            timezone.datetime.combine(today - timedelta(days=6), timezone.datetime.min.time())
        )
        sub_logs = (
            ActivityLog.objects.filter(
                project=project,
                actor=user,
                action="job.status",
                after__status=JobStatus.PENDING_QC1,
                created_at__gte=start_7d,
            )
            .select_related("job")
            .order_by("created_at")
        )
        daily_first = {}
        daily_rework = {}
        for log in sub_logs:
            d = timezone.localdate(log.created_at)
            after = log.after or {}
            objs = after.get("object_count")
            if objs is None:
                objs = log.job.object_count if log.job else 0
            is_rw = after.get("event") == "annotator.resubmit" or (after.get("rework_round") or 0) > 0
            if is_rw:
                daily_rework[d] = daily_rework.get(d, 0) + int(objs or 0)
            else:
                daily_first[d] = daily_first.get(d, 0) + int(objs or 0)

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

        # Nộp đúng hạn (DH06)
        submitted_jobs = list(
            jobs.filter(
                status__in=[
                    JobStatus.PENDING_QC1,
                    JobStatus.QC1_REVIEWING,
                    JobStatus.QC1_PASSED,
                    JobStatus.PENDING_QC2,
                    JobStatus.APPROVED,
                    JobStatus.DELIVERED,
                ],
                deadline__isnull=False,
            ).only("deadline", "submitted_at", "updated_at")
        )
        submitted_total = len(submitted_jobs)
        on_time_count = sum(1 for j in submitted_jobs if (j.submitted_at or j.updated_at) <= j.deadline)

        # Sản lượng / chỉ tiêu (SL06 · KPI02 · KPI03) — chỉ tính sản lượng nộp hôm nay so với chỉ tiêu/ngày
        actual_objects = daily_first.get(today, 0) + daily_rework.get(today, 0)
        target_objects = project.kpi_annotation_target
        achievement_pct = _pct(actual_objects, target_objects) if target_objects else None
        shortfall = max(0, target_objects - actual_objects) if target_objects else 0

        # Yêu cầu của tôi (TD13)
        req_qs = AnnotatorRequest.objects.filter(project=project, created_by=user).select_related(
            "job__batch", "review_error__category", "created_by", "handler"
        )
        pending_req_count = req_qs.filter(
            status=AnnotatorRequest.Status.PENDING_PM
        ).count()
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
                status="provisional",
                formula="Job từng bị trả rework ÷ tổng job được giao",
            ),
            "first_pass_yield": _metric(
                _pct(totals["first_pass"], totals["reached_qc2"]),
                status="provisional",
                formula="Job qua QC1 ngay lần đầu ÷ tổng job đã tới QC2",
            ),
            "kpi_target": project.kpi_annotation_target,
            "errors_by_category": [{"category": r["category__name"], "count": r["n"]} for r in top_errors],
            "due_soon": [
                {
                    "id": j.id,
                    "name": j.name,
                    "batch_name": j.batch.name,
                    "status": j.status,
                    "deadline": format_rfc3339_utc(j.deadline),
                    "is_overdue": j.deadline < now,
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
                "target_objects": target_objects,
                "achievement_pct": achievement_pct,
                "shortfall": shortfall,
                "rework_jobs_count": totals["rework"],
                "max_rework_round_active": max_rework_round_active,
                "max_rework_rounds": project.max_rework_rounds,
                "due_soon_count": totals["due_soon_only"],
                "overdue_count": totals["overdue"],
                "fpy_pct": _pct(totals["first_pass"], totals["reached_qc2"]),
                "fpy_passed": totals["first_pass"],
                "fpy_total": totals["reached_qc2"],
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

        start_dt = timezone.make_aware(timezone.datetime.combine(start_date, timezone.datetime.min.time()))
        prev_start_dt = start_dt - timedelta(days=max(days, 7))

        # 1. Năng suất theo ngày (NS01, NS03) — chỉ dữ liệu của chính annotator (PQ01)
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
        start_times_by_job = {}
        if job_ids:
            for start_log in (
                ActivityLog.objects.filter(
                    project=project,
                    job_id__in=job_ids,
                    action="job.status",
                    after__status=JobStatus.ANNOTATING,
                    created_at__lte=now,
                )
                .order_by("created_at", "id")
                .only("job_id", "created_at")
            ):
                start_times_by_job.setdefault(start_log.job_id, []).append(start_log.created_at)

        day_fp = {}
        day_rw = {}
        day_hours = {}
        for log in logs:
            d = timezone.localdate(log.created_at)
            after = log.after or {}
            objs = after.get("object_count")
            if objs is None:
                objs = log.job.object_count if log.job else 0
            objs = int(objs or 0)
            is_rw = after.get("event") == "annotator.resubmit" or (after.get("rework_round") or 0) > 0
            if is_rw:
                day_rw[d] = day_rw.get(d, 0) + objs
            else:
                day_fp[d] = day_fp.get(d, 0) + objs

            session_start = None
            starts = start_times_by_job.get(log.job_id) if log.job_id else None
            if starts:
                idx = bisect_right(starts, log.created_at) - 1
                if idx >= 0:
                    session_start = starts[idx]
            if session_start is None and not is_rw and log.job and log.job.started_at:
                session_start = log.job.started_at

            if session_start and log.created_at > session_start:
                hrs = (log.created_at - session_start).total_seconds() / 3600
                hrs = max(0.25, min(10.0, hrs))
            else:
                hrs = 0.0
            day_hours[d] = day_hours.get(d, 0.0) + hrs

        daily_productivity = []
        total_objects = 0
        total_hours = 0.0
        active_days = 0
        for i in range(days):
            d = start_date + timedelta(days=i)
            fp = day_fp.get(d, 0)
            rw = day_rw.get(d, 0)
            day_total = fp + rw
            is_off = day_total == 0 and d.weekday() == 6
            hrs = day_hours.get(d, 0.0)
            if day_total > 0 and hrs <= 0:
                hrs = 7.5  # mặc định 1 ca công tiêu chuẩn khi chưa có giờ bắt đầu chi tiết
            if day_total > 0:
                active_days += 1
                total_objects += day_total
                total_hours += hrs
            daily_productivity.append({
                "date": d.isoformat(),
                "label": d.strftime("%d/%m"),
                "first_pass_objects": fp,
                "rework_objects": rw,
                "first_pass_per_hour": round(fp / hrs, 1) if hrs > 0 else 0,
                "rework_per_hour": round(rw / hrs, 1) if hrs > 0 else 0,
                "hours": round(hrs, 1),
                "is_off_day": is_off,
            })

        # Fallback nếu chưa có ActivityLog nộp bài nhưng có job đã hoàn tất
        if total_objects == 0:
            done_objs = (
                Job.objects.filter(project=project, annotator=user, status__in=DONE).aggregate(s=Sum("object_count"))["s"]
                or 0
            )
            if done_objs > 0:
                total_objects = done_objs
                active_days = 1
                total_hours = 7.5

        objects_per_hour = round(total_objects / total_hours) if total_hours > 0 else 0

        # 2. Dự báo sản lượng tuần hiện tại (DB05 · KPI01)
        avg_daily = round(total_objects / active_days) if active_days > 0 else 0
        week_start = today - timedelta(days=today.weekday())
        remaining_workdays = sum(
            1 for offset in range(7) if (week_start + timedelta(days=offset)) > today and offset < 6
        )
        estimated_objects = avg_daily * remaining_workdays
        daily_target = project.kpi_annotation_target or 0

        # Chuỗi tuần (thực tế các ngày đã qua + ước tính các ngày công còn lại)
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

        # 3. Xếp hạng sản lượng cá nhân (KPI10) — CHỈ trả hạng của chính user, không lộ dữ liệu người khác.
        annotator_ids = list(
            RoleAssignment.objects.filter(project=project, role=Role.ANNOTATOR)
            .values_list("user_id", flat=True)
            .distinct()
        )
        if user.id not in annotator_ids:
            annotator_ids.append(user.id)

        def _rank_for_window(window_start, window_end=None):
            qs = ActivityLog.objects.filter(
                project=project,
                actor_id__in=annotator_ids,
                action="job.status",
                after__status=JobStatus.PENDING_QC1,
                created_at__gte=window_start,
            ).select_related("job")
            if window_end is not None:
                qs = qs.filter(created_at__lt=window_end)
            scores = {uid: 0 for uid in annotator_ids}
            for ev in qs:
                after = ev.after or {}
                objs = after.get("object_count")
                if objs is None:
                    objs = ev.job.object_count if ev.job else 0
                scores[ev.actor_id] = scores.get(ev.actor_id, 0) + int(objs or 0)
            if window_end is None and all(v == 0 for v in scores.values()):
                for row in (
                    Job.objects.filter(project=project, annotator_id__in=annotator_ids, status__in=DONE)
                    .values("annotator_id")
                    .annotate(s=Sum("object_count"))
                ):
                    scores[row["annotator_id"]] = row["s"] or 0
            my_score = scores.get(user.id, 0)
            return 1 + sum(1 for v in scores.values() if v > my_score)

        current_rank = _rank_for_window(start_dt)
        previous_rank = _rank_for_window(prev_start_dt, start_dt)

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
        qc1_errors = ReviewError.objects.filter(job__project=project, stage=ReviewStage.QC1)
        qc2_escapes = ReviewError.objects.filter(job__project=project, stage=ReviewStage.QC2)

        if scope == "mine":
            jobs = jobs.filter(qc1_reviewer=user)
            logs = logs.filter(actor=user)
            qc1_errors = qc1_errors.filter(reported_by=user)
            qc2_escapes = qc2_escapes.filter(job__qc1_reviewer=user)

        since = _period_start(request)
        now = timezone.now()
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
        )
        stats = {**queue_stats, **decision_stats}

        kpi = {
            "current": self._window(logs, qc1_errors, since, now),
            "previous": self._window(logs, qc1_errors, since - length, since),
        }

        trend_days = 30 if length.days >= 30 else 7
        start = (now - timedelta(days=trend_days - 1)).date()
        tz = timezone.get_current_timezone()
        daily = {
            r["day"]: r
            for r in logs.filter(created_at__date__gte=start)
            .annotate(day=TruncDate("created_at", tzinfo=tz))
            .values("day")
            .annotate(
                reviewed=Count("id"),
                rejected=Count("id", filter=Q(action="qc1.reject")),
            )
        }
        daily_errors = dict(
            qc1_errors.filter(created_at__date__gte=start)
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

        return Response({
            "scope": scope,
            "stats": stats,
            "pass_rate": _pct(stats["passed"], stats["passed"] + stats["rejected"]),
            "kpi": kpi,
            "trend": trend,
            "qc2_escape_errors": qc2_escapes.count(),
            "errors_by_category": [{"category": r["category__name"], "count": r["n"]} for r in by_category],
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
