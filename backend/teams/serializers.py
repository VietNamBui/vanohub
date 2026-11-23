from rest_framework import serializers

from accounts.models import Role, User
from accounts.serializers import UserBriefSerializer

from .models import Team, TeamMember


class TeamMemberSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = TeamMember
        fields = ["id", "user", "capacity", "joined_at"]


class TeamSerializer(serializers.ModelSerializer):
    leader_detail = UserBriefSerializer(source="leader", read_only=True)
    members = TeamMemberSerializer(many=True, read_only=True)

    class Meta:
        model = Team
        fields = ["id", "name", "leader", "leader_detail", "members", "created_at"]

    def validate_leader(self, leader):
        project = self.context["project"]
        if leader and Role.TEAM_LEADER not in leader.get_project_roles(project):
            raise serializers.ValidationError("Leader phải có vai trò Team Leader trong dự án.")
        return leader

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

    def validate_user(self, user):
        if not user.get_project_roles(self.context["project"]):
            raise serializers.ValidationError("Người này chưa có vai trò nào trong dự án.")
        return user


class TransferSerializer(serializers.Serializer):
    user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all())
    to_team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all())

    def validate_to_team(self, team):
        if team.project_id != self.context["project"].id:
            raise serializers.ValidationError("Team đích không thuộc dự án này.")
        return team
