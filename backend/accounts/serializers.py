import re
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers
from rest_framework_simplejwt.exceptions import AuthenticationFailed, InvalidToken
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings

from .models import Role, RoleAssignment, User, expand_roles
from .permissions import capabilities_for_roles

if TYPE_CHECKING:

    class ModelMetaBase(serializers.ModelSerializer.Meta):
        model: Any
        fields: Any
else:
    ModelMetaBase = object

_ModelMetaBase = ModelMetaBase

AVATAR_DATA_URI_RE = re.compile(
    r"^data:image/(?:png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/]+={0,2}$",
    re.IGNORECASE,
)


class _StrictStringField(serializers.CharField):
    """Chỉ chấp nhận chuỗi ký tự thực sự (không tự ép int/bool/list/dict thành str)."""

    def to_internal_value(self, data: Any) -> str:
        if not isinstance(data, str):
            raise serializers.ValidationError("Giá trị phải là chuỗi ký tự.")
        return super().to_internal_value(data)


class UserBriefSerializer(serializers.ModelSerializer):
    """Dạng rút gọn của User để nhúng vào Job, Team, Audit..."""

    full_name = serializers.SerializerMethodField()

    class Meta(_ModelMetaBase):
        model = User
        fields = ["id", "username", "full_name"]

    def get_full_name(self, user: User) -> str:
        return user.get_full_name() or user.username


class RoleAssignmentSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="project.name", default=None, read_only=True)

    class Meta(_ModelMetaBase):
        model = RoleAssignment
        fields = ["id", "role", "project", "project_name"]


