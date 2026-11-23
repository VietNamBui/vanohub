"""API cho Team Leader (TL-01, TL-02, TL-05, TL-09). Mọi thứ giới hạn trong team mà user đang làm leader.

ĐỀ XUẤT (chưa chốt) — "job của team" = job thuộc batch được PM giao cho team
HOẶC job đang do thành viên team annotate / QC1.
"""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role, RoleAssignment, expand_roles
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from jobs.models import OPEN_STATUSES, STAGE_STATUSES, Job, JobStatus
from jobs.serializers import AssignSerializer, BulkSerializer, DeadlineSerializer, JobDetailSerializer, JobSerializer
from jobs.views import assign_job, set_job_deadline
from projects.models import ActivityLog
from projects.views import StandardPagination
from quality.models import Audit, AuditSample

from .models import Team, TeamMember

DONE = [JobStatus.APPROVED, JobStatus.DELIVERED]
PERIODS = {"day": 1, "week": 7, "month": 30}
# Tab của TL-02: Đang làm / Chờ QC.
TAB_STATUSES = {
    "doing": [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING, JobStatus.REWORK],
    "qc": [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING, JobStatus.PENDING_QC2],
}


def _pct(part, whole):
    return round(part * 100 / whole, 1) if whole else None


class LeaderMixin(ProjectScopedViewMixin):
    required_capabilities = {"*": Cap.LEAD_TEAM}

    def led_teams(self):
        """Các team user đang làm leader. ?team=<id> để chọn một team (không phải team của mình → 404)."""
        teams = Team.objects.filter(project=self.project, leader=self.request.user)
        team_id = self.request.query_params.get("team")
        if team_id:
            teams = teams.filter(pk=team_id)
            if not teams.exists():
                raise NotFound("Bạn không phải leader của team này.")
        return teams

    def member_ids(self, teams=None):
        teams = self.led_teams() if teams is None else teams
        return set(TeamMember.objects.filter(team__in=teams).values_list("user_id", flat=True))

    def team_jobs(self, teams=None):
        teams = self.led_teams() if teams is None else teams
        members = self.member_ids(teams)
        return Job.objects.filter(project=self.project).filter(
            Q(batch__team__in=teams) | Q(annotator_id__in=members) | Q(qc1_reviewer_id__in=members)
        ).distinct()


def _member_stats(project, user_ids):
    """Số liệu annotate của từng người (toàn dự án): tổng job, job xong, object xong, job từng bị rework."""
    rows = (
        Job.objects.filter(project=project, annotator_id__in=user_ids)
        .values("annotator")
        .annotate(
            total=Count("id"),
            done=Count("id", filter=Q(status__in=DONE)),
            objects_done=Sum("object_count", filter=Q(status__in=DONE)),
            reworked=Count("id", filter=Q(rework_round__gt=0)),
        )
    )
    return {r["annotator"]: r for r in rows}


class LeaderTeamsView(LeaderMixin, APIView):
    """GET /api/projects/{id}/leader/teams/ — team mình phụ trách + thành viên, vai trò, tải công việc (TL-05, TL-09)."""

    def get(self, request, project_id):
        now = timezone.now()
        teams = list(self.led_teams().prefetch_related(Prefetch("members", queryset=TeamMember.objects.select_related("user"))))
        user_ids = {m.user_id for t in teams for m in t.members.all()}
        open_jobs = Job.objects.filter(project=self.project, status__in=OPEN_STATUSES)
        holding = {
            r["annotator"]: r for r in open_jobs.filter(annotator_id__in=user_ids).values("annotator").annotate(
                n=Count("id"),
                due_soon=Count("id", filter=Q(deadline__lte=now + timedelta(hours=24))),
                escalated=Count("id", filter=Q(is_escalated=True)),
            )
        }
        qc1_holding = dict(open_jobs.filter(qc1_reviewer_id__in=user_ids).values_list("qc1_reviewer").annotate(n=Count("id")))
        direct = {}
        for a in RoleAssignment.objects.filter(project=self.project, user_id__in=user_ids):
            direct.setdefault(a.user_id, set()).add(a.role)
        stats = _member_stats(self.project, user_ids)

        def member(m):
            h, s = holding.get(m.user_id, {}), stats.get(m.user_id, {})
            roles = direct.get(m.user_id, set())
            return {
                "user": UserBriefSerializer(m.user).data,
                "email": m.user.email,
                "roles": sorted(expand_roles(roles)),
                "direct_roles": sorted(roles),
                "joined_at": m.joined_at,
                "capacity": m.capacity,
                "holding": h.get("n", 0),
                "qc1_holding": qc1_holding.get(m.user_id, 0),
                "due_soon": h.get("due_soon", 0),
                "escalated": h.get("escalated", 0),
                "jobs_total": s.get("total", 0),
                "jobs_done": s.get("done", 0),
                "rework_rate": _pct(s.get("reworked", 0), s.get("total", 0)),
            }

        return Response([
            {"id": t.id, "name": t.name, "members": [member(m) for m in t.members.all()]} for t in teams
        ])


