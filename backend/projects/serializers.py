from collections import Counter, defaultdict

from rest_framework import serializers

from accounts.models import Role, User, expand_roles
from accounts.permissions import get_project_capabilities
from accounts.serializers import UserBriefSerializer

from .models import (
    ActivityLog,
    Announcement,
    Batch,
    DataStatus,
    Dataset,
    Delivery,
    EscalationPolicy,
    Guideline,
    Project,
    UserNotification,
)


class ProjectScopedSerializer(serializers.ModelSerializer):
    """Serializer biết dự án hiện tại (view truyền vào context["project"])."""

    @property
    def project(self):
        return self.context["project"]


def _my_roles(project):
    # `my_assignments` được nạp sẵn bằng Prefetch trong ProjectViewSet.get_queryset.
    return sorted(expand_roles(a.role for a in project.my_assignments))


class ProjectListSerializer(serializers.ModelSerializer):
    my_roles = serializers.SerializerMethodField()
    project_managers = serializers.SerializerMethodField()
    job_count = serializers.IntegerField(read_only=True, default=0)
    done_count = serializers.IntegerField(read_only=True, default=0)
    overdue_count = serializers.IntegerField(read_only=True, default=0)
    escalated_count = serializers.IntegerField(read_only=True, default=0)
    progress_percent = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "description",
            "cvat_project_id",
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
        return _my_roles(project)

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
        counts = Counter()
        for roles in self._roles_by_user(project).values():
            counts.update(expand_roles(roles))
        return dict(counts)

    def get_member_total(self, project):
        return len(self._roles_by_user(project))

    def get_my_capabilities(self, project):
        """Frontend dùng để ẩn/hiện menu. Backend vẫn tự kiểm tra lại ở từng API."""
        return sorted(get_project_capabilities(self.context["request"].user, project))


class ProjectWriteSerializer(serializers.ModelSerializer):
    """Project Manager tạo / sửa dự án và gán danh sách PM phụ trách."""

    pm_ids = serializers.ListField(child=serializers.IntegerField(), required=False, write_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "description",
            "cvat_project_id",
            "max_rework_rounds",
            "escalation_policy",
            "annotator_wip_limit",
            "pm_ids",
        ]

    def validate_pm_ids(self, ids):
        unique_ids = list(dict.fromkeys(ids))
        found = set(User.objects.filter(pk__in=unique_ids, is_active=True).values_list("id", flat=True))
        missing = [uid for uid in unique_ids if uid not in found]
        if missing:
            raise serializers.ValidationError(f"Không tìm thấy tài khoản hoạt động với ID: {missing}.")
        return unique_ids


class ProjectSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            "cvat_project_id",
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

    def validate_max_rework_rounds(self, value):
        if value < 1:
            raise serializers.ValidationError("Số vòng rework tối đa phải ≥ 1.")
        return value

    def validate_escalation_policy(self, value):
        if value not in EscalationPolicy.values:
            raise serializers.ValidationError("Chế độ escalation không hợp lệ.")
        return value

    def validate_annotator_wip_limit(self, value):
        if value < 1:
            raise serializers.ValidationError("Giới hạn số job giữ cùng lúc phải ≥ 1.")
        return value


class MemberSerializer(serializers.Serializer):
    """Một người trong dự án + vai trò + team. Dữ liệu dựng sẵn trong view."""

    user = UserBriefSerializer()
    roles = serializers.ListField(child=serializers.CharField())
    team = serializers.DictField(allow_null=True)
    active_jobs = serializers.IntegerField()