class CurrentUserSerializer(serializers.ModelSerializer):
    """Thông tin của người đang đăng nhập, dùng cho GET/PATCH /api/auth/me/."""

    full_name = serializers.SerializerMethodField()
    is_pm = serializers.SerializerMethodField()
    cvat_linked = serializers.SerializerMethodField()
    cvat_username = serializers.SerializerMethodField()
    role_assignments = RoleAssignmentSerializer(many=True, read_only=True)
    projects = serializers.SerializerMethodField()

    class Meta(_ModelMetaBase):
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "avatar_url",
            "timezone_name",
            "notify_rework",
            "notify_deadline",
            "notify_request_updates",
            "notify_qc_pass",
            "is_pm",
            "cvat_linked",
            "cvat_username",
            "role_assignments",
            "projects",
        ]

    def get_full_name(self, user: User) -> str:
        return user.get_full_name() or user.username

    def get_is_pm(self, user: User) -> bool:
        if user.is_superuser:
            return True
        return any(a.role == Role.PROJECT_MANAGER for a in user.role_assignments.all())

    def get_cvat_linked(self, user: User) -> bool:
        return getattr(user, "cvat_account", None) is not None

    def get_cvat_username(self, user: User) -> str | None:
        account = getattr(user, "cvat_account", None)
        return account.cvat_username if account is not None else None

    def get_projects(self, user: User) -> list[dict[str, Any]]:
        grouped: dict[int, tuple[Any, set[str]]] = {}
        for assignment in user.role_assignments.all():
            project = assignment.project
            if project is None:
                continue
            entry = grouped.get(project.id)
            if entry is None:
                grouped[project.id] = (project, {assignment.role})
            else:
                entry[1].add(assignment.role)
        if user.is_superuser:
            from projects.models import Project

            for project in Project.objects.all():
                grouped.setdefault(project.id, (project, set()))
        result: list[dict[str, Any]] = []
        for project, direct_roles in grouped.values():
            effective_input = set(direct_roles)
            if user.is_superuser:
                effective_input.add(Role.PROJECT_MANAGER)
            effective_roles = expand_roles(effective_input)
            result.append(
                {
                    "id": project.id,
                    "name": project.name,
                    "cvat_org_slug": project.cvat_org_slug,
                    "roles": sorted(str(role) for role in effective_roles),
                    "direct_roles": sorted(direct_roles),
                    "capabilities": sorted(capabilities_for_roles(effective_roles)),
                }
            )
        return result


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Cập nhật hồ sơ & tuỳ chọn thông báo cá nhân (vai trò, múi giờ Việt Nam và liên kết CVAT là chỉ đọc)."""

    full_name = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta(_ModelMetaBase):
        model = User
        fields = [
            "first_name",
            "last_name",
            "full_name",
            "email",
            "avatar_url",
            "notify_rework",
            "notify_deadline",
            "notify_request_updates",
            "notify_qc_pass",
        ]

    def validate_avatar_url(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if len(value) > 500_000:
            raise serializers.ValidationError("Ảnh đại diện vượt quá kích thước cho phép.")
        if AVATAR_DATA_URI_RE.fullmatch(value):
            return value
        parsed = urlparse(value)
        if (
            parsed.scheme.lower() in ("http", "https")
            and parsed.netloc
            and not any(ch.isspace() or ord(ch) < 32 for ch in value)
        ):
            return value
        raise serializers.ValidationError(
            "URL ảnh đại diện chỉ chấp nhận http(s):// hoặc ảnh base64 (PNG, JPEG, WebP, GIF)."
        )

    def update(self, instance: User, validated_data: dict[str, Any]) -> User:
        full_name = validated_data.pop("full_name", None)
        if full_name is not None and "first_name" not in validated_data and "last_name" not in validated_data:
            parts = full_name.strip().split(" ", 1)
            instance.first_name = parts[0] if parts and parts[0] else ""
            instance.last_name = parts[1] if len(parts) > 1 else ""
        return super().update(instance, validated_data)


class ChangePasswordSerializer(serializers.Serializer):
    """Đổi mật khẩu cho người đang đăng nhập và xoá mật khẩu tạm (nếu có)."""

    current_password = _StrictStringField(
        write_only=True,
        trim_whitespace=False,
        error_messages={"blank": "Vui lòng nhập mật khẩu hiện tại.", "null": "Vui lòng nhập mật khẩu hiện tại."},
    )
    new_password = _StrictStringField(
        write_only=True,
        trim_whitespace=False,
        error_messages={"blank": "Vui lòng nhập mật khẩu mới.", "null": "Vui lòng nhập mật khẩu mới."},
    )

    def validate_current_password(self, value: str) -> str:
        user: User = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Mật khẩu hiện tại không đúng.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        user: User = self.context["request"].user
        current_password: str = attrs["current_password"]
        new_password: str = attrs["new_password"]
        if new_password == current_password:
            raise serializers.ValidationError({"new_password": "Mật khẩu mới phải khác mật khẩu hiện tại."})
        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        return attrs

    def save(self, **kwargs: Any) -> User:
        request_user: User = self.context["request"].user
        data = cast(dict[str, Any], self.validated_data)
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=request_user.pk)
            if not user.check_password(data["current_password"]):
                raise serializers.ValidationError({"current_password": "Mật khẩu hiện tại không đúng."})
            user.set_password(data["new_password"])
            user.initial_password_encrypted = ""
            user.token_version += 1
            user.save(update_fields=["password", "initial_password_encrypted", "token_version"])
        return user


class VanoHubTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Đưa User.token_version vào payload JWT để thu hồi tức thì khi đổi mật khẩu hoặc gỡ vai trò."""

    @classmethod
    def get_token(cls, user: Any) -> Any:
        token = super().get_token(user)
        token["tv"] = user.token_version
        return token


class VanoHubTokenRefreshSerializer(TokenRefreshSerializer):
    """Từ chối làm mới access token nếu token_version không khớp User.token_version hiện tại."""

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        refresh = self.token_class(attrs["refresh"])
        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)
        if user_id is None:
            raise InvalidToken("Token không chứa định danh người dùng.")
        user = User.objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
        if user is None or not api_settings.USER_AUTHENTICATION_RULE(user):
            raise AuthenticationFailed(
                str(self.error_messages["no_active_account"]),
                "no_active_account",
            )
        token_version = refresh.payload.get("tv")
        if token_version is None or token_version != user.token_version:
            raise AuthenticationFailed(
                "Phiên đăng nhập đã hết hiệu lực, vui lòng đăng nhập lại.",
                code="token_revoked",
            )
        return super().validate(attrs)
