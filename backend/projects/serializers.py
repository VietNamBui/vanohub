from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, cast

from rest_framework import serializers

from accounts.datetime_utils import PG_INT32_MAX, RFC3339DateTimeField
from accounts.models import Role, User, expand_roles
from accounts.permissions import get_project_capabilities
from accounts.serializers import ModelMetaBase, UserBriefSerializer
from teams.models import Team

from .models import (
    ActivityLog,
    Announcement,
    Batch,
    Dataset,
    DataStatus,
    Delivery,
    EscalationPolicy,
    Guideline,
    Project,
    UserNotification,
)

GRANTABLE_ROLE_CHOICES = [
    (Role.QC2, Role.QC2.label),
    (Role.QC1, Role.QC1.label),
    (Role.ANNOTATOR, Role.ANNOTATOR.label),
]


class ProjectScopedSerializer(serializers.ModelSerializer):
    """Serializer biết organization hiện tại (view truyền vào context["project"])."""

    @property
    def project(self):
        return self.context["project"]


def _my_roles(project):
    # `my_assignments` được nạp sẵn bằng Prefetch trong ProjectViewSet._base_queryset.
    return sorted(expand_roles(a.role for a in project.my_assignments))


class ProjectListSerializer(serializers.ModelSerializer):
    my_roles = serializers.SerializerMethodField()
    project_managers = serializers.SerializerMethodField()
    cvat_synced_at = RFC3339DateTimeField(read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)
    job_count = serializers.IntegerField(read_only=True, default=0)
    done_count = serializers.IntegerField(read_only=True, default=0)
    overdue_count = serializers.IntegerField(read_only=True, default=0)
    escalated_count = serializers.IntegerField(read_only=True, default=0)
    progress_percent = serializers.SerializerMethodField()

    class Meta(ModelMetaBase):
        model = Project
        fields = [
            "id",
            "name",
            "description",
            "cvat_org_id",
            "cvat_org_slug",
            "cvat_synced_at",
            "created_at",
            "my_roles",
            "project_managers",
            "job_count",
            "done_count",
            "overdue_count",
            "escalated_count",
            "progress_percent",
        ]

    def get_my_roles(self, project):
        roles = [a.role for a in project.my_assignments]
        request = self.context.get("request")
        if request and getattr(request.user, "is_superuser", False):
            roles.append(Role.PROJECT_MANAGER)
        return sorted(expand_roles(roles))

    def get_project_managers(self, project):
        pms = getattr(project, "pm_assignments", None)
        if pms is None:
            pms = project.role_assignments.filter(role=Role.PROJECT_MANAGER).select_related("user")
        return [UserBriefSerializer(a.user).data for a in pms]

    def get_progress_percent(self, project):
        total = getattr(project, "job_count", 0) or 0
        done = getattr(project, "done_count", 0) or 0
        return round(done * 100 / total, 1) if total else 0.0


class ProjectDetailSerializer(ProjectListSerializer):
    updated_at = RFC3339DateTimeField(read_only=True)
    member_counts = serializers.SerializerMethodField()
    member_total = serializers.SerializerMethodField()
    my_capabilities = serializers.SerializerMethodField()

    class Meta(ProjectListSerializer.Meta):
        fields = ProjectListSerializer.Meta.fields + [
            "updated_at",
            "member_counts",
            "member_total",
            "my_capabilities",
            "max_rework_rounds",
            "escalation_policy",
            "annotator_wip_limit",
        ]

    def _roles_by_user(self, project):
        roles = defaultdict(set)
        for assignment in project.role_assignments.all():  # đã prefetch
            roles[assignment.user_id].add(assignment.role)
        return roles

    def get_member_counts(self, project):
        """Số người theo từng vai trò có hiệu lực. PM được tính cả vào QC2."""
        counts: Counter[str] = Counter()
        for roles in self._roles_by_user(project).values():
            counts.update(expand_roles(roles))
        return dict(counts)

    def get_member_total(self, project):
        return len(self._roles_by_user(project))

    def get_my_capabilities(self, project):
        """Frontend dùng để ẩn/hiện menu. Backend vẫn tự kiểm tra lại ở từng API."""
        return sorted(get_project_capabilities(self.context["request"].user, project))


