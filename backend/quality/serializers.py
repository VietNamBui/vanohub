from rest_framework import serializers

from accounts.serializers import UserBriefSerializer
from jobs.models import Job

from .models import Audit, AuditSample, ErrorCategory, ReviewError, Severity


class ErrorCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorCategory
        fields = ["id", "name", "description", "severity", "applies_to", "is_active"]

    def validate_name(self, name):
        qs = ErrorCategory.objects.filter(project=self.context["project"], name=name)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Danh mục đã có loại lỗi trùng tên.")
        return name


class ReviewErrorSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    reported_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = ReviewError
        fields = ["id", "stage", "rework_round", "category", "category_name", "severity",
                  "location", "description", "reported_by", "created_at"]


class SampleJobSerializer(serializers.ModelSerializer):
    annotator = UserBriefSerializer(read_only=True)
    qc1_reviewer = UserBriefSerializer(read_only=True)
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset_name = serializers.CharField(source="dataset.name", read_only=True)
    cvat_url = serializers.CharField(read_only=True)

    class Meta:
        model = Job
        fields = ["id", "name", "status", "dataset_name", "batch_name", "annotator", "qc1_reviewer", "rework_round",
                  "object_count", "frame_count", "cvat_start_frame", "cvat_job_id", "cvat_url"]


class AuditSampleSerializer(serializers.ModelSerializer):
    job = SampleJobSerializer(read_only=True)
    auditor = UserBriefSerializer(read_only=True)
    reviewed_by = UserBriefSerializer(read_only=True)
    errors = ReviewErrorSerializer(many=True, read_only=True)
    audit_status = serializers.CharField(source="audit.status", read_only=True)

    class Meta:
        model = AuditSample
        fields = ["id", "audit", "audit_status", "job", "frames", "rework_round", "auditor", "result",
                  "reviewed_by", "reviewed_at", "comment", "errors"]


class AuditSerializer(serializers.ModelSerializer):
    """Đợt QC2 của một task (tự tạo / tự chốt)."""

    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset_name = serializers.CharField(source="batch.dataset.name", read_only=True)
    sample_count = serializers.IntegerField(read_only=True)
    passed = serializers.IntegerField(read_only=True)
    rejected = serializers.IntegerField(read_only=True)
    pending = serializers.IntegerField(read_only=True)

    class Meta:
        model = Audit
        fields = ["id", "batch", "batch_name", "dataset_name", "status", "sampling_rate",
                  "created_at", "completed_at", "sample_count", "passed", "rejected", "pending"]


class ErrorInputSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=ErrorCategory.objects.filter(is_active=True))
    severity = serializers.ChoiceField(choices=Severity.choices, required=False)
    location = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_category(self, category):
        if category.project_id != self.context["project"].id:
            raise serializers.ValidationError("Loại lỗi không thuộc dự án này.")
        if category.applies_to == ErrorCategory.AppliesTo.QC1:
            raise serializers.ValidationError("Loại lỗi này chỉ dùng cho QC1.")
        return category


class RejectSerializer(serializers.Serializer):
    errors = ErrorInputSerializer(many=True, allow_empty=False)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class PassSerializer(serializers.Serializer):
    comment = serializers.CharField(required=False, allow_blank=True, default="")
