from rest_framework import serializers

from accounts.models import Role, User
from accounts.serializers import UserBriefSerializer
from projects.serializers import ActivityLogSerializer
from quality.models import ReviewError

from .models import AnnotatorRequest, Job


class JobSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    stage = serializers.CharField(read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset_name = serializers.CharField(source="dataset.name", read_only=True)
    annotator = UserBriefSerializer(read_only=True)
    qc1_reviewer = UserBriefSerializer(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    due_state = serializers.CharField(read_only=True)
    hours_remaining = serializers.FloatField(read_only=True)
    max_rework_rounds = serializers.IntegerField(source="project.max_rework_rounds", read_only=True)
    rework_scope_label = serializers.CharField(source="get_rework_scope_display", read_only=True)
    progress_percent = serializers.IntegerField(read_only=True)
    open_error_count = serializers.SerializerMethodField()
    cvat_url = serializers.CharField(read_only=True)
    qc2 = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            "id",
            "name",
            "status",
            "status_label",
            "stage",
            "batch",
            "batch_name",
            "dataset",
            "dataset_name",
            "annotator",
            "qc1_reviewer",
            "qc2",
            "deadline",
            "is_overdue",
            "due_state",
            "hours_remaining",
            "rework_round",
            "max_rework_rounds",
            "rework_scope",
            "rework_scope_label",
            "is_escalated",
            "is_locked",
            "frame_count",
            "object_count",
            "target_object_count",
            "progress_percent",
            "open_error_count",
            "started_at",
            "submitted_at",
            "cvat_job_id",
            "cvat_task_id",
            "cvat_stage",
            "cvat_state",
            "cvat_url",
            "updated_at",
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

    def get_open_error_count(self, job):
        annotated = getattr(job, "_open_error_count", None)
        if annotated is not None:
            return annotated
        if hasattr(job, "_prefetched_objects_cache") and "review_errors" in job._prefetched_objects_cache:
            return len(job._prefetched_objects_cache["review_errors"])
        return job.review_errors.count()


def _open_sample(job):
    """Mẫu QC2 hiện hành của job trong đợt audit đang mở (ưu tiên mẫu PENDING, nếu không có lấy mẫu mới nhất)."""
    samples = getattr(job, "open_samples", None)
    if samples is None:  # chưa prefetch (vd. trang chi tiết) → truy vấn trực tiếp
        samples = list(job.audit_samples.filter(audit__status="in_progress").select_related("auditor"))
    if not samples:
        return None
    pending = [s for s in samples if s.result == "pending"]
    return pending[-1] if pending else samples[-1]


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


class AnnotatorRequestSerializer(serializers.ModelSerializer):
    job_name = serializers.CharField(source="job.name", read_only=True)
    batch_name = serializers.CharField(source="job.batch.name", read_only=True)
    request_type_label = serializers.CharField(source="get_request_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    error_category = serializers.CharField(source="review_error.category.name", read_only=True, default=None)
    error_location = serializers.CharField(source="review_error.location", read_only=True, default="")
    created_by = UserBriefSerializer(read_only=True)
    handler = UserBriefSerializer(read_only=True)

    class Meta:
        model = AnnotatorRequest
        fields = [
            "id",
            "job",
            "job_name",
            "batch_name",
            "review_error",
            "error_category",
            "error_location",
            "request_type",
            "request_type_label",
            "status",
            "status_label",
            "title",
            "reason",
            "progress_note",
            "resolution_note",
            "created_by",
            "handler",
            "handler_role",
            "created_at",
            "updated_at",
            "resolved_at",
        ]
        read_only_fields = fields


class AnnotatorRequestCreateSerializer(serializers.Serializer):
    job = serializers.IntegerField()
    review_error = serializers.IntegerField(required=False, allow_null=True)
    request_type = serializers.ChoiceField(choices=AnnotatorRequest.RequestType.choices)
    title = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    reason = serializers.CharField(min_length=3, max_length=2000)

    def validate(self, attrs):
        project = self.context["project"]
        user = self.context["request"].user
        job = Job.objects.select_related("batch").filter(pk=attrs["job"], project=project).first()
        if not job:
            raise serializers.ValidationError({"job": "Không tìm thấy job trong dự án."})
        if job.annotator_id != user.id:
            raise serializers.ValidationError({"job": "Bạn chỉ có thể gửi yêu cầu trên job được giao cho mình."})
        attrs["job_obj"] = job

        error_id = attrs.get("review_error")
        review_error = None
        if error_id is not None:
            review_error = ReviewError.objects.select_related("category").filter(pk=error_id, job=job).first()
            if not review_error:
                raise serializers.ValidationError({"review_error": "Lỗi không thuộc job này."})
        attrs["review_error_obj"] = review_error

        if not attrs.get("title"):
            if review_error:
                loc = f" {review_error.location}" if review_error.location else ""
                attrs["title"] = f"Không đồng ý lỗi '{review_error.category.name}'{loc}"[:255]
            elif attrs["request_type"] == AnnotatorRequest.RequestType.ERROR_DISPUTE:
                attrs["title"] = f"Phản hồi lỗi QC1 · {job.name}"
            else:
                attrs["title"] = attrs["reason"].strip().splitlines()[0][:255]
        return attrs


class AnnotatorRequestResolveSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=[
            AnnotatorRequest.Status.PENDING_PM,
            AnnotatorRequest.Status.RESOLVED,
            AnnotatorRequest.Status.REJECTED,
        ]
    )
    progress_note = serializers.CharField(required=False, allow_blank=True, default="")
    resolution_note = serializers.CharField(required=False, allow_blank=True, default="")
