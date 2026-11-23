from rest_framework import serializers

from accounts.models import Role, User
from accounts.serializers import UserBriefSerializer
from projects.serializers import ActivityLogSerializer

from .models import Job


class JobSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    stage = serializers.CharField(read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset = serializers.IntegerField(source="batch.dataset_id", read_only=True)
    dataset_name = serializers.CharField(source="batch.dataset.name", read_only=True)
    annotator = UserBriefSerializer(read_only=True)
    qc1_reviewer = UserBriefSerializer(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    max_rework_rounds = serializers.IntegerField(source="project.max_rework_rounds", read_only=True)
    cvat_url = serializers.CharField(read_only=True)
    qc2 = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            "id", "name", "status", "status_label", "stage", "batch", "batch_name", "dataset", "dataset_name",
            "annotator", "qc1_reviewer", "qc2", "deadline", "is_overdue", "rework_round", "max_rework_rounds",
            "is_escalated", "is_locked", "frame_count", "object_count",
            "cvat_job_id", "cvat_task_id", "cvat_stage", "cvat_state", "cvat_url", "updated_at",
        ]
        read_only_fields = fields

    def get_qc2(self, job):
        """QC2 gắn với mẫu audit, không gắn cứng vào job: chỉ job được lấy mẫu trong audit đang mở mới có auditor."""
        sample = _open_sample(job)
        if sample is None:
            return None
        return {
            "sample_id": sample.id,
            "audit_id": sample.audit_id,
            "result": sample.result,
            "auditor": UserBriefSerializer(sample.auditor).data if sample.auditor else None,
        }


def _open_sample(job):
    """Mẫu QC2 của job trong đợt audit đang mở (None nếu job không được lấy mẫu)."""
    samples = getattr(job, "open_samples", None)
    if samples is None:  # chưa prefetch (vd. trang chi tiết) → truy vấn trực tiếp
        samples = list(job.audit_samples.filter(audit__status="in_progress").select_related("auditor"))
    return samples[0] if samples else None


class ReviewErrorBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    stage = serializers.CharField()
    rework_round = serializers.IntegerField()
    category = serializers.CharField(source="category.name")
    severity = serializers.CharField()
    location = serializers.CharField()
    description = serializers.CharField()
    reported_by = UserBriefSerializer()
    created_at = serializers.DateTimeField()


class JobDetailSerializer(JobSerializer):
    timeline = serializers.SerializerMethodField()
    errors = serializers.SerializerMethodField()

    class Meta(JobSerializer.Meta):
        fields = JobSerializer.Meta.fields + ["timeline", "errors"]
        read_only_fields = fields

    def get_timeline(self, job):
        return ActivityLogSerializer(job.events.select_related("actor").order_by("created_at", "id"), many=True).data

    def get_errors(self, job):
        errors = job.review_errors.select_related("category", "reported_by")
        return ReviewErrorBriefSerializer(errors, many=True).data


def _member_with_role(project, user_id, role, label):
    if user_id is None:
        return None
    user = User.objects.filter(pk=user_id).first()
    if not user or role not in user.get_project_roles(project):
        raise serializers.ValidationError(f"{label} phải là người có vai trò {Role(role).label} trong dự án.")
    return user


class AssignSerializer(serializers.Serializer):
    """Giao lại job. Gửi field nào thì đổi field đó; gửi null để bỏ người phụ trách."""

    annotator = serializers.IntegerField(allow_null=True, required=False)
    qc1_reviewer = serializers.IntegerField(allow_null=True, required=False)
    note = serializers.CharField(allow_blank=True, required=False, default="")

    def validate(self, attrs):
        project = self.context["project"]
        if "annotator" in attrs:
            attrs["annotator"] = _member_with_role(project, attrs["annotator"], Role.ANNOTATOR, "Annotator")
        if "qc1_reviewer" in attrs:
            attrs["qc1_reviewer"] = _member_with_role(project, attrs["qc1_reviewer"], Role.QC1, "Người QC1")
        if "annotator" not in attrs and "qc1_reviewer" not in attrs:
            raise serializers.ValidationError("Chọn annotator hoặc người QC1.")
        return attrs


class DeadlineSerializer(serializers.Serializer):
    deadline = serializers.DateTimeField(allow_null=True)
    note = serializers.CharField(allow_blank=True, required=False, default="")


class BulkSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(), min_length=1, max_length=500)


class AnnotatorStartSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=True, required=False, default="")


class AnnotatorSubmitSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=True, required=False, default="")
    object_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)
