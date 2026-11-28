from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from django.db.models import Q
from rest_framework import serializers

from accounts.datetime_utils import PG_INT32_MAX, parse_int_param
from accounts.models import User, expand_roles
from accounts.serializers import UserBriefSerializer

from .models import Team, TeamMember

if TYPE_CHECKING:

    class _ModelMetaBase(serializers.ModelSerializer.Meta):
        model: Any
else:
    _ModelMetaBase = object

_INVALID_MEMBER_MSG = "Người dùng không hợp lệ hoặc không thuộc organization này."
_INVALID_TO_TEAM_MSG = "Team đích không hợp lệ hoặc không thuộc dự án này."


class TeamMemberSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)
    # Vai trò hiệu lực của người này trong dự án của team — trả kèm để trang team không phải ghép với API khác.
    roles = serializers.SerializerMethodField()
    direct_roles = serializers.SerializerMethodField()

    class Meta(_ModelMetaBase):
        model = TeamMember
        fields = ["id", "user", "roles", "direct_roles", "capacity", "joined_at"]

    def _direct(self, member: TeamMember) -> set[str]:
        assignments = getattr(member.user, "project_roles", None)  # đã prefetch trong TeamViewSet
        if assignments is None:
            assignments = member.user.role_assignments.filter(project_id=member.team.project_id)
        return {a.role for a in assignments}

    def get_roles(self, member: TeamMember) -> list[str]:
        return sorted(str(role) for role in expand_roles(self._direct(member)))

    def get_direct_roles(self, member: TeamMember) -> list[str]:
        return sorted(self._direct(member))


class TeamSerializer(serializers.ModelSerializer):
    members = TeamMemberSerializer(many=True, read_only=True)

    class Meta(_ModelMetaBase):
        model = Team
        fields = ["id", "name", "members", "created_at"]

    def validate_name(self, name: str) -> str:
        qs = Team.objects.filter(project=self.context["project"], name=name)
        if self.instance is not None:
            qs = qs.exclude(pk=cast(Team, self.instance).pk)
        if qs.exists():
            raise serializers.ValidationError("Dự án đã có team trùng tên.")
        return name


class MemberInputSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(),
        error_messages={
            "does_not_exist": _INVALID_MEMBER_MSG,
            "incorrect_type": _INVALID_MEMBER_MSG,
        },
    )
    capacity = serializers.IntegerField(min_value=1, max_value=100, required=False, default=5)

    # Người chưa có vai trò ở bất kỳ organization nào vẫn thêm được (mặc định Annotator);
    # người thuộc organization khác hoặc superuser không thuộc org này bị chặn.
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        project = self.context.get("project")
        if project is not None:
            user_field = cast(serializers.PrimaryKeyRelatedField, self.fields["user"])
            user_field.queryset = User.objects.filter(
                Q(role_assignments__project=project) | Q(role_assignments__isnull=True, is_superuser=False)
            ).distinct()


class RemoveMemberSerializer(serializers.Serializer):
    user = serializers.IntegerField(min_value=1, max_value=PG_INT32_MAX)

    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, Mapping):
            raise serializers.ValidationError("Dữ liệu đầu vào phải là JSON object.")
        user_id = parse_int_param(data.get("user"), "user")
        return {"user": user_id}


class TransferSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.none(),
        error_messages={
            "does_not_exist": _INVALID_MEMBER_MSG,
            "incorrect_type": _INVALID_MEMBER_MSG,
        },
    )
    to_team = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.none(),
        error_messages={
            "does_not_exist": _INVALID_TO_TEAM_MSG,
            "incorrect_type": _INVALID_TO_TEAM_MSG,
        },
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        project = self.context.get("project")
        if project is not None:
            user_field = cast(serializers.PrimaryKeyRelatedField, self.fields["user"])
            user_field.queryset = User.objects.filter(role_assignments__project=project).distinct()
            to_team_field = cast(serializers.PrimaryKeyRelatedField, self.fields["to_team"])
            to_team_field.queryset = Team.objects.filter(project=project)

    def validate_to_team(self, team: Team) -> Team:
        if team.project_id != self.context["project"].id:
            raise serializers.ValidationError(_INVALID_TO_TEAM_MSG)
        return team