class ProjectWriteSerializer(serializers.ModelSerializer):
    """Project Manager tạo / sửa organization và gán danh sách PM phụ trách."""

    max_rework_rounds = serializers.IntegerField(min_value=1, required=False)
    annotator_wip_limit = serializers.IntegerField(min_value=1, max_value=50, required=False)
    pm_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=PG_INT32_MAX),
        required=False,
        allow_empty=False,
        write_only=True,
        error_messages={"empty": "Mỗi organization phải có ít nhất một Project Manager."},
    )

    class Meta(ModelMetaBase):
        model = Project
        fields = [
            "id",
            "name",
            "description",
            "max_rework_rounds",
            "escalation_policy",
            "annotator_wip_limit",
            "pm_ids",
        ]

    def validate_escalation_policy(self, value):
        if value not in EscalationPolicy.values:
            raise serializers.ValidationError("Chế độ escalation không hợp lệ.")
        return value

    def validate_pm_ids(self, ids):
        unique_ids = list(dict.fromkeys(ids))
        if not unique_ids:
            raise serializers.ValidationError("Mỗi organization phải có ít nhất một Project Manager.")
        found = set(User.objects.filter(pk__in=unique_ids, is_active=True).values_list("id", flat=True))
        missing = [uid for uid in unique_ids if uid not in found]
        if missing:
            raise serializers.ValidationError(f"Không tìm thấy tài khoản hoạt động với ID: {missing}.")
        return unique_ids


class ProjectSettingsSerializer(serializers.ModelSerializer):
    cvat_synced_at = RFC3339DateTimeField(read_only=True)
    max_rework_rounds = serializers.IntegerField(min_value=1, required=False)
    annotator_wip_limit = serializers.IntegerField(min_value=1, max_value=50, required=False)
    sampling_rate = serializers.IntegerField(min_value=1, max_value=100, required=False)
    quality_cl_threshold = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        allow_null=True,
        required=False,
    )
    defect_rate_threshold = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        allow_null=True,
        required=False,
    )

    class Meta(ModelMetaBase):
        model = Project
        fields = [
            "cvat_org_id",
            "cvat_org_slug",
            "cvat_synced_at",
            "max_rework_rounds",
            "escalation_policy",
            "annotator_wip_limit",
            "sampling_method",
            "sampling_rate",
            "stratify_by",
            "quality_cl_threshold",
            "defect_rate_threshold",
            "kpi_annotation_target",
            "kpi_qc1_target",
            "kpi_qc2_target",
        ]
        read_only_fields = ["cvat_org_id", "cvat_org_slug", "cvat_synced_at"]

    def validate_max_rework_rounds(self, value):
        if value < 1:
            raise serializers.ValidationError("Số vòng rework tối đa phải ≥ 1.")
        return value

    def validate_escalation_policy(self, value):
        if value not in EscalationPolicy.values:
            raise serializers.ValidationError("Chế độ escalation không hợp lệ.")
        return value

    def validate_annotator_wip_limit(self, value):
        if value < 1 or value > 50:
            raise serializers.ValidationError("Giới hạn số job giữ cùng lúc phải nằm trong khoảng 1..50.")
        return value


class MemberSerializer(serializers.Serializer):
    """Một người trong organization + vai trò + team. Dữ liệu dựng sẵn trong view."""

    user = UserBriefSerializer()
    roles = serializers.ListField(child=serializers.CharField())
    team = serializers.DictField(allow_null=True)
    active_jobs = serializers.IntegerField()


_INVALID_TEAM_MSG = "Team không hợp lệ hoặc không thuộc organization này."
_INVALID_BATCH_MSG = "Task không hợp lệ hoặc không thuộc organization này."


class CreateMemberSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150)
    username = serializers.RegexField(
        r"^[A-Za-z0-9_.-]{3,150}$",
        required=False,
        allow_blank=True,
        error_messages={"invalid": "Chỉ gồm chữ không dấu, số và . _ - (ít nhất 3 ký tự)."},
    )
    email = serializers.EmailField(required=False, allow_blank=True)
    roles = serializers.ListField(
        child=serializers.ChoiceField(choices=GRANTABLE_ROLE_CHOICES),
        allow_empty=False,
        error_messages={"empty": "Chọn ít nhất một vai trò."},
    )
    team = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.none(),
        required=False,
        allow_null=True,
        error_messages={"does_not_exist": _INVALID_TEAM_MSG, "incorrect_type": _INVALID_TEAM_MSG},
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        project = self.context.get("project")
        if project is not None:
            team_field = cast(serializers.PrimaryKeyRelatedField, self.fields["team"])
            team_field.queryset = Team.objects.filter(project=project)

    def validate_full_name(self, value):
        value = " ".join(value.split())
        if not value:
            raise serializers.ValidationError("Nhập họ tên.")
        return value

    def validate_username(self, value):
        if value and User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Tên tài khoản đã tồn tại.")
        return value

    def validate_roles(self, value):
        return sorted(set(value))

    def validate_team(self, team):
        if team and team.project_id != self.context["project"].id:
            raise serializers.ValidationError(_INVALID_TEAM_MSG)
        return team


