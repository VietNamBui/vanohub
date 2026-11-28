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


class PrimaryCategory(models.TextChoices):
    NONE = "", "Chưa phân nhóm"
    E1 = "E1", "E1 · Thiếu đối tượng"
    E2 = "E2", "E2 · Sai nhãn lớp"
    E3 = "E3", "E3 · Lệch khung / biên"
    E4 = "E4", "E4 · Gán nhầm / thừa"
    E5 = "E5", "E5 · Sai thuộc tính"
    E6 = "E6", "E6 · Lỗi liên kết track"


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
    code = models.CharField(max_length=32, blank=True, default="")
    primary_category = models.CharField(
        max_length=8,
        choices=PrimaryCategory.choices,
        blank=True,
        default=PrimaryCategory.NONE,
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MINOR)
    applies_to = models.CharField(max_length=10, choices=AppliesTo.choices, default=AppliesTo.BOTH)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="unique_error_category"),
            models.UniqueConstraint(
                fields=["project", "code"],
                condition=~models.Q(code=""),
                name="unique_error_category_code",
            ),
            models.CheckConstraint(
                condition=models.Q(primary_category__in=PrimaryCategory.values),
                name="error_category_valid_primary_category",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.primary_category not in PrimaryCategory.values:
            raise ValidationError({"primary_category": "Nhóm lỗi chính không hợp lệ."})

    def __str__(self):
        return self.name


DEFAULT_ERROR_CATEGORIES: tuple[tuple[str, str, str, str, str, str], ...] = (
    ("E1", PrimaryCategory.E1, "Thiếu đối tượng", "Bỏ sót đối tượng cần gán nhãn trên frame", Severity.MAJOR, ErrorCategory.AppliesTo.BOTH),
    ("E2", PrimaryCategory.E2, "Sai nhãn lớp", "Gắn sai class/category so với guideline", Severity.MAJOR, ErrorCategory.AppliesTo.BOTH),
    ("E3", PrimaryCategory.E3, "Lệch khung / biên", "Bounding box / cuboid lệch kích thước hoặc góc xoay", Severity.MINOR, ErrorCategory.AppliesTo.BOTH),
    ("E4", PrimaryCategory.E4, "Gán nhầm / thừa", "Gán nhãn vùng không thuộc đối tượng mục tiêu", Severity.MINOR, ErrorCategory.AppliesTo.BOTH),
    ("E5", PrimaryCategory.E5, "Sai thuộc tính", "Thiếu hoặc sai attribute / occlusion / truncation", Severity.MINOR, ErrorCategory.AppliesTo.BOTH),
    ("E6", PrimaryCategory.E6, "Lỗi liên kết track", "Sai hoặc đứt gãy track ID giữa các frame", Severity.MAJOR, ErrorCategory.AppliesTo.BOTH),
    ("", PrimaryCategory.NONE, "Lỗi nghiêm trọng", "Vi phạm quy tắc guideline nghiêm trọng cần làm lại", Severity.CRITICAL, ErrorCategory.AppliesTo.BOTH),
)


def seed_default_error_categories(project) -> int:
    """Tạo bộ danh mục lỗi mặc định cho organization mới (idempotent) để QC1/QC2 Reject không bị tắc."""
    if ErrorCategory.objects.filter(project=project).exists():
        return 0
    objs = [
        ErrorCategory(
            project=project,
            code=code,
            primary_category=primary_cat,
            name=name,
            description=desc,
            severity=sev,
            applies_to=applies,
        )
        for code, primary_cat, name, desc, sev, applies in DEFAULT_ERROR_CATEGORIES
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


class JobIssue(models.Model):
    """Issue đồng bộ một chiều từ CVAT và vòng đời kiểm soát/phán quyết trên VanoHub."""

    if TYPE_CHECKING:
        id: int
        project_id: int
        job_id: int
        author_id: int | None
        ruled_by_id: int | None
        review_errors: Any
        disputes: Any

        def get_status_display(self) -> str: ...

    class Source(models.TextChoices):
        MANUAL = "manual", "Thủ công"
        CLARIFICATION = "clarification", "Làm rõ (Clarification)"

    class AuthorStage(models.TextChoices):
        NONE = "", "Không xác định"
        ANNOTATOR = "annotator", "Annotator"
        QC1 = "qc1", "QC1"
        QC2 = "qc2", "QC2"

    class AuthorityStatus(models.TextChoices):
        VALID = "valid", "Hợp lệ"
        REJECTED_AUTHOR = "rejected_author", "Tác giả không hợp lệ"

    class Status(models.TextChoices):
        OPEN = "open", "Mở"
        ADDRESSED = "addressed", "Đã sửa (chờ xác nhận)"
        UNCLEAR = "unclear", "Chưa rõ / Tranh chấp"
        REOPENED = "reopened", "Mở lại"
        RESOLVED = "resolved", "Đã xử lý"
        NOT_AN_ISSUE = "not_an_issue", "Không phải lỗi"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="job_issues")
    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="issues")
    cvat_issue_id = models.PositiveIntegerField()
    first_comment_id = models.PositiveIntegerField(null=True, blank=True)
    defect_code = models.CharField(max_length=32, blank=True, default="")
    primary_category = models.CharField(
        max_length=8,
        choices=PrimaryCategory.choices,
        blank=True,
        default=PrimaryCategory.NONE,
    )
    severity = models.CharField(max_length=20, choices=Severity.choices, default=Severity.MINOR)
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.MANUAL)
    is_clarification = models.BooleanField(default=False)

    frame_number = models.PositiveIntegerField(default=0)
    frame_start = models.PositiveIntegerField(null=True, blank=True)
    frame_end = models.PositiveIntegerField(null=True, blank=True)
    track_id = models.PositiveIntegerField(null=True, blank=True)
    shape_id = models.PositiveIntegerField(null=True, blank=True)
    position = models.JSONField(default=list, blank=True)
    message = models.TextField(blank=True, default="")

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_job_issues",
    )
    author_cvat_id = models.PositiveIntegerField(null=True, blank=True)
    author_stage = models.CharField(
        max_length=16,
        choices=AuthorStage.choices,
        blank=True,
        default=AuthorStage.NONE,
    )
    authority_status = models.CharField(
        max_length=24,
        choices=AuthorityStatus.choices,
        default=AuthorityStatus.VALID,
    )
    status = models.CharField(
        max_length=24,
        choices=Status.choices,
        default=Status.OPEN,
    )

    reopened_after_comment_id = models.PositiveIntegerField(default=0)
    last_applied_lifecycle_comment_id = models.PositiveIntegerField(default=0)
    cvat_resolved = models.BooleanField(default=False)
    cvat_last_comment_id = models.PositiveIntegerField(default=0)
    cvat_comments_fingerprint = models.CharField(max_length=64, blank=True, default="")
    cvat_synced_at = models.DateTimeField(null=True, blank=True)

    source_missing = models.BooleanField(default=False)
    tampered = models.BooleanField(default=False)
    tamper_reason = models.CharField(max_length=64, blank=True, default="")
    cvat_reopen_drift = models.BooleanField(default=False)

    is_disputed = models.BooleanField(default=False)
    dispute_reason = models.TextField(blank=True, default="")

    ruling_label = models.CharField(max_length=120, blank=True, default="")
    ruling_attributes = models.JSONField(default=dict, blank=True)
    ruling_note = models.TextField(blank=True, default="")
    ruled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ruled_job_issues",
    )
    ruled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["job", "authority_status", "status"]),
            models.Index(fields=["project", "is_disputed"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["job", "cvat_issue_id"], name="unique_job_issue_cvat_id"),
            models.CheckConstraint(condition=models.Q(cvat_issue_id__gte=1), name="job_issue_cvat_issue_id_positive"),
            models.CheckConstraint(
                condition=models.Q(first_comment_id__isnull=True) | models.Q(first_comment_id__gte=1),
                name="job_issue_first_comment_id_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(author_cvat_id__isnull=True) | models.Q(author_cvat_id__gte=1),
                name="job_issue_author_cvat_id_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(track_id__isnull=True) | models.Q(track_id__gte=1),
                name="job_issue_track_id_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(shape_id__isnull=True) | models.Q(shape_id__gte=1),
                name="job_issue_shape_id_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(track_id__isnull=True) | models.Q(shape_id__isnull=True),
                name="job_issue_exclusive_track_or_shape",
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(frame_start__isnull=True) & models.Q(frame_end__isnull=True))
                    | (
                        models.Q(frame_start__isnull=False)
                        & models.Q(frame_end__isnull=False)
                        & models.Q(frame_start__lte=models.F("frame_end"))
                    )
                ),
                name="job_issue_frame_span_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(ruled_by__isnull=True) | models.Q(ruled_at__isnull=False),
                name="job_issue_ruled_by_requires_ruled_at",
            ),
            models.CheckConstraint(
                condition=models.Q(primary_category__in=["", "E1", "E2", "E3", "E4", "E5", "E6"]),
                name="job_issue_valid_primary_category",
            ),
            models.CheckConstraint(
                condition=models.Q(severity__in=["minor", "major", "critical"]),
                name="job_issue_valid_severity",
            ),
            models.CheckConstraint(
                condition=models.Q(source__in=["manual", "clarification"]),
                name="job_issue_valid_source",
            ),
            models.CheckConstraint(
                condition=models.Q(author_stage__in=["", "annotator", "qc1", "qc2"]),
                name="job_issue_valid_author_stage",
            ),
            models.CheckConstraint(
                condition=models.Q(authority_status__in=["valid", "rejected_author"]),
                name="job_issue_valid_authority_status",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["open", "addressed", "unclear", "reopened", "resolved", "not_an_issue"]),
                name="job_issue_valid_status",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.job_id and self.project_id and self.job.project_id != self.project_id:
            raise ValidationError({"job": "Job không thuộc cùng organization với JobIssue."})
        if (self.frame_start is None) != (self.frame_end is None):
            raise ValidationError({"frame_start": "frame_start và frame_end phải cùng có hoặc cùng trống."})
        if self.frame_start is not None and self.frame_end is not None and self.frame_start > self.frame_end:
            raise ValidationError({"frame_end": "frame_end phải lớn hơn hoặc bằng frame_start."})
        if self.track_id is not None and self.shape_id is not None:
            raise ValidationError({"shape_id": "Không thể đồng thời gắn track_id và shape_id."})
        if self.ruled_by_id is not None and self.ruled_at is None:
            raise ValidationError({"ruled_at": "Phải có ruled_at khi đã gắn ruled_by."})

    def __str__(self) -> str:
        return f"Issue #{self.cvat_issue_id} · {self.job}"


