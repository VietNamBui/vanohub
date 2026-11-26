from django.conf import settings
from django.db import models

from projects.models import SamplingMethod, StratifyBy


class Severity(models.TextChoices):
    MINOR = "minor", "Nhẹ"
    MAJOR = "major", "Nặng"
    CRITICAL = "critical", "Nghiêm trọng"


class ReviewStage(models.TextChoices):
    QC1 = "qc1", "QC1"
    QC2 = "qc2", "QC2"


class ErrorCategory(models.Model):
    """Danh mục lỗi (PM-15). QC1 và QC2 cùng dùng khi ghi lỗi."""

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
    """Nhóm các lượt QC2 của MỘT TASK (Batch). Tạo tự động khi job đầu tiên của task vào Chờ QC2;
    chốt (completed) khi task được bàn giao. Các trường method / seed / eligible_* là của cách
    lấy mẫu job cũ — không còn dùng (QC2 giờ kiểm mọi job, mỗi job một phần frame).

    Lưu lại cấu hình sampling đã dùng + seed ngẫu nhiên → có thể giải thích vì sao
    những job này được chọn (yêu cầu "lưu lịch sử Sampling").
    """

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
    # Job đủ điều kiện TẠI LÚC TẠO audit. Khi chốt, job không được lấy mẫu trong danh sách này
    # mới được duyệt — job vào hàng chờ QC2 sau đó phải chờ đợt audit sau.
    eligible_job_ids = models.JSONField(default=list)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Audit #{self.pk} · {self.batch}"


class AuditSample(models.Model):
    """Một lượt QC2 của một job: các frame được chọn để kiểm + kết quả.

    Mỗi lần job vào Chờ QC2 (lần đầu hoặc sau rework) có một lượt mới → cùng job có thể có nhiều lượt.
    """

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
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["id"]


class ReviewError(models.Model):
    """Một lỗi được ghi khi review (QC1 hoặc QC2). Lưu từng lần → giữ được lịch sử qua các vòng rework."""

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
    location = models.CharField(max_length=120, blank=True, help_text="Frame / object ID")
    description = models.TextField(blank=True)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