class LeaderDashboardView(LeaderMixin, APIView):
    """GET /api/projects/{id}/leader/dashboard/?team=&period=day|week|month — Tổng quan team (TL-01)."""

    def get(self, request, project_id):
        now = timezone.now()
        since = now - timedelta(days=PERIODS.get(request.query_params.get("period", "week"), 7))
        teams = self.led_teams()
        members = self.member_ids(teams)
        jobs = self.team_jobs(teams)
        totals = Job.objects.filter(pk__in=jobs.values("pk")).aggregate(
            total=Count("id"),
            done=Count("id", filter=Q(status__in=DONE)),
            done_in_period=Count("id", filter=Q(status__in=DONE, updated_at__gte=since)),
            reworked=Count("id", filter=Q(rework_round__gt=0)),
            open=Count("id", filter=Q(status__in=OPEN_STATUSES)),
        )
        stats = _member_stats(self.project, members)
        users = {m.user_id: m.user for m in TeamMember.objects.filter(team__in=teams).select_related("user")}
        ranking = sorted(
            (
                {
                    "user": UserBriefSerializer(users[uid]).data,
                    "jobs_total": s.get("total", 0),
                    "jobs_done": s.get("done", 0),
                    "objects_done": s.get("objects_done") or 0,
                    "rework_rate": _pct(s.get("reworked", 0), s.get("total", 0)),
                }
                for uid in users
                for s in [stats.get(uid, {})]
            ),
            key=lambda r: (-r["jobs_done"], -r["objects_done"], r["user"]["username"]),
        )
        due_soon = (
            Job.objects.filter(pk__in=jobs.values("pk"), status__in=OPEN_STATUSES, deadline__lte=now + timedelta(hours=24))
            .select_related("annotator", "batch").order_by("deadline")[:10]
        )
        return Response({
            "teams": [{"id": t.id, "name": t.name} for t in teams],
            "member_count": len(members),
            "jobs_total": totals["total"],
            "jobs_open": totals["open"],
            # Tạm tính: "xong trong kỳ" dựa vào thời điểm cập nhật cuối của job đã duyệt.
            "done_in_period": {"value": totals["done_in_period"], "status": "provisional",
                               "formula": "Job Đã duyệt / Đã bàn giao có lần cập nhật cuối trong kỳ (tạm tính)."},
            "kpi_by_total": {"value": _pct(totals["done"], totals["total"]), "status": "provisional",
                             "formula": "Job xong / tổng job của team × 100% (tạm tính)."},
            "kpi_quota": {"value": None, "status": "pending_definition",
                          "formula": "Chưa chốt: KPI khoán đặt theo người, theo team hay theo batch?"},
            "rework_rate": {"value": _pct(totals["reworked"], totals["total"]), "status": "provisional",
                            "formula": "Job từng bị trả rework / tổng job của team × 100% (tạm tính)."},
            "ranking": ranking,
            "due_soon": [
                {"id": j.id, "name": j.name, "batch_name": j.batch.name, "status": j.status,
                 "annotator": UserBriefSerializer(j.annotator).data if j.annotator else None,
                 "deadline": j.deadline, "is_overdue": j.deadline < now}
                for j in due_soon
            ],
        })


