from typing import Any

from rest_framework import serializers

from accounts.datetime_utils import PG_INT32_MAX, RFC3339DateTimeField
from accounts.serializers import ModelMetaBase, UserBriefSerializer
from jobs.models import Job, ReworkScope

from .models import Audit, AuditSample, ErrorCategory, ErrorVerdict, JobIssue, ReviewError, Severity


class ErrorCategorySerializer(serializers.ModelSerializer):
    class Meta(ModelMetaBase):
        model = ErrorCategory
        fields = ["id", "code", "primary_category", "name", "description", "severity", "applies_to", "is_active"]

    def validate_code(self, code: str) -> str:
        cleaned = code.strip()
        if cleaned:
            qs = ErrorCategory.objects.filter(project=self.context["project"], code=cleaned)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("Danh mục đã có loại lỗi trùng mã.")
        return cleaned

    def validate_name(self, name: str) -> str:
        qs = ErrorCategory.objects.filter(project=self.context["project"], name=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Danh mục đã có loại lỗi trùng tên.")
        return name


class ReviewErrorSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    reported_by = UserBriefSerializer(read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)

    class Meta(ModelMetaBase):
        model = ReviewError
        fields = [
            "id",
            "stage",
            "rework_round",
            "job_issue",
            "cvat_issue_id",
            "category",
            "category_name",
            "severity",
            "verdict",
            "frame_number",
            "cvat_object_id",
            "is_missing_object",
            "location",
            "description",
            "is_voided",
            "reported_by",
            "created_at",
        ]
        read_only_fields = ["job_issue", "cvat_issue_id", "is_voided", "reported_by", "created_at"]


class JobIssueSerializer(serializers.ModelSerializer):
    job_name = serializers.CharField(source="job.name", read_only=True)
    author = UserBriefSerializer(read_only=True)
    ruled_by = UserBriefSerializer(read_only=True)
    cvat_synced_at = RFC3339DateTimeField(read_only=True)
    ruled_at = RFC3339DateTimeField(read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)
    updated_at = RFC3339DateTimeField(read_only=True)

    class Meta(ModelMetaBase):
        model = JobIssue
        fields = [
            "id",
            "job",
            "job_name",
            "cvat_issue_id",
            "first_comment_id",
            "defect_code",
            "primary_category",
            "severity",
            "source",
            "is_clarification",
            "frame_number",
            "frame_start",
            "frame_end",
            "track_id",
            "shape_id",
            "position",
            "message",
            "author",
            "author_cvat_id",
            "author_stage",
            "authority_status",
            "status",
            "cvat_resolved",
            "cvat_last_comment_id",
            "cvat_synced_at",
            "source_missing",
            "tampered",
            "tamper_reason",
            "cvat_reopen_drift",
            "is_disputed",
            "dispute_reason",
            "ruling_label",
            "ruling_attributes",
            "ruling_note",
            "ruled_by",
            "ruled_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class JobIssueImportSerializer(serializers.Serializer):
    job = serializers.IntegerField(min_value=1, max_value=PG_INT32_MAX)


class JobIssueNoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class JobIssueDisputeSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=3, max_length=2000)


class JobIssueRuleSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["ruling", "not_an_issue", "resolved"])
    ruling_label = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    ruling_attributes = serializers.DictField(required=False, default=dict)
    ruling_note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    dispute_outcome = serializers.ChoiceField(choices=["rejected"], required=False, allow_null=True, default=None)

    def validate_ruling_attributes(self, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 32:
            raise serializers.ValidationError("ruling_attributes tối đa 32 thuộc tính.")
        clean: dict[str, str | int | float | bool | None] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 64:
                raise serializers.ValidationError("Tên thuộc tính không hợp lệ.")
            if item is not None and not isinstance(item, (str, int, float, bool)):
                raise serializers.ValidationError("Giá trị thuộc tính phải là kiểu nguyên thủy (chuỗi, số, boolean).")
            if isinstance(item, str) and len(item) > 255:
                raise serializers.ValidationError("Giá trị thuộc tính quá dài.")
            clean[key.strip()] = item
        return clean


class SampleJobSerializer(serializers.ModelSerializer):
    annotator = UserBriefSerializer(read_only=True)
    qc1_reviewer = UserBriefSerializer(read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset_name = serializers.CharField(source="dataset.name", read_only=True)
    deadline = RFC3339DateTimeField(read_only=True)
    cvat_url = serializers.CharField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    due_state = serializers.CharField(read_only=True)
    hours_remaining = serializers.FloatField(read_only=True)
    max_rework_rounds = serializers.IntegerField(source="project.max_rework_rounds", read_only=True)

    class Meta(ModelMetaBase):
        model = Job
        fields = [
            "id",
            "name",
            "status",
            "dataset_name",
            "batch_name",
            "annotator",
            "qc1_reviewer",
            "deadline",
            "is_overdue",
            "due_state",
            "hours_remaining",
            "rework_round",
            "max_rework_rounds",
            "object_count",
            "frame_count",
            "cvat_start_frame",
            "cvat_job_id",
            "cvat_url",
        ]


class AuditSampleSerializer(serializers.ModelSerializer):
    job = SampleJobSerializer(read_only=True)
    job_name = serializers.CharField(source="job.name", read_only=True)
    batch_name = serializers.CharField(source="job.batch.name", read_only=True)
    dataset_name = serializers.CharField(source="job.dataset.name", read_only=True)
    cvat_url = serializers.CharField(source="job.cvat_url", read_only=True)
    auditor = UserBriefSerializer(read_only=True)
    reviewed_by = UserBriefSerializer(read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)
    reviewed_at = RFC3339DateTimeField(read_only=True)
    audit_status = serializers.CharField(source="audit.status", read_only=True)

    class Meta(ModelMetaBase):
        model = AuditSample
        fields = [
            "id",
            "audit",
            "audit_status",
            "job",
            "job_name",
            "batch_name",
            "dataset_name",
            "cvat_url",
            "frames",
            "rework_round",
            "checked_object_count",
            "auditor",
            "result",
            "created_at",
            "reviewed_by",
            "reviewed_at",
            "comment",
            "errors",
        ]

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["errors"] = ReviewErrorSerializer(many=True, read_only=True)
        return fields


class AuditSerializer(serializers.ModelSerializer):
    """Đợt QC2 của một task (tự tạo / tự chốt)."""

    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset_name = serializers.CharField(source="batch.dataset.name", read_only=True)
    created_at = RFC3339DateTimeField(read_only=True)
    completed_at = RFC3339DateTimeField(read_only=True)
    sample_count = serializers.IntegerField(read_only=True)
    passed = serializers.IntegerField(read_only=True)
    rejected = serializers.IntegerField(read_only=True)
    pending = serializers.IntegerField(read_only=True)

    class Meta(ModelMetaBase):
        model = Audit
        fields = [
            "id",
            "batch",
            "batch_name",
            "dataset_name",
            "status",
            "sampling_rate",
            "created_at",
            "completed_at",
            "sample_count",
            "passed",
            "rejected",
            "pending",
        ]


_INVALID_CATEGORY_MSG = "Loại lỗi không hợp lệ hoặc không thuộc dự án này."


class _ProjectErrorCategoryField(serializers.PrimaryKeyRelatedField):
    default_error_messages = {
        **serializers.PrimaryKeyRelatedField.default_error_messages,
        "does_not_exist": _INVALID_CATEGORY_MSG,
        "incorrect_type": _INVALID_CATEGORY_MSG,
    }

    def get_queryset(self):
        project = self.context.get("project")
        if project is None:
            return ErrorCategory.objects.none()
        return ErrorCategory.objects.filter(project=project, is_active=True)


class _BaseErrorInputSerializer(serializers.Serializer):
    category = _ProjectErrorCategoryField(queryset=ErrorCategory.objects.none())
    job_issue = serializers.IntegerField(
        min_value=1, max_value=PG_INT32_MAX, required=False, allow_null=True, default=None
    )
    severity = serializers.ChoiceField(choices=Severity.choices, required=False)
    verdict = serializers.ChoiceField(choices=ErrorVerdict.choices, required=False, default=ErrorVerdict.FAIL)
    frame_number = serializers.IntegerField(
        min_value=0, max_value=PG_INT32_MAX, required=False, allow_null=True, default=None
    )
    cvat_object_id = serializers.IntegerField(
        min_value=1, max_value=PG_INT32_MAX, required=False, allow_null=True, default=None
    )
    is_missing_object = serializers.BooleanField(required=False, default=False)
    location = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("is_missing_object") and attrs.get("job_issue") is None:
            if attrs.get("cvat_object_id") is not None:
                raise serializers.ValidationError(
                    {"cvat_object_id": "Lỗi thiếu đối tượng không được gắn cvat_object_id."}
                )
            if attrs.get("verdict", ErrorVerdict.FAIL) == ErrorVerdict.EDGE:
                raise serializers.ValidationError(
                    {"verdict": "Lỗi thiếu đối tượng phải có kết luận 'fail', không được chọn 'edge'."}
                )
        return attrs


class ErrorInputSerializer(_BaseErrorInputSerializer):
    def validate_category(self, category: ErrorCategory) -> ErrorCategory:
        if category.project_id != self.context["project"].id:
            raise serializers.ValidationError("Loại lỗi không thuộc dự án này.")
        if category.applies_to == ErrorCategory.AppliesTo.QC1:
            raise serializers.ValidationError("Loại lỗi này chỉ dùng cho QC1.")
        return category


class RejectSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    rework_scope = serializers.ChoiceField(choices=ReworkScope.choices, required=False, default=ReworkScope.PARTIAL)

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["errors"] = ErrorInputSerializer(many=True, allow_empty=False)
        return fields


class AssignAuditorSerializer(serializers.Serializer):
    auditor = serializers.IntegerField(min_value=1, max_value=PG_INT32_MAX)


class PassSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class Qc1StartSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class Qc1ErrorInputSerializer(_BaseErrorInputSerializer):
    def validate_category(self, category: ErrorCategory) -> ErrorCategory:
        if category.project_id != self.context["project"].id:
            raise serializers.ValidationError("Loại lỗi không thuộc dự án này.")
        if category.applies_to == ErrorCategory.AppliesTo.QC2:
            raise serializers.ValidationError("Loại lỗi này chỉ dùng cho QC2.")
        return category


class Qc1RejectSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    rework_scope = serializers.ChoiceField(choices=ReworkScope.choices, required=False, default=ReworkScope.PARTIAL)

    def get_fields(self) -> dict[str, Any]:
        fields = super().get_fields()
        fields["errors"] = Qc1ErrorInputSerializer(many=True, allow_empty=False)
        return fields
