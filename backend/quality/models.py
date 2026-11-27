from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from projects.models import SamplingMethod, StratifyBy


class Severity(models.TextChoices):
    MINOR = "minor", "Nhẹ"
    MAJOR = "major", "Nặng"
    CRITICAL = "critical", "Nghiêm trọng"


class ReviewStage(models.TextChoices):
    QC1 = "qc1", "QC1"
    QC2 = "qc2", "QC2"


class ErrorVerdict(models.TextChoices):
    """Phân loại kết luận cấp cuboid tách biệt với Severity."""

    FAIL = "fail", "Lỗi (Fail)"
    EDGE = "edge", "Cận biên (Edge)"


class ErrorCategory(models.Model):
    """Danh mục lỗi. QC1 và QC2 cùng dùng khi ghi lỗi."""

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


DEFAULT_ERROR_CATEGORIES: tuple[tuple[str, str, str, str], ...] = (
    ("Thiếu đối tượng", "Bỏ sót đối tượng cần gán nhãn trên frame", Severity.MAJOR, ErrorCategory.AppliesTo.BOTH),
    ("Sai nhãn lớp", "Gắn sai class/category so với guideline", Severity.MAJOR, ErrorCategory.AppliesTo.BOTH),
    ("Lệch khung / biên", "Bounding box / cuboid lệch kích thước hoặc góc xoay", Severity.MINOR, ErrorCategory.AppliesTo.BOTH),
    ("Gán nhầm / thừa", "Gán nhãn vùng không thuộc đối tượng mục tiêu", Severity.MINOR, ErrorCategory.AppliesTo.BOTH),
    ("Sai thuộc tính", "Thiếu hoặc sai attribute / occlusion / truncation", Severity.MINOR, ErrorCategory.AppliesTo.BOTH),
    ("Lỗi nghiêm trọng", "Vi phạm quy tắc guideline nghiêm trọng cần làm lại", Severity.CRITICAL, ErrorCategory.AppliesTo.BOTH),
)


def seed_default_error_categories(project) -> int:
    """Tạo bộ danh mục lỗi mặc định cho organization mới (idempotent) để QC1/QC2 Reject không bị tắc."""
    if ErrorCategory.objects.filter(project=project).exists():
        return 0
    objs = [
        ErrorCategory(project=project, name=name, description=desc, severity=sev, applies_to=applies)
        for name, desc, sev, applies in DEFAULT_ERROR_CATEGORIES
    ]
    ErrorCategory.objects.bulk_create(objs, ignore_conflicts=True)
    return len(objs)


class Audit(models.Model):
    """Nhóm các lượt QC2 của MỘT TASK (Batch). Tạo tự động khi job đầu tiên của task vào Chờ QC2;
    chốt (completed) khi task được bàn giao. Các trường method / seed / eligible_* là của cách
    lấy mẫu job cũ — không còn dùng (QC2 kiểm mọi job, mỗi job một phần frame).
    """

    if TYPE_CHECKING:
        id: int
        project_id: int
        batch_id: int
        samples: Any

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "Đang audit"
        COMPLETED = "completed", "Đã chốt"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="audits")
    batch = models.ForeignKey("projects.Batch", on_delete=models.CASCADE, related_name="audits")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.IN_PROGRESS)
    method = models.CharField(max_length=20, choices=SamplingMethod.choices)
    sampling_rate = models.PositiveSmallIntegerField()
    stratify_by = models.CharField(max_length=20, choices=StratifyBy.choices, blank=True)
    seed = models.BigIntegerField()
    eligible_count = models.PositiveIntegerField()
    eligible_job_ids = models.JSONField(default=list)
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
            models.UniqueConstraint(
                fields=["batch"],
                condition=models.Q(status="in_progress"),
                name="unique_in_progress_audit_per_batch",
            ),
        ]

    def clean(self):
        super().clean()
        if not (1 <= self.sampling_rate <= 100):
            raise ValidationError({"sampling_rate": "Tỉ lệ lấy mẫu phải nằm trong khoảng 1..100."})
        if self.batch_id and self.project_id and self.batch.project_id != self.project_id:
            raise ValidationError({"batch": "Task không thuộc cùng organization với Audit."})

    def __str__(self):
        return f"Audit #{self.pk} · {self.batch}"


class AuditSample(models.Model):
    """Một lượt QC2 của một job: các frame được chọn để kiểm + kết quả.

    Mỗi lần job vào Chờ QC2 (lần đầu hoặc sau rework) có một lượt mới → cùng job có thể có nhiều lượt.
    """

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
    # Số frame (đánh số theo task, như trên CVAT) QC2 cần kiểm — sampling_rate % frame của job.
    frames = models.JSONField(default=list)
    rework_round = models.PositiveSmallIntegerField(default=0)
    auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_samples"
    )
    result = models.CharField(max_length=10, choices=Result.choices, default=Result.PENDING)
    checked_object_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="Số cuboid trên các frame được kiểm (chờ định nghĩa khi tách theo frame)"
    )
    created_at = models.DateTimeField(default=timezone.now)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["job"],
                condition=models.Q(result="pending"),
                name="unique_pending_sample_per_job",
            ),
        ]

    def __str__(self):
        return f"AuditSample #{self.pk} · {self.job}"


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
    # nhưng vẫn cho xoá cả organization (khi đó lỗi cũng bị xoá theo).
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
        default=False, help_text="True nếu là lỗi thiếu đối tượng (False Negative)"
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
            models.CheckConstraint(
                condition=~models.Q(is_missing_object=True)
                | (models.Q(cvat_object_id__isnull=True) & models.Q(verdict="fail")),
                name="review_error_missing_object_valid",
            ),
        ]

    def __str__(self):
        return f"{self.stage} · {self.category} · {self.job}"
