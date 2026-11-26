from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from projects.models import SamplingMethod, StratifyBy


class Severity(models.TextChoices):
    MINOR = "minor", "Nhẹ"
    MAJOR = "major", "Nặng"
    CRITICAL = "critical", "Nghiêm trọng"


class ReviewStage(models.TextChoices):
    QC1 = "qc1", "QC1"
    QC2 = "qc2", "QC2"


class ErrorVerdict(models.TextChoices):
    """Phân loại kết luận cấp cuboid tách biệt với Severity (CL02/CL11)."""

    FAIL = "fail", "Lỗi (Fail)"
    EDGE = "edge", "Cận biên (Edge)"


class ErrorCategory(models.Model):
    """Danh mục lỗi (PM-15). QC1 và QC2 cùng dùng khi ghi lỗi."""

    if TYPE_CHECKING:
        id: int
        project_id: int

    class AppliesTo(models.TextChoices):
        QC1 = "qc1", "QC1"
        QC2 = "qc2", "QC2"
        BOTH = "both", "QC1 & QC2"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="error_categories")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MINOR)
    applies_to = models.CharField(max_length=10, choices=AppliesTo.choices, default=AppliesTo.BOTH)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["project", "name"], name="unique_error_category")]

    def __str__(self):
        return self.name


class Audit(models.Model):
    """Một đợt QC2 Internal Audit trên một Batch.

    Lưu lại cấu hình sampling đã dùng + seed ngẫu nhiên → có thể giải thích vì sao
    những job này được chọn (yêu cầu "lưu lịch sử Sampling").
    """

    if TYPE_CHECKING:
        id: int
        project_id: int
        batch_id: int
        decided_by_id: int | None
        samples: Any

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "Đang audit"
        COMPLETED = "completed", "Đã chốt"

    class Decision(models.TextChoices):
        ACCEPT = "accept", "Chấp nhận batch"
        REJECT = "reject", "Trả cả batch"
        PARTIAL_REJECT = "partial_reject", "Trả theo tầng"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="audits")
    batch = models.ForeignKey("projects.Batch", on_delete=models.CASCADE, related_name="audits")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    decision = models.CharField(max_length=20, choices=Decision.choices, blank=True, default="")
    decision_reason = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    stratum_decisions = models.JSONField(default=dict, blank=True)
    method = models.CharField(max_length=20, choices=SamplingMethod.choices)
    sampling_rate = models.PositiveSmallIntegerField()
    stratify_by = models.CharField(max_length=20, choices=StratifyBy.choices, blank=True)
    seed = models.BigIntegerField()
    eligible_count = models.PositiveIntegerField()
    # Job đủ điều kiện TẠI LÚC TẠO audit. Khi chốt, job không được lấy mẫu trong danh sách này
    # mới được duyệt hoặc trả sửa — job vào hàng chờ QC2 sau đó phải chờ đợt audit sau.
    eligible_job_ids = models.JSONField(default=list)
    # Bản đồ {str(job_id): stratum_name} lưu tại lúc tạo audit để quyết định theo tầng nhất quán.
    eligible_job_strata = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(sampling_rate__gte=1, sampling_rate__lte=100),
                name="audit_sampling_rate_1_to_100",
            ),
            models.CheckConstraint(
                condition=models.Q(status="in_progress") | ~models.Q(decision=""),
                name="audit_completed_requires_decision",
            ),
        ]

    def clean(self):
        super().clean()
        if not (1 <= self.sampling_rate <= 100):
            raise ValidationError({"sampling_rate": "Tỉ lệ lấy mẫu phải nằm trong khoảng 1..100."})
        if self.status == self.Status.COMPLETED and not self.decision:
            raise ValidationError({"decision": "Audit đã chốt phải có quyết định (decision)."})
        if self.batch_id and self.project_id and self.batch.dataset.project_id != self.project_id:
            raise ValidationError({"batch": "Batch không thuộc cùng dự án với Audit."})

    def __str__(self):
        return f"Audit #{self.pk} · {self.batch}"


class AuditSample(models.Model):
    """Một job được lấy mẫu trong một Audit, và kết quả QC2 của job đó."""

    if TYPE_CHECKING:
        id: int
        audit_id: int
        job_id: int
        auditor_id: int | None
        reviewed_by_id: int | None

    class Result(models.TextChoices):
        PENDING = "pending", "Chờ audit"
        PASS = "pass", "Pass"
        REJECT = "reject", "Reject"

    audit = models.ForeignKey(Audit, on_delete=models.CASCADE, related_name="samples")
    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="audit_samples")
    stratum = models.CharField(max_length=120, blank=True)
    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_samples"
    )
    result = models.CharField(max_length=10, choices=Result.choices, default=Result.PENDING)
    checked_object_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="Snapshot object_count của job tại thời điểm chấm audit QC2"
    )
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["audit", "job"], name="unique_job_per_audit")]


class ReviewError(models.Model):
    """Một lỗi được ghi khi review (QC1 hoặc QC2). Lưu từng lần → giữ được lịch sử qua các vòng rework."""

    if TYPE_CHECKING:
        id: int
        job_id: int
        audit_sample_id: int | None
        category_id: int
        reported_by_id: int | None

    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="review_errors")
    stage = models.CharField(max_length=10, choices=ReviewStage.choices)
    rework_round = models.PositiveSmallIntegerField(help_text="Vòng rework tại thời điểm ghi lỗi")
    audit_sample = models.ForeignKey(
        AuditSample, on_delete=models.CASCADE, null=True, blank=True, related_name="errors"
    )
    # RESTRICT (không phải PROTECT): chặn xoá riêng loại lỗi đang được dùng,
    # nhưng vẫn cho xoá cả dự án (khi đó lỗi cũng bị xoá theo).
    category = models.ForeignKey(ErrorCategory, on_delete=models.RESTRICT, related_name="errors")
    severity = models.CharField(max_length=20, choices=Severity.choices)
    verdict = models.CharField(max_length=10, choices=ErrorVerdict.choices, default=ErrorVerdict.FAIL)
    frame_number = models.PositiveIntegerField(
        null=True, blank=True, help_text="Số thứ tự frame (0-based) trên CVAT"
    )
    cvat_object_id = models.PositiveIntegerField(
        null=True, blank=True, help_text="ID đối tượng trên CVAT (trống nếu chưa gắn ID hoặc thiếu object)"
    )
    is_missing_object = models.BooleanField(
        default=False, help_text="True nếu là lỗi thiếu đối tượng (False Negative), cộng vào mẫu số N_missing"
    )
    location = models.CharField(max_length=120, blank=True, help_text="Frame / object ID")
    description = models.TextField(blank=True)
    is_voided = models.BooleanField(
        default=False, help_text="True khi PM chấp nhận khiếu nại lỗi (error_dispute resolved)"
    )
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(verdict__in=["fail", "edge"]),
                name="review_error_valid_verdict",
            ),
        ]
