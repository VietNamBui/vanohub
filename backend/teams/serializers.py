from rest_framework import serializers

from accounts.models import Role, User, expand_roles
from accounts.serializers import UserBriefSerializer

from .models import Team, TeamMember


class TeamMemberSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)
    # Vai trò hiệu lực của người này trong dự án của team — trả kèm để trang team không phải ghép với API khác.
    roles = serializers.SerializerMethodField()
    direct_roles = serializers.SerializerMethodField()

    class Meta:
        model = TeamMember
        fields = ["id", "user", "roles", "direct_roles", "capacity", "joined_at"]

    def _direct(self, member):
        assignments = getattr(member.user, "project_roles", None)  # đã prefetch trong TeamViewSet
        if assignments is None:
            assignments = member.user.role_assignments.filter(project_id=member.team.project_id)
        return {a.role for a in assignments}

    def get_roles(self, member):
        return sorted(expand_roles(self._direct(member)))

    def get_direct_roles(self, member):
        return sorted(self._direct(member))


class TeamSerializer(serializers.ModelSerializer):
    members = TeamMemberSerializer(many=True, read_only=True)

    class Meta:
        model = Team
        fields = ["id", "name", "members", "created_at"]

    def validate_name(self, name):
        qs = Team.objects.filter(project=self.context["project"], name=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Dự án đã có team trùng tên.")
        return name


class MemberInputSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    capacity = serializers.IntegerField(min_value=1, max_value=100, required=False, default=5)

    # Người chưa có vai trò trong dự án vẫn thêm được: view tự gán vai trò mặc định Annotator.


class TransferSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    to_team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all())

    def validate_to_team(self, team):
        if team.project_id != self.context["project"].id:
            raise serializers.ValidationError("Team đích không thuộc dự án này.")
        return team