class DatasetSerializer(ProjectScopedSerializer):
    """"Project" trên giao diện = một CVAT project. Tên đồng bộ từ CVAT; VanoHub chỉ sửa mô tả, khoá / mở khoá."""

    last_synced_at = RFC3339DateTimeField(read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)
    task_count = serializers.IntegerField(read_only=True, default=0)
    job_count = serializers.IntegerField(read_only=True, default=0)
    done_count = serializers.IntegerField(read_only=True, default=0)

    class Meta(ModelMetaBase):
        model = Dataset
        fields = [
            "id",
            "name",
            "description",
            "status",
            "cvat_project_id",
            "last_synced_at",
            "created_at",
            "task_count",
            "job_count",
            "done_count",
        ]
        read_only_fields = ["name", "status", "cvat_project_id", "last_synced_at"]


class BatchSerializer(ProjectScopedSerializer):
    """"Task" trên giao diện = một CVAT task. Tên đồng bộ từ CVAT; PM đặt deadline và team phụ trách."""

    dataset_name = serializers.CharField(source="dataset.name", read_only=True)
    deadline = RFC3339DateTimeField(allow_null=True, required=False)
    last_synced_at = RFC3339DateTimeField(read_only=True)
    qc2_confirmed_at = RFC3339DateTimeField(read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)
    job_count = serializers.IntegerField(read_only=True, default=0)
    done_count = serializers.IntegerField(read_only=True, default=0)
    qc1_passed_count = serializers.IntegerField(read_only=True, default=0)
    blocking_qc2_count = serializers.IntegerField(read_only=True, default=0)
    pending_qc2_count = serializers.IntegerField(read_only=True, default=0)
    escalated_count = serializers.IntegerField(read_only=True, default=0)
    pending_qc2_samples = serializers.IntegerField(read_only=True, default=0)
    locked_jobs = serializers.IntegerField(read_only=True, default=0)
    ready_for_qc2_confirm = serializers.SerializerMethodField()
    team_name = serializers.CharField(source="team.name", read_only=True, default=None)
    qc2_confirmed_by = UserBriefSerializer(read_only=True)

    class Meta(ModelMetaBase):
        model = Batch
        fields = [
            "id",
            "name",
            "dataset",
            "dataset_name",
            "status",
            "deadline",
            "team",
            "team_name",
            "cvat_task_id",
            "source_missing",
            "last_synced_at",
            "last_sync_status",
            "last_sync_error",
            "qc2_confirmed_by",
            "qc2_confirmed_at",
            "created_at",
            "job_count",
            "done_count",
            "qc1_passed_count",
            "blocking_qc2_count",
            "pending_qc2_count",
            "escalated_count",
            "pending_qc2_samples",
            "locked_jobs",
            "ready_for_qc2_confirm",
        ]
        read_only_fields = [
            "name",
            "dataset",
            "cvat_task_id",
            "status",
            "source_missing",
            "last_synced_at",
            "last_sync_status",
            "last_sync_error",
            "qc2_confirmed_by",
            "qc2_confirmed_at",
        ]

    def get_ready_for_qc2_confirm(self, batch):
        if batch.status != DataStatus.ACTIVE or batch.dataset.status != DataStatus.ACTIVE:
            return False
        qc1_passed = getattr(batch, "qc1_passed_count", 0) or 0
        blocking = getattr(batch, "blocking_qc2_count", 0) or 0
        locked = getattr(batch, "locked_jobs", 0) or 0
        return qc1_passed > 0 and blocking == 0 and locked == 0

    def get_fields(self):
        fields = super().get_fields()
        project = self.context.get("project")
        if "team" in fields and isinstance(fields["team"], serializers.PrimaryKeyRelatedField):
            team_field = cast(serializers.PrimaryKeyRelatedField, fields["team"])
            team_field.queryset = Team.objects.filter(project=project) if project is not None else Team.objects.none()
            team_field.error_messages = {
                **team_field.error_messages,
                "does_not_exist": _INVALID_TEAM_MSG,
                "incorrect_type": _INVALID_TEAM_MSG,
            }
        return fields

    def validate_team(self, team):
        if team and team.project_id != self.project.id:
            raise serializers.ValidationError(_INVALID_TEAM_MSG)
        return team


