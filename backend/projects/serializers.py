from collections import Counter, defaultdict

from rest_framework import serializers

from accounts.models import Role, expand_roles
from accounts.permissions import get_project_capabilities
from accounts.serializers import UserBriefSerializer

from .models import ActivityLog, Announcement, Batch, Dataset, Delivery, Guideline, Project


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

    class Meta:
        model = Project
        fields = ["id", "name", "description", "created_at", "my_roles"]

    def get_my_roles(self, project):
        return _my_roles(project)


class ProjectDetailSerializer(ProjectListSerializer):
    member_counts = serializers.SerializerMethodField()
    member_total = serializers.SerializerMethodField()
    my_capabilities = serializers.SerializerMethodField()

    class Meta(ProjectListSerializer.Meta):
        fields = ProjectListSerializer.Meta.fields + [
            "updated_at", "member_counts", "member_total", "my_capabilities", "cvat_org_id", "cvat_org_slug",
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


class ProjectSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = [
            "max_rework_rounds", "sampling_rate",
            "quality_cl_threshold", "defect_rate_threshold",
            "kpi_annotation_target", "kpi_qc1_target", "kpi_qc2_target",
        ]

    def validate_max_rework_rounds(self, value):
        if value < 1:
            raise serializers.ValidationError("Số vòng rework tối đa phải ≥ 1.")
        return value


class MemberSerializer(serializers.Serializer):
    """Một người trong dự án + vai trò + team. Dữ liệu dựng sẵn trong view."""

    user = UserBriefSerializer()
    roles = serializers.ListField(child=serializers.CharField())
    team = serializers.DictField(allow_null=True)
    active_jobs = serializers.IntegerField()


class DatasetSerializer(ProjectScopedSerializer):
    """"Project" trên giao diện = một CVAT project. Tên đồng bộ từ CVAT; VanoHub chỉ sửa mô tả, khoá / mở khoá."""

    task_count = serializers.IntegerField(read_only=True)
    job_count = serializers.IntegerField(read_only=True)
    done_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Dataset
        fields = ["id", "name", "description", "status", "cvat_project_id", "last_synced_at", "created_at",
                  "task_count", "job_count", "done_count"]
        read_only_fields = ["name", "status", "cvat_project_id", "last_synced_at"]


class BatchSerializer(ProjectScopedSerializer):
    """"Task" trên giao diện = một CVAT task. Tên đồng bộ từ CVAT; PM đặt deadline và team phụ trách."""

    dataset_name = serializers.CharField(source="dataset.name", read_only=True)
    job_count = serializers.IntegerField(read_only=True)
    done_count = serializers.IntegerField(read_only=True)
    pending_qc2_count = serializers.IntegerField(read_only=True)
    escalated_count = serializers.IntegerField(read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True, default=None)

    class Meta:
        model = Batch
        fields = [
            "id", "name", "dataset", "dataset_name", "cvat_task_id", "status", "deadline", "team", "team_name",
            "last_synced_at", "created_at", "job_count", "done_count", "pending_qc2_count", "escalated_count",
        ]
        read_only_fields = ["name", "dataset", "cvat_task_id", "status", "last_synced_at"]

    def validate_team(self, team):
        if team and team.project_id != self.project.id:
            raise serializers.ValidationError("Team không thuộc organization này.")
        return team


class DeliverySerializer(ProjectScopedSerializer):
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    delivered_by = UserBriefSerializer(read_only=True)
    job_count = serializers.IntegerField(source="batch.jobs.count", read_only=True)

    class Meta:
        model = Delivery
        fields = ["id", "batch", "batch_name", "note", "client_feedback",
                  "delivered_by", "delivered_at", "job_count"]

    def validate_batch(self, batch):
        if batch.project_id != self.project.id:
            raise serializers.ValidationError("Batch không thuộc dự án này.")
        return batch


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
