from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action as drf_action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from accounts.datetime_utils import parse_int_param
from accounts.models import Role, RoleAssignment, User, expand_roles
from accounts.permissions import Cap, HasProjectCapability, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from accounts.validation import validated_dict
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, Job, JobStatus
from projects.models import ActivityLog, Announcement

from .models import Team, TeamMember
from .serializers import (
    _INVALID_MEMBER_MSG,
    MemberInputSerializer,
    RemoveMemberSerializer,
    TeamSerializer,
    TransferSerializer,
)


class TeamViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TeamSerializer
    permission_classes: Any = [HasProjectCapability]
    action: Any
    required_capabilities = {
        "list": [Cap.MANAGE_TEAM, Cap.VIEW_DASHBOARD],
        "retrieve": [Cap.MANAGE_TEAM, Cap.VIEW_DASHBOARD],
        "workload": [Cap.MANAGE_TEAM, Cap.VIEW_DASHBOARD],
        "*": Cap.MANAGE_TEAM,
    }

    def get_queryset(self) -> Any:
        roles = Prefetch(
            "user__role_assignments",
            queryset=RoleAssignment.objects.filter(project=self.project),
            to_attr="project_roles",
        )
        return Team.objects.filter(project=self.project).prefetch_related(
            Prefetch("members", queryset=TeamMember.objects.select_related("user").prefetch_related(roles))
        )

    def perform_create(self, serializer: Any) -> None:
        try:
            with transaction.atomic():
                team = serializer.save(project=self.project)
                ActivityLog.record(project=self.project, actor=self.request.user, action="team.create", target=team)
        except IntegrityError as exc:
            raise ValidationError({"name": "Dự án đã có team trùng tên."}) from exc

    def perform_update(self, serializer: Any) -> None:
        instance = serializer.instance
        try:
            with transaction.atomic():
                locked_team = Team.objects.select_for_update().filter(pk=instance.pk, project=self.project).first()
                if locked_team is None:
                    raise NotFound("Không tìm thấy team trong organization.")
                serializer.instance = locked_team
                team = serializer.save()
                ActivityLog.record(
                    project=self.project,
                    actor=self.request.user,
                    action="team.update",
                    target=team,
                    after={"name": team.name},
                )
        except IntegrityError as exc:
            raise ValidationError({"name": "Dự án đã có team trùng tên."}) from exc

    @transaction.atomic
    def perform_destroy(self, instance: Any) -> None:
        """Xoá team: thành viên trở thành "chưa có team" (vai trò, job giữ nguyên).

        Thông báo gửi riêng cho team này bị xoá theo — nếu giữ lại, target_team thành NULL
        và thông báo sẽ hiện cho cả dự án (rò rỉ ngoài nhóm nhận).
        """
        team = Team.objects.select_for_update().filter(pk=instance.pk, project=self.project).first()
        if team is None:
            raise NotFound("Không tìm thấy team trong organization.")
        ActivityLog.record(
            project=self.project,
            actor=self.request.user,
            action="team.delete",
            target=team,
            before={"name": team.name, "members": list(team.members.values_list("user__username", flat=True))},
        )
        Announcement.objects.filter(target_team=team).delete()
        team.delete()

    def _current_membership(self, user: User) -> TeamMember | None:
        return TeamMember.objects.filter(team__project=self.project, user=user).select_related("team").first()

    @drf_action(detail=True, methods=["post"], url_path="add-member")
    def add_member(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        team_obj = self.get_object()
        data = validated_dict(MemberInputSerializer(data=request.data, context=self.get_serializer_context()))
        user_id = data["user"].pk
        capacity: int = data["capacity"]
        try:
            with transaction.atomic():
                team = Team.objects.select_for_update().filter(pk=team_obj.pk, project=self.project).first()
                if team is None:
                    raise NotFound("Không tìm thấy team trong organization.")
                user = User.objects.select_for_update().filter(pk=user_id).first()
                if user is None:
                    raise ValidationError({"user": _INVALID_MEMBER_MSG})
                has_role_here = RoleAssignment.objects.filter(user=user, project=self.project).exists()
                if not has_role_here and (
                    user.is_superuser
                    or RoleAssignment.objects.filter(user=user).exclude(project=self.project).exists()
                ):
                    raise ValidationError({"user": _INVALID_MEMBER_MSG})
                existing = self._current_membership(user)
                if existing:
                    raise ValidationError(f"{user} đã thuộc team {existing.team}. Dùng chức năng điều chuyển.")
                # Thành viên team chưa có vai trò nào trong dự án → mặc định là Annotator.
                if not has_role_here:
                    RoleAssignment.objects.create(
                        user=user, role=Role.ANNOTATOR, project=self.project, granted_by=request.user
                    )
                TeamMember.objects.create(team=team, user=user, capacity=capacity)
                ActivityLog.record(
                    project=self.project,
                    actor=request.user,
                    action="team.add_member",
                    target=team,
                    after={"user": user.username},
                )
        except IntegrityError as exc:
            raise ValidationError("Thành viên đã thuộc team hoặc dữ liệu xung đột.") from exc
        return Response(self.get_serializer(self.get_object()).data, status=status.HTTP_201_CREATED)

    @drf_action(detail=True, methods=["post"], url_path="remove-member")
    def remove_member(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        team_obj = self.get_object()
        data = validated_dict(RemoveMemberSerializer(data=request.data))
        user_id: int = data["user"]
        with transaction.atomic():
            team = Team.objects.select_for_update().filter(pk=team_obj.pk, project=self.project).first()
            if team is None:
                raise NotFound("Không tìm thấy team trong organization.")
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

    @drf_action(detail=True, methods=["post"], url_path="set-capacity")
    def set_capacity(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        team_obj = self.get_object()
        data = validated_dict(MemberInputSerializer(data=request.data, context=self.get_serializer_context()))
        user: User = data["user"]
        capacity: int = data["capacity"]
        with transaction.atomic():
            team = Team.objects.select_for_update().filter(pk=team_obj.pk, project=self.project).first()
            if team is None:
                raise NotFound("Không tìm thấy team trong organization.")
            member = TeamMember.objects.select_for_update().filter(team=team, user=user).first()
            if member is None:
                raise ValidationError("Người này không thuộc team.")
            before_capacity = member.capacity
            member.capacity = capacity
            member.save(update_fields=["capacity"])
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="team.set_capacity",
                target=team,
                before={"user": user.username, "capacity": before_capacity},
                after={"user": user.username, "capacity": capacity},
            )
        return Response(self.get_serializer(self.get_object()).data)

    @drf_action(detail=False, methods=["post"])
    def transfer(self, request: Any, project_id: Any) -> Response:
        """Phân roster & luân chuyển: chuyển một người sang team khác trong cùng dự án."""
        data = validated_dict(TransferSerializer(data=request.data, context=self.get_serializer_context()))
        user_id = data["user"].pk
        to_team_obj: Team = data["to_team"]
        try:
            with transaction.atomic():
                to_team = Team.objects.select_for_update().filter(pk=to_team_obj.pk, project=self.project).first()
                if to_team is None:
                    raise ValidationError({"to_team": "Team đích không thuộc dự án này."})
                user = User.objects.select_for_update().filter(pk=user_id).first()
                if user is None:
                    raise ValidationError({"user": _INVALID_MEMBER_MSG})
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
        except IntegrityError as exc:
            raise ValidationError("Không thể điều chuyển thành viên do xung đột dữ liệu.") from exc
        return Response({"user": user.id, "team": to_team.id})

    @drf_action(detail=False)
    def workload(self, request: Any, project_id: Any) -> Response:
        """Tải công việc từng người (TD10): job đang giữ đúng vai trò, quá hạn, sắp hạn (24h), escalated."""
        now = timezone.now()
        cutoff = now + timedelta(hours=24)
        active_annotator_jobs = Job.objects.filter(
            project=self.project,
            status__in=ACTIVE_ANNOTATOR_STATUSES,
            annotator__isnull=False,
        )
        stats = {
            row["annotator"]: row
            for row in active_annotator_jobs.values("annotator").annotate(
                holding=Count("id"),
                overdue=Count("id", filter=Q(deadline__lt=now)),
                due_soon=Count("id", filter=Q(deadline__gte=now, deadline__lte=cutoff)),
                escalated=Count("id", filter=Q(is_escalated=True)),
            )
        }
        qc1_holding = dict(
            Job.objects.filter(
                project=self.project,
                status__in=[JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING],
                qc1_reviewer__isnull=False,
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
            direct_roles = {a.role for a in getattr(m.user, "project_roles", ())}
            data.append(
                {
                    "user": UserBriefSerializer(m.user).data,
                    "team": {"id": m.team_id, "name": m.team.name},
                    "roles": sorted(str(role) for role in expand_roles(direct_roles)),
                    "capacity": m.capacity,
                    "holding": s.get("holding", 0),
                    "qc1_holding": qc1_holding.get(m.user_id, 0),
                    "overdue": s.get("overdue", 0),
                    "due_soon": s.get("due_soon", 0),
                    "escalated": s.get("escalated", 0),
                }
            )
        data.sort(key=lambda r: (r["holding"] / max(r["capacity"], 1), r["user"]["username"]))
        return Response(data)
