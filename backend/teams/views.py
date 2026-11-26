from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from accounts.validation import validated_dict
from jobs.models import ACTIVE_ANNOTATOR_STATUSES, Job, JobStatus
from projects.models import ActivityLog, Announcement

from .models import Team, TeamMember
from .serializers import MemberInputSerializer, RemoveMemberSerializer, TeamSerializer, TransferSerializer


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

    def get_queryset(self) -> Any:
        return Team.objects.filter(project=self.project).prefetch_related(
            Prefetch("members", queryset=TeamMember.objects.select_related("user"))
        )

    def perform_create(self, serializer):
        team = serializer.save(project=self.project)
        ActivityLog.record(project=self.project, actor=self.request.user, action="team.create", target=team)

    def perform_update(self, serializer):
        team = serializer.save()
        ActivityLog.record(project=self.project, actor=self.request.user, action="team.update", target=team,
                           after={"name": team.name})

    @transaction.atomic
    def perform_destroy(self, instance):
        """Xoá team: thành viên trở thành "chưa có team" (vai trò, job giữ nguyên).

        Thông báo gửi riêng cho team này bị xoá theo — nếu giữ lại, target_team thành NULL
        và thông báo sẽ hiện cho cả dự án (rò rỉ ngoài nhóm nhận).
        """
        team = instance
        ActivityLog.record(project=self.project, actor=self.request.user, action="team.delete", target=team,
                           before={"name": team.name, "members": list(team.members.values_list("user__username", flat=True))})
        Announcement.objects.filter(target_team=team).delete()
        team.delete()

    def _current_membership(self, user):
        return TeamMember.objects.filter(team__project=self.project, user=user).select_related("team").first()

    @action(detail=True, methods=["post"], url_path="add-member")
    def add_member(self, request, project_id, pk=None):
        team = self.get_object()
        data = validated_dict(MemberInputSerializer(data=request.data, context=self.get_serializer_context()))
        user = data["user"]
        existing = self._current_membership(user)
        if existing:
            raise ValidationError(f"{user} đã thuộc team {existing.team}. Dùng chức năng điều chuyển.")
        TeamMember.objects.create(team=team, user=user, capacity=data["capacity"])
        ActivityLog.record(project=self.project, actor=request.user, action="team.add_member", target=team,
                           after={"user": user.username})
        return Response(self.get_serializer(self.get_object()).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="remove-member")
    def remove_member(self, request, project_id, pk=None):
        team = self.get_object()
        data = validated_dict(RemoveMemberSerializer(data=request.data))
        user_id = data["user"]
        deleted, _ = TeamMember.objects.filter(team=team, user_id=user_id).delete()
        if not deleted:
            raise ValidationError("Người này không thuộc team.")
        ActivityLog.record(project=self.project, actor=request.user, action="team.remove_member", target=team,
                           before={"user": user_id})
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=True, methods=["post"], url_path="set-capacity")
    def set_capacity(self, request, project_id, pk=None):
        team = self.get_object()
        data = validated_dict(MemberInputSerializer(data=request.data, context=self.get_serializer_context()))
        updated = TeamMember.objects.filter(team=team, user=data["user"]).update(
            capacity=data["capacity"]
        )
        if not updated:
            raise ValidationError("Người này không thuộc team.")
        return Response(self.get_serializer(self.get_object()).data)

    @action(detail=False, methods=["post"])
    def transfer(self, request, project_id):
        """Phân roster & luân chuyển: chuyển một người sang team khác trong cùng dự án."""
        data = validated_dict(TransferSerializer(data=request.data, context=self.get_serializer_context()))
        user, to_team = data["user"], data["to_team"]
        with transaction.atomic():
            current = self._current_membership(user)
            if current and current.team_id == to_team.id:
                raise ValidationError("Người này đã ở team đích.")
            if not user.get_project_roles(self.project):
                raise ValidationError("Người này chưa có vai trò nào trong dự án.")
            capacity = current.capacity if current else 5
            if current:
                current.delete()
            TeamMember.objects.create(team=to_team, user=user, capacity=capacity)
            ActivityLog.record(project=self.project, actor=request.user, action="team.transfer", target=to_team,
                               before={"team": current.team.name if current else None},
                               after={"team": to_team.name, "user": user.username})
        return Response({"user": user.id, "team": to_team.id})

    @action(detail=False)
    def workload(self, request, project_id):
        """Tải công việc từng người (TD10): job đang giữ đúng vai trò, sắp hạn (24h), quá hạn, escalated."""
        now = timezone.now()
        cutoff = now + timedelta(hours=24)
        active_anno_jobs = Job.objects.filter(project=self.project, status__in=ACTIVE_ANNOTATOR_STATUSES)
        stats = {
            row["annotator"]: row
            for row in active_anno_jobs.filter(annotator__isnull=False).values("annotator").annotate(
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
        members = TeamMember.objects.filter(team__project=self.project).select_related("user", "team")
        team_id = request.query_params.get("team")
        if team_id:
            members = members.filter(team_id=team_id)
        data = []
        for m in members:
            s = stats.get(m.user_id, {})
            data.append({
                "user": UserBriefSerializer(m.user).data,
                "team": {"id": m.team_id, "name": m.team.name},
                "roles": sorted(m.user.get_project_roles(self.project)),
                "capacity": m.capacity,
                "holding": s.get("holding", 0),
                "qc1_holding": qc1_holding.get(m.user_id, 0),
                "due_soon": s.get("due_soon", 0),
                "overdue": s.get("overdue", 0),
                "escalated": s.get("escalated", 0),
            })
        data.sort(key=lambda r: (r["holding"] / max(r["capacity"], 1), r["user"]["username"]))
        return Response(data)
