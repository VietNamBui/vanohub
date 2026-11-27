"""Dashboard & KPI. Không có model riêng: tổng hợp từ dữ liệu của projects, jobs, quality, teams.

QUY ƯỚC: chỉ số nào chưa chốt công thức thì trả về value=None kèm status="pending_definition".
Chỉ số "tạm tính" (provisional) có ghi công thức đang dùng để nhóm kiểm tra.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from accounts.datetime_utils import app_timezone, format_local_datetime, local_date
from accounts.models import Role, RoleAssignment, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from django.db.models import (
    BigIntegerField,
    Case,
    Count,
    F,
    IntegerField,
    Max,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, TruncDate
from django.utils import timezone
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, OPEN_STATUSES, STAGE_STATUSES, AnnotatorRequest, Job, JobStatus
from jobs.serializers import AnnotatorRequestSerializer, JobSerializer, ReviewErrorBriefSerializer
from jobs.views import order_by_db06_priority
from projects.models import ActivityLog, Batch, DataStatus
from quality.models import Audit, AuditSample, ReviewError, ReviewStage
from quality.qc2 import ANNOTATOR_EVENTS
from rest_framework.response import Response
from rest_framework.views import APIView
from teams.models import Team, TeamMember

PERIODS = {"day": 1, "week": 7, "month": 30}
DONE = STAGE_STATUSES["done"]
REACHED_QC2 = [JobStatus.PENDING_QC2, *DONE]
REACHED_QC1_OUTCOME = [*REACHED_QC2, JobStatus.REWORK]
REWORKED_Q = Q(total_rework_rounds__gt=0) | Q(rework_round__gt=0)
FIRST_PASS_Q = Q(status__in=REACHED_QC2, total_rework_rounds=0, rework_round=0)
FPY_DENOM_Q = Q(status__in=REACHED_QC1_OUTCOME) | REWORKED_Q


def _metric(value, *, status="ok", formula=""):
    return {"value": value, "status": status, "formula": formula}


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


def _period_start(request, now=None):
    days = PERIODS.get(request.query_params.get("period", "week"), 7)
    return (now or timezone.now()) - timedelta(days=days)


def _local_day_start(day):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()), app_timezone())


class ProjectOverviewView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/overview/?period=day|week|month"""

    required_capabilities = {"*": Cap.VIEW_DASHBOARD}

    def get(self, request, project_id):
        project = self.project
        now = timezone.now()
        since = _period_start(request, now=now)
        jobs = Job.objects.filter(project=project)

        totals = jobs.aggregate(
            total=Count("id"),
            objects=Sum("object_count"),
            frames=Sum("frame_count"),
            done=Count("id", filter=Q(status__in=DONE)),
            reached_qc2=Count("id", filter=Q(status__in=REACHED_QC2)),
            fpy_total=Count("id", filter=FPY_DENOM_Q),
            first_pass=Count("id", filter=FIRST_PASS_Q),
            reworked=Count("id", filter=REWORKED_Q),
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
                           "message": f"{job.name} quá hạn từ {format_local_datetime(job.deadline)}"})
        for job in jobs.filter(deadline__gte=now, deadline__lte=now + timedelta(hours=24),
                               status__in=OPEN_STATUSES).order_by("deadline")[:10]:
            alerts.append({"level": "info", "type": "due_soon", "job": job.id,
                           "message": f"{job.name} đến hạn lúc {format_local_datetime(job.deadline)}"})

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
                "delivery_readiness": _metric(
                    _pct(by_status.get(JobStatus.APPROVED, 0) + by_status.get(JobStatus.DELIVERED, 0), totals["total"]),
                    status="provisional", formula="Job Đã duyệt + Đã bàn giao ÷ tổng job",
                ),
                "rework_rate": _metric(_pct(totals["reworked"], totals["total"]), status="provisional",
                                       formula="Job từng bị rework ÷ tổng job"),
                "first_pass_yield": _metric(_pct(totals["first_pass"], totals["fpy_total"]), status="provisional",
                                            formula="Job qua QC1 ngay lần đầu ÷ tổng job đã có kết quả QC1"),
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
        teams = list(Team.objects.filter(project=self.project))
        team_members: dict[int, set[int]] = defaultdict(set)
        all_member_ids: set[int] = set()
        for team_id, user_id in TeamMember.objects.filter(team__project=self.project).values_list("team_id", "user_id"):
            team_members[team_id].add(user_id)
            all_member_ids.add(user_id)

        job_stats_by_user = {}
        qc2_errors_by_user = {}
        if all_member_ids:
            job_stats_by_user = {
                row["annotator_id"]: row
                for row in Job.objects.filter(project=self.project, annotator_id__in=all_member_ids)
                .values("annotator_id")
                .annotate(
                    total=Count("id"),
                    done=Count("id", filter=Q(status__in=DONE)),
                    objects=Sum("object_count", filter=Q(status__in=DONE)),
                    reworked=Count("id", filter=REWORKED_Q),
                    escalated=Count("id", filter=Q(is_escalated=True)),
                )
            }
            qc2_errors_by_user = dict(
                ReviewError.objects.filter(
                    job__project=self.project,
                    job__annotator_id__in=all_member_ids,
                    stage=ReviewStage.QC2,
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
            objects_done = sum((job_stats_by_user[uid]["objects"] or 0) for uid in member_ids if uid in job_stats_by_user)
            reworked = sum(job_stats_by_user[uid]["reworked"] for uid in member_ids if uid in job_stats_by_user)
            escalated = sum(job_stats_by_user[uid]["escalated"] for uid in member_ids if uid in job_stats_by_user)
            qc2_errors = sum(qc2_errors_by_user.get(uid, 0) for uid in member_ids)
            rows.append({
                "team": {"id": team.id, "name": team.name},
                "members": len(member_ids),
                "jobs": total,
                "done": done,
                "objects_done": objects_done,
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
        return Response({"formula": "Tạm tính: object đã xong (giảm dần), rồi tỉ lệ rework (tăng dần)", "rows": rows})


class Qc2SummaryView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/qc2-summary/ — dashboard QC2 (QC2-01). PM xem toàn dự án, QC2 xem của mình."""

    required_capabilities = {"*": Cap.PERFORM_AUDIT}

    def get(self, request, project_id):
        samples = AuditSample.objects.filter(audit__project=self.project)
        scope = "project" if self.has_cap(Cap.MANAGE_AUDITS) and request.query_params.get("scope") != "mine" else "mine"
        if scope == "mine":
            # Mẫu đã hoàn tất tính theo người trực tiếp review (reviewed_by), mẫu đang chờ tính theo auditor — tránh đếm trùng.
            samples = samples.filter(
                Q(result=AuditSample.Result.PENDING, auditor=request.user)
                | Q(result__in=[AuditSample.Result.PASS, AuditSample.Result.REJECT], reviewed_by=request.user)
            )
        now = timezone.now()
        since = _period_start(request, now=now)
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
        length = now - since
        kpi = {"current": self._window(samples, errors, since, now),
               "previous": self._window(samples, errors, since - length, since)}

        # Xu hướng theo ngày theo giờ Việt Nam (Asia/Ho_Chi_Minh).
        trend_days = 30 if length.days >= 30 else 7
        tz = app_timezone()
        start = local_date(now) - timedelta(days=trend_days - 1)
        start_dt = _local_day_start(start)
        daily = {
            r["day"]: r for r in samples.filter(reviewed_at__gte=start_dt)
            .annotate(day=TruncDate("reviewed_at", tzinfo=tz)).values("day")
            .annotate(audited=Count("id"), rejected=Count("id", filter=Q(result=AuditSample.Result.REJECT)))
        }
        daily_errors = dict(
            errors.filter(created_at__gte=start_dt).annotate(day=TruncDate("created_at", tzinfo=tz))
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
                total=Count("id"),
                done=Count("id", filter=Q(status__in=DONE)),
                objects_done=Sum("object_count", filter=Q(status__in=DONE)),
                reworked=Count("id", filter=REWORKED_Q),
            )
        )
        users = {u.id: u for u in User.objects.filter(pk__in=[r["annotator"] for r in rows])}
        return Response([
            {
                "user": UserBriefSerializer(users[r["annotator"]]).data,
                "jobs": r["total"],
                "done": r["done"],
                "objects_done": r["objects_done"] or 0,
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
        now = timezone.now()
        today = local_date(now)
        since = _period_start(request, now=now)

        jobs = Job.objects.filter(project=project, annotator=user)
        totals = jobs.aggregate(
            total=Count("id"),
            pending_annotation=Count("id", filter=Q(status=JobStatus.PENDING_ANNOTATION)),
            annotating=Count("id", filter=Q(status=JobStatus.ANNOTATING)),
            rework=Count("id", filter=Q(status=JobStatus.REWORK)),
            waiting_review=Count(
                "id",
                filter=Q(status__in=[JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING, JobStatus.PENDING_QC2]),
            ),
            done=Count("id", filter=Q(status__in=DONE)),
            objects_done=Sum("object_count", filter=Q(status__in=DONE)),
            fpy_total=Count("id", filter=FPY_DENOM_Q),
            first_pass=Count("id", filter=FIRST_PASS_Q),
            reworked=Count("id", filter=REWORKED_Q),
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
        team_leader_name = None
        last_sync = project.cvat_synced_at
        if last_sync is None:
            last_sync = (
                Batch.objects.filter(project=project, last_synced_at__isnull=False)
                .order_by("-last_synced_at")
                .values_list("last_synced_at", flat=True)
                .first()
            )

        # Tổng hợp đầy đủ trên toàn bộ active_base (không tính trên lát cắt [:10])
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
            max_rework_round_active=Coalesce(
                Max("rework_round", filter=Q(status=JobStatus.REWORK)),
                0,
            ),
        )
        active_jobs_count = active_agg["active_jobs_count"]
        active_object_frames = active_agg["active_object_frames"]
        max_rework_round_active = active_agg["max_rework_round_active"]

        # Công việc tiếp theo (quá hạn → sắp hạn → rework → còn lại)
        active_qs = order_by_db06_priority(
            active_base.select_related("batch", "dataset", "annotator", "qc1_reviewer", "project")
            .annotate(
                _active_rework_error_count=Count(
                    "review_errors",
                    filter=Q(
                        status__in=[JobStatus.REWORK, JobStatus.ANNOTATING],
                        rework_round__gt=0,
                        review_errors__rework_round=F("rework_round") - 1,
                    ),
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

        # Việc cần sửa nổi bật tìm trên toàn bộ active_base (không bị bỏ sót sau vị trí thứ 10)
        rework_job = (
            order_by_db06_priority(active_base.filter(status=JobStatus.REWORK).select_related("batch"), now=now).first()
            or order_by_db06_priority(
                active_base.filter(rework_round__gt=0).select_related("batch"), now=now
            ).first()
        )
        rework_focus = None
        if rework_job:
            latest_round = max(0, rework_job.rework_round - 1)
            err_qs = (
                rework_job.review_errors.filter(rework_round=latest_round)
                .select_related("category", "reported_by")
                .order_by("-created_at")
            )
            err_list = list(err_qs[:5])
            total_errs = err_qs.count()
            rework_focus = {
                "job_id": rework_job.id,
                "job_name": rework_job.name,
                "batch_name": rework_job.batch.name,
                "deadline": rework_job.deadline,
                "rework_round": rework_job.rework_round,
                "max_rework_rounds": project.max_rework_rounds,
                "rework_scope": rework_job.rework_scope,
                "rework_scope_label": rework_job.get_rework_scope_display(),
                "error_count": total_errs,
                "pending_object_frames": total_errs,
                "errors": ReviewErrorBriefSerializer(err_list, many=True).data,
            }

        # Kết quả theo ngày 7 ngày gần nhất theo giờ Việt Nam (Asia/Ho_Chi_Minh)
        start_7d = _local_day_start(today - timedelta(days=6))
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
        daily_first_jobs = {}
        daily_rework_jobs = {}
        for log in sub_logs:
            d = local_date(log.created_at)
            after = log.after or {}
            objs = after.get("object_count")
            if objs is None:
                objs = log.job.object_count if log.job else 0
            objs = int(objs or 0)
            job_key = log.job_id if log.job_id is not None else f"log:{log.pk}"
            is_rw = after.get("event") == "annotator.resubmit" or (after.get("rework_round") or 0) > 0
            if is_rw:
                daily_rework_jobs.setdefault(d, {})[job_key] = objs
            else:
                daily_first_jobs.setdefault(d, {})[job_key] = objs

        daily_target = project.kpi_annotation_target or 0
        daily_results = []
        for offset in range(6, -1, -1):
            d = today - timedelta(days=offset)
            fp_map = daily_first_jobs.get(d, {})
            rw_map = daily_rework_jobs.get(d, {})
            fp = sum(fp_map.values())
            rw = sum(rw_map.values())
            # Không cộng trùng nếu cùng một job vừa nộp lần đầu vừa nộp rework trong cùng ngày
            total_d = fp + sum(v for k, v in rw_map.items() if k not in fp_map)
            daily_results.append({
                "date": d.isoformat(),
                "label": d.strftime("%d/%m"),
                "first_pass_objects": fp,
                "rework_objects": rw,
                "total_objects": total_d,
                "target_objects": daily_target,
                "is_off_day": total_d == 0 and d.weekday() == 6,
            })

        # Nộp đúng hạn (DH06): tổng hợp trên DB theo submitted_at <= deadline (không dùng updated_at)
        # và tính các job đang giữ đã quá hạn là trễ hạn.
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

        # Sản lượng / chỉ tiêu hôm nay: không fallback sang tích luỹ toàn thời gian và không thổi phồng bằng nộp lại rework.
        today_first_pass = sum(daily_first_jobs.get(today, {}).values())
        today_rework = sum(daily_rework_jobs.get(today, {}).values())
        actual_objects = today_first_pass
        target_objects = project.kpi_annotation_target
        achievement_pct = _pct(actual_objects, target_objects) if target_objects else None
        shortfall = max(0, target_objects - actual_objects) if target_objects else 0

        # Yêu cầu của tôi (TD13)
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
                status="provisional",
                formula="Job từng bị trả rework ÷ tổng job được giao",
            ),
            "first_pass_yield": _metric(
                _pct(totals["first_pass"], totals["fpy_total"]),
                status="provisional",
                formula="Job qua QC1 ngay lần đầu ÷ tổng job đã có kết quả QC1",
            ),
            "kpi_target": project.kpi_annotation_target,
            "errors_by_category": [{"category": r["category__name"], "count": r["n"]} for r in top_errors],
            "due_soon": [
                {
                    "id": j.id,
                    "name": j.name,
                    "batch_name": j.batch.name,
                    "status": j.status,
                    "deadline": j.deadline,
                    "is_overdue": j.deadline < now,
                }
                for j in due_soon
            ],
            "meta": {
                "team_name": team_name,
                "team_leader_name": team_leader_name,
                "project_name": project.name,
                "last_cvat_sync_at": last_sync,
                "wip_limit": project.annotator_wip_limit,
                "active_jobs_count": active_jobs_count,
                "active_object_frames": active_object_frames,
            },
            "kpi_summary": {
                "actual_objects": actual_objects,
                "today_first_pass": today_first_pass,
                "today_rework": today_rework,
                "target_objects": target_objects,
                "achievement_pct": achievement_pct,
                "shortfall": shortfall,
                "rework_jobs_count": totals["rework"],
                "max_rework_round_active": max_rework_round_active,
                "max_rework_rounds": project.max_rework_rounds,
                "due_soon_count": totals["due_soon_only"],
                "overdue_count": totals["overdue"],
                "fpy_pct": _pct(totals["first_pass"], totals["fpy_total"]),
                "fpy_passed": totals["first_pass"],
                "fpy_total": totals["fpy_total"],
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

        start_dt = _local_day_start(start_date)
        prev_start_dt = start_dt - timedelta(days=max(days, 7))

        # 1. Năng suất theo ngày (NS01, NS03) — chỉ dữ liệu thực của chính annotator (PQ01)
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
        day_fp_jobs = {}
        day_rw_jobs = {}
        day_hours = {}
        for log in logs:
            d = local_date(log.created_at)
            after = log.after or {}
            objs = after.get("object_count")
            if objs is None:
                objs = log.job.object_count if log.job else 0
            objs = int(objs or 0)
            job_key = log.job_id if log.job_id is not None else f"log:{log.pk}"
            is_rw = after.get("event") == "annotator.resubmit" or (after.get("rework_round") or 0) > 0
            if is_rw:
                day_rw_jobs.setdefault(d, {})[job_key] = objs
            else:
                day_fp_jobs.setdefault(d, {})[job_key] = objs

            if log.job and log.job.started_at:
                end_dt = log.created_at
                if end_dt < log.job.started_at and log.job.submitted_at and log.job.submitted_at >= log.job.started_at:
                    end_dt = log.job.submitted_at
                if end_dt >= log.job.started_at:
                    hrs = (end_dt - log.job.started_at).total_seconds() / 3600
                    hrs = max(0.05, min(10.0, hrs))
                else:
                    hrs = 0.0
            else:
                hrs = 0.0
            day_hours[d] = day_hours.get(d, 0.0) + hrs

        daily_productivity = []
        total_objects = 0
        total_hours = 0.0
        active_days = 0
        for i in range(days):
            d = start_date + timedelta(days=i)
            fp_map = day_fp_jobs.get(d, {})
            rw_map = day_rw_jobs.get(d, {})
            fp = sum(fp_map.values())
            rw = sum(rw_map.values())
            day_total = fp + sum(v for k, v in rw_map.items() if k not in fp_map)
            is_off = day_total == 0 and d.weekday() == 6
            hrs = min(24.0, day_hours.get(d, 0.0))
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
                fp_map = day_fp_jobs.get(d, {})
                rw_map = day_rw_jobs.get(d, {})
                actual = sum(fp_map.values()) + sum(v for k, v in rw_map.items() if k not in fp_map)
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

        # 3. Xếp hạng sản lượng cá nhân (KPI10) — tổng hợp trên DB, chỉ tính lần nộp đầu (không thổi phồng bằng rework).
        annotator_ids = list(
            RoleAssignment.objects.filter(project=project, role=Role.ANNOTATOR)
            .values_list("user_id", flat=True)
            .distinct()
        )
        if user.id not in annotator_ids:
            annotator_ids.append(user.id)

        obj_expr = Coalesce(
            Cast(KeyTextTransform("object_count", "after"), IntegerField()),
            F("job__object_count"),
            Value(0),
            output_field=IntegerField(),
        )

        def _rank_for_window(window_start, window_end=None, *, none_if_empty=False):
            qs = (
                ActivityLog.objects.filter(
                    project=project,
                    actor_id__in=annotator_ids,
                    action="job.status",
                    after__status=JobStatus.PENDING_QC1,
                    created_at__gte=window_start,
                )
                .filter(Q(after__event__isnull=True) | ~Q(after__event="annotator.resubmit"))
                .filter(Q(after__rework_round__isnull=True) | Q(after__rework_round=0))
            )
            if window_end is not None:
                qs = qs.filter(created_at__lt=window_end)
            rows = list(qs.values("actor_id").annotate(score=Sum(obj_expr)))
            if not rows:
                return None if none_if_empty else 1
            scores = {uid: 0 for uid in annotator_ids}
            for row in rows:
                scores[row["actor_id"]] = int(row["score"] or 0)
            if none_if_empty and all(v == 0 for v in scores.values()):
                return None
            my_score = scores.get(user.id, 0)
            return 1 + sum(1 for v in scores.values() if v > my_score)

        current_rank = _rank_for_window(start_dt, none_if_empty=False)
        previous_rank = _rank_for_window(prev_start_dt, start_dt, none_if_empty=True)

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
        scope = "project" if self.has_cap(Cap.VIEW_DASHBOARD) and request.query_params.get("scope") != "mine" else "mine"

        now = timezone.now()
        since = _period_start(request, now=now)
        length = now - since

        logs = ActivityLog.objects.filter(project=project, action__in=["qc1.pass", "qc1.reject"])
        qc1_errors = ReviewError.objects.filter(job__project=project, stage=ReviewStage.QC1)

        pool_q = Q(
            qc1_reviewer__isnull=True,
            status=JobStatus.PENDING_QC1,
            is_locked=False,
            is_escalated=False,
            batch__status=DataStatus.ACTIVE,
            dataset__status=DataStatus.ACTIVE,
        )

        # Lỗi lọt sang QC2 lọc theo kỳ và quy trách nhiệm cho người duyệt qc1.pass (fallback job.qc1_reviewer).
        pass_actor_before = Subquery(
            ActivityLog.objects.filter(
                project=project,
                job_id=OuterRef("job_id"),
                action="qc1.pass",
                actor_id__isnull=False,
                created_at__lte=OuterRef("created_at"),
            )
            .order_by("-created_at", "-id")
            .values("actor_id")[:1]
        )
        pass_actor_any = Subquery(
            ActivityLog.objects.filter(
                project=project,
                job_id=OuterRef("job_id"),
                action="qc1.pass",
                actor_id__isnull=False,
            )
            .order_by("-created_at", "-id")
            .values("actor_id")[:1]
        )
        qc2_escapes = ReviewError.objects.filter(
            job__project=project,
            stage=ReviewStage.QC2,
            created_at__gte=since,
        ).annotate(
            attributed_qc1_id=Coalesce(
                pass_actor_before,
                pass_actor_any,
                F("job__qc1_reviewer_id"),
                output_field=BigIntegerField(),
            )
        )

        if scope == "mine":
            logs = logs.filter(actor=user)
            qc1_errors = qc1_errors.filter(reported_by=user)
            qc2_escapes = qc2_escapes.filter(attributed_qc1_id=user.id)

            mine_agg = Job.objects.filter(project=project, qc1_reviewer=user).aggregate(
                assigned=Count("id", filter=Q(status__in=STAGE_STATUSES["qc1"])),
                my_pending=Count("id", filter=Q(status=JobStatus.PENDING_QC1)),
                reviewing=Count("id", filter=Q(status=JobStatus.QC1_REVIEWING)),
            )
            hist_ann_job_ids = (
                ActivityLog.objects.filter(project=project, actor=user, job_id__isnull=False)
                .filter(
                    Q(action__in=ANNOTATOR_EVENTS)
                    | Q(action__in=("job.status", "job.assign"), after__event__in=ANNOTATOR_EVENTS)
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
            pool_pending = (
                Job.objects.filter(project=project)
                .filter(pool_q)
                .exclude(
                    Q(annotator=user)
                    | Q(pk__in=hist_ann_job_ids)
                    | Q(pk__in=hist_qc2_sample_job_ids)
                    | Q(pk__in=hist_qc2_err_job_ids)
                )
                .count()
            )
            queue_stats = {
                "assigned": mine_agg["assigned"],
                "pending": mine_agg["my_pending"] + pool_pending,
                "pool_pending": pool_pending,
                "reviewing": mine_agg["reviewing"],
            }
        else:
            queue_stats = Job.objects.filter(project=project).aggregate(
                assigned=Count("id", filter=Q(status__in=STAGE_STATUSES["qc1"])),
                pending=Count("id", filter=Q(status=JobStatus.PENDING_QC1)),
                pool_pending=Count("id", filter=pool_q),
                reviewing=Count("id", filter=Q(status=JobStatus.QC1_REVIEWING)),
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
        tz = app_timezone()
        start = local_date(now) - timedelta(days=trend_days - 1)
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
