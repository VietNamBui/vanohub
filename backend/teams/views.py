from datetime import timedelta

from accounts.datetime_utils import parse_int_param
from accounts.models import Role, RoleAssignment, User, expand_roles
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, STAGE_STATUSES, Job
from projects.models import ActivityLog, Announcement
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .models import Team, TeamMember
from .serializers import MemberInputSerializer, TeamSerializer, TransferSerializer


class TeamViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                  mixins.CreateModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin,
                  viewsets.GenericViewSet):
    serializer_class = TeamSerializer
    required_capabilities = {
        "list": [Cap.MANAGE_TEAM, Cap.VIEW_DASHBOARD],
        "retrieve": [Cap.MANAGE_TEAM, Cap.VIEW_DASHBOARD],
        "workload": [Cap.MANAGE_TEAM, Cap.VIEW_DASHBOARD],
        "*": Cap.MANAGE_TEAM,
    }

    def get_queryset(self):
        roles = Prefetch("user__role_assignments", queryset=RoleAssignment.objects.filter(project=self.project),
                         to_attr="project_roles")
        return Team.objects.filter(project=self.project).prefetch_related(
            Prefetch("members", queryset=TeamMember.objects.select_related("user").prefetch_related(roles))
        )

    def perform_create(self, serializer):
        team = serializer.save(project=self.project)
        ActivityLog.record(project=self.project, actor=self.request.user, action="team.create", target=team)

    def perform_update(self, serializer):
        team = serializer.save()
        ActivityLog.record(project=self.project, actor=self.request.user, action="team.update", target=team,
                           after={"name": team.name})

    @transaction.atomic
    def perform_destroy(self, team):
        """Xoá team: thành viên trở thành "chưa có team" (vai trò, job giữ nguyên).

        Thông báo gửi riêng cho team này bị xoá theo — nếu giữ lại, target_team thành NULL
        và thông báo sẽ hiện cho cả dự án (rò rỉ ngoài nhóm nhận).
        """
        ActivityLog.record(project=self.project, actor=self.request.user, action="team.delete", target=team,
                           before={"name": team.name, "members": list(team.members.values_list("user__username", flat=True))})
        Announcement.objects.filter(target_team=team).delete()
        team.delete()

    def _current_membership(self, user):
        return TeamMember.objects.filter(team__project=self.project, user=user).select_related("team").first()

    @action(detail=True, methods=["post"], url_path="add-member")
    def add_member(self, request, project_id, pk=None):
        team = self.get_object()
        serializer = MemberInputSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user_id = serializer.validated_data["user"].pk
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user_id)
            has_role_here = RoleAssignment.objects.filter(user=user, project=self.project).exists()
            if not has_role_here and (
                user.is_superuser
                or RoleAssignment.objects.filter(user=user).exclude(project=self.project).exists()
            ):
                raise ValidationError({"user": "Người dùng không hợp lệ hoặc không thuộc organization này."})
            existing = self._current_membership(user)
            if existing:
                raise ValidationError(f"{user} đã thuộc team {existing.team}. Dùng chức năng điều chuyển.")
            # Thành viên team chưa có vai trò nào trong dự án → mặc định là Annotator.
            if not has_role_here:
                RoleAssignment.objects.create(
                    user=user, role=Role.ANNOTATOR, project=self.project, granted_by=request.user
                )
            TeamMember.objects.create(team=team, user=user, capacity=serializer.validated_data["capacity"])
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="team.add_member",
                target=team,
                after={"user": user.username},
            )
        return Response(self.get_serializer(self.get_object()).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="remove-member")
    def remove_member(self, request, project_id, pk=None):
        team = self.get_object()
        user_id = parse_int_param(request.data.get("user"), "user")
        deleted, _ = TeamMember.objects.filter(team=team, user_id=user_id).delete()
        if not deleted:
            raise ValidationError("Người này không thuộc team.")
        ActivityLog.record(
            project=self.project,
            actor=request.user,
            action="team.remove_member",
            target=team,
            before={"user": user_id},
        )
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="set-capacity")
    def set_capacity(self, request, project_id, pk=None):
        team = self.get_object()
        serializer = MemberInputSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        updated = TeamMember.objects.filter(team=team, user=serializer.validated_data["user"]).update(
            capacity=serializer.validated_data["capacity"]
        )
        if not updated:
            raise ValidationError("Người này không thuộc team.")
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=False, methods=["post"])
    def transfer(self, request, project_id):
        """Phân roster & luân chuyển: chuyển một người sang team khác trong cùng dự án."""
        serializer = TransferSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user_id = serializer.validated_data["user"].pk
        to_team = serializer.validated_data["to_team"]
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=user_id)
            current = self._current_membership(user)
            if current and current.team_id == to_team.id:
                raise ValidationError("Người này đã ở team đích.")
            if not user.get_project_roles(self.project):
                raise ValidationError("Người này chưa có vai trò nào trong dự án.")
            capacity = current.capacity if current else 5
            if current:
                current.delete()
            TeamMember.objects.create(team=to_team, user=user, capacity=capacity)
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="team.transfer",
                target=to_team,
                before={"team": current.team.name if current else None},
                after={"team": to_team.name, "user": user.username},
            )
        return Response({"user": user.id, "team": to_team.id})

    @action(detail=False)
    def workload(self, request, project_id):
        """Tải công việc từng người: job đang giữ / sức chứa, quá hạn, sắp deadline (24h), escalated."""
        now = timezone.now()
        active_annotator_jobs = Job.objects.filter(
            project=self.project, status__in=ACTIVE_ANNOTATOR_STATUSES, annotator__isnull=False
        )
        stats = {
            row["annotator"]: row
            for row in active_annotator_jobs.values("annotator").annotate(
                holding=Count("id"),
                overdue=Count("id", filter=Q(deadline__lt=now)),
                due_soon=Count("id", filter=Q(deadline__gte=now, deadline__lte=now + timedelta(hours=24))),
                escalated=Count("id", filter=Q(is_escalated=True)),
            )
        }
        qc1_holding = dict(
            Job.objects.filter(
                project=self.project, status__in=STAGE_STATUSES["qc1"], qc1_reviewer__isnull=False
            )
            .values_list("qc1_reviewer")
            .annotate(n=Count("id"))
        )
        roles = Prefetch(
            "user__role_assignments",
            queryset=RoleAssignment.objects.filter(project=self.project),
            to_attr="project_roles",
        )
        members = (
            TeamMember.objects.filter(team__project=self.project)
            .select_related("user", "team")
            .prefetch_related(roles)
        )
        team_param = request.query_params.get("team")
        if team_param is not None and str(team_param).strip() != "":
            team_id = parse_int_param(team_param, "team")
            members = members.filter(team_id=team_id)
        data = []
        for m in members:
            s = stats.get(m.user_id, {})
            direct_roles = {a.role for a in m.user.project_roles}
            data.append({
                "user": UserBriefSerializer(m.user).data,
                "team": {"id": m.team_id, "name": m.team.name},
                "roles": sorted(expand_roles(direct_roles)),
                "capacity": m.capacity,
                "holding": s.get("holding", 0),
                "qc1_holding": qc1_holding.get(m.user_id, 0),
                "overdue": s.get("overdue", 0),
                "due_soon": s.get("due_soon", 0),
                "escalated": s.get("escalated", 0),
            })
        data.sort(key=lambda r: (r["holding"] / max(r["capacity"], 1), r["user"]["username"]))
        return Response(data)