class DeliverySerializer(ProjectScopedSerializer):
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset_name = serializers.CharField(source="batch.dataset.name", read_only=True)
    deadline = RFC3339DateTimeField(source="batch.deadline", read_only=True)
    is_on_time = serializers.SerializerMethodField()
    delivered_by = UserBriefSerializer(read_only=True)
    delivered_at = RFC3339DateTimeField(read_only=True)
    job_count = serializers.IntegerField(source="batch.jobs.count", read_only=True)

    class Meta(ModelMetaBase):
        model = Delivery
        fields = [
            "id",
            "batch",
            "batch_name",
            "dataset_name",
            "deadline",
            "is_on_time",
            "recipient",
            "output_path",
            "note",
            "client_feedback",
            "delivered_by",
            "delivered_at",
            "job_count",
        ]

    def get_fields(self):
        fields = super().get_fields()
        if "batch" in fields:
            if self.instance is not None:
                fields["batch"].read_only = True
            elif isinstance(fields["batch"], serializers.PrimaryKeyRelatedField):
                project = self.context.get("project")
                batch_field = cast(serializers.PrimaryKeyRelatedField, fields["batch"])
                batch_field.queryset = (
                    Batch.objects.filter(project=project) if project is not None else Batch.objects.none()
                )
                batch_field.error_messages = {
                    **batch_field.error_messages,
                    "does_not_exist": _INVALID_BATCH_MSG,
                    "incorrect_type": _INVALID_BATCH_MSG,
                }
        return fields

    def get_is_on_time(self, delivery):
        deadline = delivery.batch.deadline if delivery.batch_id else None
        if deadline is None or delivery.delivered_at is None:
            return None
        return delivery.delivered_at <= deadline

    def validate_batch(self, batch):
        if batch.project_id != self.project.id:
            raise serializers.ValidationError(_INVALID_BATCH_MSG)
        return batch

    def validate(self, attrs):
        errors: dict[str, str] = {}
        if self.instance is None:
            recipient = (attrs.get("recipient") or "").strip()
            output_path = (attrs.get("output_path") or "").strip()
            if not recipient:
                errors["recipient"] = "Vui lòng nhập người nhận bàn giao."
            if not output_path:
                errors["output_path"] = "Vui lòng nhập đường dẫn đầu ra."
            if errors:
                raise serializers.ValidationError(errors)
            attrs["recipient"] = recipient
            attrs["output_path"] = output_path
        else:
            if "recipient" in attrs:
                recipient = (attrs.get("recipient") or "").strip()
                if not recipient:
                    errors["recipient"] = "Người nhận bàn giao không được để trống."
                else:
                    attrs["recipient"] = recipient
            if "output_path" in attrs:
                output_path = (attrs.get("output_path") or "").strip()
                if not output_path:
                    errors["output_path"] = "Đường dẫn đầu ra không được để trống."
                else:
                    attrs["output_path"] = output_path
            if errors:
                raise serializers.ValidationError(errors)
        return attrs


class ActivityLogSerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)

    class Meta(ModelMetaBase):
        model = ActivityLog
        fields = [
            "id",
            "actor",
            "action",
            "target_type",
            "target_id",
            "target_label",
            "job",
            "before",
            "after",
            "note",
            "created_at",
        ]


class AnnouncementSerializer(ProjectScopedSerializer):
    sender = UserBriefSerializer(read_only=True)
    target_team_name = serializers.CharField(source="target_team.name", read_only=True, default=None)
    created_at = RFC3339DateTimeField(read_only=True)

    class Meta(ModelMetaBase):
        model = Announcement
        fields = ["id", "sender", "target_roles", "target_team", "target_team_name", "content", "created_at"]

    def validate_target_roles(self, roles):
        valid = set(Role.values)
        invalid = [r for r in roles if r not in valid]
        if invalid:
            raise serializers.ValidationError(f"Vai trò không hợp lệ: {', '.join(invalid)}")
        return roles

    def get_fields(self):
        fields = super().get_fields()
        project = self.context.get("project")
        if "target_team" in fields and isinstance(fields["target_team"], serializers.PrimaryKeyRelatedField):
            team_field = cast(serializers.PrimaryKeyRelatedField, fields["target_team"])
            team_field.queryset = Team.objects.filter(project=project) if project is not None else Team.objects.none()
            team_field.error_messages = {
                **team_field.error_messages,
                "does_not_exist": _INVALID_TEAM_MSG,
                "incorrect_type": _INVALID_TEAM_MSG,
            }
        return fields

    def validate_target_team(self, team):
        if team and team.project_id != self.project.id:
            raise serializers.ValidationError(_INVALID_TEAM_MSG)
        return team


class GuidelineSerializer(serializers.ModelSerializer):
    created_by = UserBriefSerializer(read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)

    class Meta(ModelMetaBase):
        model = Guideline
        fields = ["id", "version", "title", "content", "created_by", "created_at"]
        read_only_fields = ["version"]


class UserNotificationSerializer(serializers.ModelSerializer):
    created_at = RFC3339DateTimeField(read_only=True)

    class Meta(ModelMetaBase):
        model = UserNotification
        fields = [
            "id",
            "category",
            "title",
            "body",
            "job",
            "action_url",
            "is_read",
            "is_pinned_pending",
            "created_at",
        ]
        read_only_fields = fields


class AddMemberRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=GRANTABLE_ROLE_CHOICES)


class BatchNoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class SyncCvatSerializer(serializers.Serializer):
    count_objects = serializers.BooleanField(required=False, default=False)
