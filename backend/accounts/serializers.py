from django.contrib.auth.password_validation import validate_password
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
    project_name = serializers.CharField(source="project.name", read_only=True)

    class Meta:
        model = RoleAssignment
        fields = ["id", "role", "project", "project_name"]


class CurrentUserSerializer(serializers.ModelSerializer):
    """Thông tin của người đang đăng nhập, dùng cho GET/PATCH /api/auth/me/."""

    full_name = serializers.SerializerMethodField()
    role_assignments = RoleAssignmentSerializer(many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "avatar_url",
            "cvat_username",
            "timezone_name",
            "notify_rework",
            "notify_deadline",
            "notify_request_updates",
            "notify_qc_pass",
            "role_assignments",
        ]

    def get_full_name(self, user):
        return user.get_full_name() or user.username


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Cập nhật hồ sơ & tuỳ chọn thông báo cá nhân (vai trò chỉ đọc theo PQ03)."""

    full_name = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = User
        fields = [
            "first_name",
            "last_name",
            "full_name",
            "email",
            "avatar_url",
            "cvat_username",
            "timezone_name",
            "notify_rework",
            "notify_deadline",
            "notify_request_updates",
            "notify_qc_pass",
        ]

    def validate_avatar_url(self, value):
        if len(value) > 500_000:
            raise serializers.ValidationError("Ảnh đại diện vượt quá kích thước cho phép.")
        return value

    def update(self, instance, validated_data):
        full_name = validated_data.pop("full_name", None)
        if full_name is not None and "first_name" not in validated_data and "last_name" not in validated_data:
            parts = full_name.strip().split(" ", 1)
            instance.first_name = parts[0] if parts and parts[0] else ""
            instance.last_name = parts[1] if len(parts) > 1 else ""
        return super().update(instance, validated_data)


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Mật khẩu hiện tại không đúng.")
        return value

    def validate_new_password(self, value):
        validate_password(value, self.context["request"].user)
        return value
