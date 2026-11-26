from rest_framework import serializers

from accounts.models import Role, User
from accounts.serializers import UserBriefSerializer
from jobs.models import Job, ReworkScope
from projects.models import SamplingMethod, StratifyBy

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
    cvat_url = serializers.CharField(read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    due_state = serializers.CharField(read_only=True)
    hours_remaining = serializers.FloatField(read_only=True)
    max_rework_rounds = serializers.IntegerField(source="project.max_rework_rounds", read_only=True)

    class Meta:
        model = Job
        fields = [
            "id",
            "name",
            "status",
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
            "cvat_job_id",
            "cvat_url",
        ]


class AuditSampleSerializer(serializers.ModelSerializer):
    job = SampleJobSerializer(read_only=True)
    auditor = UserBriefSerializer(read_only=True)
    reviewed_by = UserBriefSerializer(read_only=True)
    errors = ReviewErrorSerializer(many=True, read_only=True)
    audit_status = serializers.CharField(source="audit.status", read_only=True)

    class Meta:
        model = AuditSample
        fields = ["id", "audit", "audit_status", "job", "stratum", "auditor", "result",
                  "reviewed_by", "reviewed_at", "comment", "errors"]


class AuditSerializer(serializers.ModelSerializer):
    batch_name = serializers.CharField(source="batch.name", read_only=True)
    dataset_name = serializers.CharField(source="batch.dataset.name", read_only=True)
    created_by = UserBriefSerializer(read_only=True)
    decided_by = UserBriefSerializer(read_only=True)
    decision_label = serializers.CharField(source="get_decision_display", read_only=True)
    sample_count = serializers.IntegerField(read_only=True)
    passed = serializers.IntegerField(read_only=True)
    rejected = serializers.IntegerField(read_only=True)
    pending = serializers.IntegerField(read_only=True)
    strata_summary = serializers.SerializerMethodField()

    class Meta:
        model = Audit
        fields = [
            "id",
            "batch",
            "batch_name",
            "dataset_name",
            "status",
            "decision",
            "decision_label",
            "decision_reason",
            "decided_by",
            "stratum_decisions",
            "strata_summary",
            "method",
            "sampling_rate",
            "stratify_by",
            "seed",
            "eligible_count",
            "note",
            "created_by",
            "created_at",
            "completed_at",
            "sample_count",
            "passed",
            "rejected",
            "pending",
        ]

    def get_strata_summary(self, audit):
        if audit.method != SamplingMethod.STRATIFIED:
            return []
        eligible_by_stratum = {}
        for _, stratum in (audit.eligible_job_strata or {}).items():
            eligible_by_stratum[stratum] = eligible_by_stratum.get(stratum, 0) + 1
        samples_by_stratum = {}
        for s in audit.samples.all():
            bucket = samples_by_stratum.setdefault(
                s.stratum, {"sampled": 0, "passed": 0, "rejected": 0, "pending": 0}
            )
            bucket["sampled"] += 1
            if s.result == AuditSample.Result.PASS:
                bucket["passed"] += 1
            elif s.result == AuditSample.Result.REJECT:
                bucket["rejected"] += 1
            else:
                bucket["pending"] += 1
        names = sorted(set(eligible_by_stratum) | set(samples_by_stratum))
        return [
            {
                "stratum": name,
                "eligible": eligible_by_stratum.get(name, samples_by_stratum.get(name, {}).get("sampled", 0)),
                **samples_by_stratum.get(name, {"sampled": 0, "passed": 0, "rejected": 0, "pending": 0}),
                "decision": (audit.stratum_decisions or {}).get(name, ""),
            }
            for name in names
        ]


class AuditCompleteSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=Audit.Decision.choices, required=False, default=Audit.Decision.ACCEPT)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    stratum_decisions = serializers.DictField(
        child=serializers.ChoiceField(choices=["accept", "reject"]),
        required=False,
        default=dict,
    )


class AuditInputSerializer(serializers.Serializer):
    """Dữ liệu để xem trước / tạo audit. Bỏ trống thì lấy cấu hình mặc định của dự án."""

    batch = serializers.IntegerField()
    method = serializers.ChoiceField(choices=SamplingMethod.choices, required=False)
    sampling_rate = serializers.IntegerField(min_value=1, max_value=100, required=False)
    stratify_by = serializers.ChoiceField(choices=StratifyBy.choices, required=False)
    seed = serializers.IntegerField(required=False, help_text="Gửi lại seed của bản xem trước để ra đúng mẫu đó")
    auditors = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        project = self.context["project"]
        attrs.setdefault("method", project.sampling_method)
        attrs.setdefault("sampling_rate", project.sampling_rate)
        attrs.setdefault("stratify_by", project.stratify_by)
        auditors = list(User.objects.filter(pk__in=attrs["auditors"]))
        for auditor in auditors:
            if Role.QC2 not in auditor.get_project_roles(project):
                raise serializers.ValidationError({"auditors": f"{auditor} không có quyền QC2 trong dự án."})
        attrs["auditors"] = auditors
        return attrs


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


class Qc1StartSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class Qc1ErrorInputSerializer(serializers.Serializer):
    category = serializers.PrimaryKeyRelatedField(queryset=ErrorCategory.objects.filter(is_active=True))
    severity = serializers.ChoiceField(choices=Severity.choices, required=False)
    location = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_category(self, category):
        if category.project_id != self.context["project"].id:
            raise serializers.ValidationError("Loại lỗi không thuộc dự án này.")
        if category.applies_to == ErrorCategory.AppliesTo.QC2:
            raise serializers.ValidationError("Loại lỗi này chỉ dùng cho QC2.")
        return category


class Qc1RejectSerializer(serializers.Serializer):
    errors = Qc1ErrorInputSerializer(many=True, allow_empty=False)
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    rework_scope = serializers.ChoiceField(choices=ReworkScope.choices, required=False, default=ReworkScope.PARTIAL)