class DatasetSerializer(ProjectScopedSerializer):
    batch_count = serializers.IntegerField(read_only=True)
    job_count = serializers.IntegerField(read_only=True)
    done_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Dataset
        fields = ["id", "name", "description", "status", "created_at", "batch_count", "job_count", "done_count"]
        read_only_fields = ["status"]

    def validate_name(self, value):
        qs = Dataset.objects.filter(project=self.project, name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Dự án đã có dataset trùng tên.")
        return value


class BatchSerializer(ProjectScopedSerializer):
    dataset_name = serializers.CharField(source="dataset.name", read_only=True)
    job_count = serializers.IntegerField(read_only=True)
    done_count = serializers.IntegerField(read_only=True)
    qc1_passed_count = serializers.IntegerField(read_only=True, default=0)
    pending_qc2_count = serializers.IntegerField(read_only=True)
    escalated_count = serializers.IntegerField(read_only=True)
    ready_for_qc2_confirm = serializers.SerializerMethodField()
    team_name = serializers.CharField(source="team.name", read_only=True, default=None)
    qc2_confirmed_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = Batch
        fields = [
            "id",
            "dataset",
            "dataset_name",
            "name",
            "status",
            "deadline",
            "team",
            "team_name",
            "cvat_task_id",
            "last_synced_at",
            "last_sync_status",
            "last_sync_error",
            "qc2_confirmed_by",
            "qc2_confirmed_at",
            "created_at",
            "job_count",
            "done_count",
            "qc1_passed_count",
            "pending_qc2_count",
            "escalated_count",
            "ready_for_qc2_confirm",
        ]
        read_only_fields = [
            "status",
            "cvat_task_id",
            "last_synced_at",
            "last_sync_status",
            "last_sync_error",
            "qc2_confirmed_by",
            "qc2_confirmed_at",
        ]

    def get_ready_for_qc2_confirm(self, batch):
        if batch.status != DataStatus.ACTIVE:
            return False
        job_count = getattr(batch, "job_count", 0) or 0
        qc1_passed = getattr(batch, "qc1_passed_count", 0) or 0
        blocking = getattr(batch, "blocking_qc2_count", 0) or 0
        return job_count > 0 and qc1_passed > 0 and blocking == 0

    def validate_dataset(self, dataset):
        if dataset.project_id != self.project.id:
            raise serializers.ValidationError("Dataset không thuộc dự án này.")
        if dataset.status != "active":
            raise serializers.ValidationError("Dataset đã khoá hoặc đã bàn giao.")
        return dataset

    def validate_team(self, team):
        if team and team.project_id != self.project.id:
            raise serializers.ValidationError("Team không thuộc dự án này.")
        return team

    def validate(self, attrs):
        dataset = attrs.get("dataset", getattr(self.instance, "dataset", None))
        name = attrs.get("name", getattr(self.instance, "name", None))
        qs = Batch.objects.filter(dataset=dataset, name=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"name": "Dataset đã có batch trùng tên."})
        return attrs


class DeliverySerializer(ProjectScopedSerializer):
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset_name = serializers.CharField(source="batch.dataset.name", read_only=True)
    delivered_by = UserBriefSerializer(read_only=True)
    job_count = serializers.IntegerField(source="batch.jobs.count", read_only=True)

    class Meta:
        model = Delivery
        fields = [
            "id",
            "batch",
            "batch_name",
            "dataset_name",
            "recipient",
            "output_path",
            "note",
            "client_feedback",
            "delivered_by",
            "delivered_at",
            "job_count",
        ]

    def validate_batch(self, batch):
        if batch.dataset.project_id != self.project.id:
            raise serializers.ValidationError("Batch không thuộc dự án này.")
        return batch

    def validate(self, attrs):
        if self.instance is None:
            recipient = (attrs.get("recipient") or "").strip()
            output_path = (attrs.get("output_path") or "").strip()
            errors = {}
            if not recipient:
                errors["recipient"] = "Vui lòng nhập người nhận bàn giao."
            if not output_path:
                errors["output_path"] = "Vui lòng nhập đường dẫn đầu ra."
            if errors:
                raise serializers.ValidationError(errors)
            attrs["recipient"] = recipient
            attrs["output_path"] = output_path
        return attrs


class ActivityLogSerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)

    class Meta:
        model = ActivityLog
        fields = ["id", "actor", "action", "target_type", "target_id", "target_label",
                  "job", "before", "after", "note", "created_at"]


class AnnouncementSerializer(ProjectScopedSerializer):
    sender = UserBriefSerializer(read_only=True)
    target_team_name = serializers.CharField(source="target_team.name", read_only=True, default=None)

    class Meta:
        model = Announcement
        fields = ["id", "sender", "target_roles", "target_team", "target_team_name", "content", "created_at"]

    def validate_target_roles(self, roles):
        valid = set(Role.values)
        invalid = [r for r in roles if r not in valid]
        if invalid:
            raise serializers.ValidationError(f"Vai trò không hợp lệ: {', '.join(invalid)}")
        return roles

    def validate_target_team(self, team):
        if team and team.project_id != self.project.id:
            raise serializers.ValidationError("Team không thuộc dự án này.")
        return team


class GuidelineSerializer(serializers.ModelSerializer):
    created_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = Guideline
        fields = ["id", "version", "title", "content", "created_by", "created_at"]
        read_only_fields = ["version"]


class UserNotificationSerializer(serializers.ModelSerializer):
    class Meta:
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