class LeaderJobViewSet(LeaderMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Job của team (TL-02): xem, giao lại trong team, đặt deadline (lẻ hoặc hàng loạt)."""

    pagination_class = StandardPagination

    def get_serializer_class(self):
        return JobDetailSerializer if self.action == "retrieve" else JobSerializer

    def get_queryset(self):
        queryset = Job.objects.filter(pk__in=self.team_jobs().values("pk")).select_related(
            "batch__dataset", "annotator", "qc1_reviewer", "project"
        ).prefetch_related(Prefetch(
            "audit_samples",
            queryset=AuditSample.objects.filter(audit__status=Audit.Status.IN_PROGRESS).select_related("auditor"),
            to_attr="open_samples",
        ))
        p = self.request.query_params
        tab = p.get("tab")
        if tab in TAB_STATUSES:
            queryset = queryset.filter(status__in=TAB_STATUSES[tab])
        elif tab == "escalated":
            queryset = queryset.filter(is_escalated=True)
        if p.get("stage") in STAGE_STATUSES:
            queryset = queryset.filter(status__in=STAGE_STATUSES[p["stage"]])
        if p.get("search"):
            s = p["search"]
            queryset = queryset.filter(Q(name__icontains=s) | Q(batch__name__icontains=s) | Q(annotator__username__icontains=s))
        return queryset.order_by("deadline", "id")

    def _validated_assignment(self, request):
        """Như PM giao việc, thêm điều kiện: người nhận phải là thành viên team mình phụ trách."""
        serializer = AssignSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        members = self.member_ids()
        for field in ("annotator", "qc1_reviewer"):
            user = serializer.validated_data.get(field)
            if user and user.id not in members:
                raise ValidationError({field: f"{user} không thuộc team bạn phụ trách."})
        return serializer.validated_data

    def _detail(self, job):
        return Response(JobDetailSerializer(self.get_queryset().get(pk=job.pk), context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, project_id, pk=None):
        job = self.get_object()
        assign_job(job, self._validated_assignment(request), request.user, self.project)
        return self._detail(job)

    @action(detail=True, methods=["post"])
    def deadline(self, request, project_id, pk=None):
        job = self.get_object()
        serializer = DeadlineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_job_deadline(job, serializer.validated_data["deadline"], serializer.validated_data["note"], request.user, self.project)
        return self._detail(job)

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request, project_id):
        ids = BulkSerializer(data=request.data)
        ids.is_valid(raise_exception=True)
        data = self._validated_assignment(request)
        jobs = list(self.get_queryset().filter(pk__in=ids.validated_data["ids"]))
        with transaction.atomic():
            for job in jobs:
                assign_job(job, data, request.user, self.project)
        return Response({"updated": len(jobs)})

    @action(detail=False, methods=["post"], url_path="bulk-deadline")
    def bulk_deadline(self, request, project_id):
        ids = BulkSerializer(data=request.data)
        ids.is_valid(raise_exception=True)
        data = DeadlineSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        jobs = list(self.get_queryset().filter(pk__in=ids.validated_data["ids"]))
        with transaction.atomic():
            for job in jobs:
                set_job_deadline(job, data.validated_data["deadline"], data.validated_data["note"], request.user, self.project)
        return Response({"updated": len(jobs)})


class LeaderMemberQc1View(LeaderMixin, APIView):
    """POST / DELETE /api/projects/{id}/leader/teams/{team_id}/members/{user_id}/qc1/ — TL cấp / thu quyền QC1.

    ĐỀ XUẤT: không thu được QC1 có sẵn do vai trò Team Leader; người đang giữ job QC1 chưa xong
    phải được giao lại job trước khi thu quyền.
    """

    def _member(self, team_id, user_id):
        team = get_object_or_404(self.led_teams(), pk=team_id)
        membership = TeamMember.objects.filter(team=team, user_id=user_id).select_related("user").first()
        if not membership:
            raise NotFound("Người này không thuộc team.")
        return team, membership.user

    def post(self, request, project_id, team_id, user_id):
        team, user = self._member(team_id, user_id)
        if Role.QC1 in user.get_project_roles(self.project):
            raise ValidationError("Người này đã có quyền QC1.")
        RoleAssignment.objects.create(user=user, role=Role.QC1, project=self.project)
        ActivityLog.record(project=self.project, actor=request.user, action="member.grant_qc1", target=user,
                           after={"team": team.name})
        return Response({"user": user.id, "roles": sorted(user.get_project_roles(self.project))}, status=status.HTTP_201_CREATED)

    def delete(self, request, project_id, team_id, user_id):
        team, user = self._member(team_id, user_id)
        assignment = RoleAssignment.objects.filter(user=user, role=Role.QC1, project=self.project).first()
        if not assignment:
            if Role.QC1 in user.get_project_roles(self.project):
                raise ValidationError("QC1 của người này đi kèm vai trò Team Leader — không thu riêng được.")
            raise ValidationError("Người này không có quyền QC1.")
        open_qc1 = Job.objects.filter(
            project=self.project, qc1_reviewer=user, status__in=[JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING]
        ).count()
        if open_qc1:
            raise ValidationError(f"Người này đang giữ {open_qc1} job QC1 chưa xong — giao lại các job đó trước.")
        with transaction.atomic():
            assignment.delete()
            ActivityLog.record(project=self.project, actor=request.user, action="member.revoke_qc1", target=user,
                               before={"team": team.name})
        return Response({"user": user.id, "roles": sorted(user.get_project_roles(self.project))})