class ReviewError(models.Model):
    """Một lỗi được ghi khi review (QC1 hoặc QC2). Lưu từng lần → giữ được lịch sử qua các vòng rework."""

    if TYPE_CHECKING:
        id: int
        job_id: int
        audit_sample_id: int | None
        job_issue_id: int | None
        category_id: int
        reported_by_id: int | None

    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, related_name="review_errors")
    stage = models.CharField(max_length=10, choices=ReviewStage.choices)
    rework_round = models.PositiveSmallIntegerField(help_text="Vòng rework tại thời điểm ghi lỗi")
    audit_sample = models.ForeignKey(
        AuditSample, on_delete=models.CASCADE, null=True, blank=True, related_name="errors"
    )
    job_issue = models.ForeignKey(
        JobIssue, on_delete=models.SET_NULL, null=True, blank=True, related_name="review_errors"
    )
    cvat_issue_id = models.PositiveIntegerField(null=True, blank=True)
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
            models.CheckConstraint(
                condition=models.Q(cvat_issue_id__isnull=True) | models.Q(cvat_issue_id__gte=1),
                name="review_error_cvat_issue_id_positive",
            ),
            models.UniqueConstraint(
                fields=["job", "stage", "rework_round", "cvat_issue_id"],
                condition=models.Q(cvat_issue_id__isnull=False),
                name="unique_review_error_issue_per_round",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.job_issue_id and self.job_id and self.job_issue is not None and self.job_issue.job_id != self.job_id:
            raise ValidationError({"job_issue": "JobIssue không thuộc cùng Job với ReviewError."})
        if self.audit_sample_id and self.job_id and self.audit_sample is not None and self.audit_sample.job_id != self.job_id:
            raise ValidationError({"audit_sample": "AuditSample không thuộc cùng Job với ReviewError."})

    def __str__(self):
        return f"{self.stage} · {self.category} · {self.job}"
