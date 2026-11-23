from rest_framework import serializers

from .models import RoleAssignment, User


class UserBriefSerializer(serializers.ModelSerializer):
    """Dạng rút gọn của User để nhúng vào Job, Team, Audit..."""

    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "full_name"]

    def get_full_name(self, user):
        return user.get_full_name() or user.username


class RoleAssignmentSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", default=None, read_only=True)

    class Meta:
        model = RoleAssignment
        fields = ["id", "role", "project", "project_name"]


class CurrentUserSerializer(serializers.ModelSerializer):
    """Thông tin của người đang đăng nhập, dùng cho GET /api/auth/me/."""

    is_director = serializers.SerializerMethodField()
    role_assignments = RoleAssignmentSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "first_name", "last_name", "email", "is_director", "role_assignments"]

    def get_is_director(self, user):
        return user.is_director()
