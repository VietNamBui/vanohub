from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from accounts.datetime_utils import app_timezone


class FirstQc1Result(models.TextChoices):
    NONE = "", "Chưa kiểm"
    PASS = "pass", "Đạt lần đầu"
    REJECT = "reject", "Trượt lần đầu"


def user_work_date(user: Any = None, at: Any = None) -> date:
    """Ngày làm việc theo múi giờ nghiệp vụ Việt Nam (settings.APP_TIME_ZONE)."""
    return timezone.localtime(at or timezone.now(), app_timezone()).date()


class JobStatus(models.TextChoices):
    """Trạng thái vòng đời của Job (đủ luồng PM xác nhận theo batch sang QC2 và chốt batch)."""

    PENDING_ANNOTATION = "pending_annotation", "Chờ annotate"
    ANNOTATING = "annotating", "Đang annotate"
    PENDING_QC1 = "pending_qc1", "Chờ QC1"
    QC1_REVIEWING = "qc1_reviewing", "Đang QC1"
    QC1_PASSED = "qc1_passed", "Đạt QC1"
    REWORK = "rework", "Rework"
    PENDING_QC2 = "pending_qc2", "Chờ QC2"
    APPROVED = "approved", "Đã duyệt"
    DELIVERED = "delivered", "Đã bàn giao"


class ReworkScope(models.TextChoices):
    PARTIAL = "partial", "Sửa một phần"
    FULL = "full", "Sửa toàn job"


# Nhóm trạng thái theo stage, dùng cho tab lọc và Data Queue.
STAGE_STATUSES: dict[str, list[str]] = {
    "annotation": [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING, JobStatus.REWORK],
    "qc1": [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING, JobStatus.QC1_PASSED],
    "qc2": [JobStatus.PENDING_QC2],
    "done": [JobStatus.APPROVED, JobStatus.DELIVERED],
}
OPEN_STATUSES: list[str] = STAGE_STATUSES["annotation"] + STAGE_STATUSES["qc1"] + STAGE_STATUSES["qc2"]
ACTIVE_ANNOTATOR_STATUSES: list[str] = [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING, JobStatus.REWORK]
SUBMITTED_OR_DONE_STATUSES: list[str] = [
    JobStatus.PENDING_QC1,
    JobStatus.QC1_REVIEWING,
    JobStatus.QC1_PASSED,
    JobStatus.PENDING_QC2,
    JobStatus.APPROVED,
    JobStatus.DELIVERED,
]


class Job(models.Model):
    if TYPE_CHECKING:
        id: int
        project_id: int
        batch_id: int
        annotator_id: int | None
        qc1_reviewer_id: int | None
        events: Any
        review_errors: Any
        audit_samples: Any
        annotator_requests: Any
        daily_outputs: Any

        def get_status_display(self) -> str: ...
        def get_rework_scope_display(self) -> str: ...
        def get_first_qc1_result_display(self) -> str: ...
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="jobs")
    batch = models.ForeignKey("projects.Batch", on_delete=models.CASCADE, related_name="jobs")
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=30, choices=JobStatus.choices, default=JobStatus.PENDING_ANNOTATION)

    annotator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="annotated_jobs"
    )
    qc1_reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="qc1_jobs"
    )
    deadline = models.DateTimeField(null=True, blank=True)
    rework_round = models.PositiveSmallIntegerField(default=0)
    total_rework_rounds = models.PositiveSmallIntegerField(
        default=0, help_text="Tổng số vòng rework bất biến (không đặt lại khi gỡ escalation)"
    )
    first_qc1_result = models.CharField(
        max_length=10, choices=FirstQc1Result.choices, blank=True, default=""
    )
    rework_scope = models.CharField(max_length=16, choices=ReworkScope.choices, default=ReworkScope.PARTIAL)
    is_escalated = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)

    frame_count = models.PositiveIntegerField(default=0)
    object_count = models.PositiveIntegerField(default=0, help_text="Số object/cuboid (đồng bộ từ CVAT)")
    last_counted_objects = models.PositiveIntegerField(
        default=0, help_text="Mốc object_count đã ghi vào sổ sản lượng ngày (tránh cộng đúp)"
    )
    round_credited_objects = models.PositiveIntegerField(
        default=0, help_text="Sản lượng đã ghi nhận trong vòng làm/rework hiện tại"
    )
    target_object_count = models.PositiveIntegerField(
        default=0, help_text="Tổng object-frame mục tiêu của job (TD03/TD10)"
    )

    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # --- Liên kết CVAT (CVAT là nguồn dữ liệu annotation; trạng thái do Vanohub quản lý) ---
    cvat_job_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    cvat_task_id = models.PositiveIntegerField(null=True, blank=True)
    cvat_stage = models.CharField(max_length=30, blank=True)
    cvat_state = models.CharField(max_length=30, blank=True)
    source_missing = models.BooleanField(
        default=False, help_text="True nếu CVAT job không còn tồn tại ở lần đồng bộ gần nhất"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["deadline", "id"]
        indexes = [models.Index(fields=["project", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cvat_job_id__isnull=True) | models.Q(cvat_job_id__gte=1),
                name="job_cvat_job_id_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(cvat_task_id__isnull=True) | models.Q(cvat_task_id__gte=1),
                name="job_cvat_task_id_positive",
            ),
        ]

    def clean(self):
        super().clean()
        if self.batch_id and self.project_id and self.batch.dataset.project_id != self.project_id:
            raise ValidationError({"batch": "Batch không thuộc cùng dự án với Job."})

    def __str__(self):
        return self.name

    @property
    def is_overdue(self):
        return bool(self.deadline and self.deadline < timezone.now() and self.status in OPEN_STATUSES)

    @property
    def due_state(self):
        if not self.deadline or self.status not in OPEN_STATUSES:
            return "none"
        now = timezone.now()
        if self.deadline < now:
            return "overdue"
        if self.deadline <= now + timedelta(hours=24):
            return "soon"
        return "normal"

    @property
    def hours_remaining(self):
        if not self.deadline or self.status not in OPEN_STATUSES:
            return None
        delta = (self.deadline - timezone.now()).total_seconds() / 3600
        return round(delta, 1)

    @property
    def overdue_hours(self):
        """DH03: chưa xong thì max(0, hiện tại - hạn); đã xong thì max(0, hoàn tất - hạn)."""
        if not self.deadline:
            return 0.0
        ref = timezone.now() if self.status in OPEN_STATUSES else (self.submitted_at or self.updated_at or timezone.now())
        delta = (ref - self.deadline).total_seconds() / 3600
        return round(max(0.0, delta), 1)

    @property
    def is_on_time(self):
        """DH05: hoàn tất/nộp <= deadline."""
        if not self.deadline or self.status not in SUBMITTED_OR_DONE_STATUSES:
            return None
        ref = self.submitted_at or self.updated_at
        return bool(ref is not None and ref <= self.deadline)

    @property
    def progress_percent(self):
        if self.status in SUBMITTED_OR_DONE_STATUSES:
            return 100
        if self.target_object_count > 0:
            return min(100, round(self.object_count * 100 / self.target_object_count))
        return 0

    @property
    def stage(self):
        for stage, statuses in STAGE_STATUSES.items():
            if self.status in statuses:
                return stage
        return "done"

    def cvat_url(self):
        base = getattr(settings, "CVAT_PUBLIC_URL", "")
        if not (base and self.cvat_job_id and self.cvat_task_id):
            return None
        return f"{base.rstrip('/')}/tasks/{self.cvat_task_id}/jobs/{self.cvat_job_id}"


class AnnotatorRequest(models.Model):
    """Yêu cầu của Annotator (TD13): phản hồi lỗi QC1 hoặc báo dữ liệu bị chặn."""

    class RequestType(models.TextChoices):
        ERROR_DISPUTE = "error_dispute", "Phản hồi lỗi"
        DATA_ISSUE = "data_issue", "Dữ liệu bị chặn"

    class Status(models.TextChoices):
        PENDING_PM = "pending_pm", "Đang chờ PM"
        RESOLVED = "resolved", "Đã giải quyết"
        REJECTED = "rejected", "Từ chối"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="annotator_requests")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="annotator_requests")
    review_error = models.ForeignKey(
        "quality.ReviewError", on_delete=models.SET_NULL, null=True, blank=True, related_name="disputes"
    )
    request_type = models.CharField(max_length=20, choices=RequestType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PM)
    title = models.CharField(max_length=255)
    reason = models.TextField()
    progress_note = models.TextField(blank=True, default="")
    resolution_note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="annotator_requests"
    )
    handler = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="handled_requests"
    )
    handler_role = models.CharField(max_length=16, blank=True, default="PM")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["project", "created_by", "status"])]

    if TYPE_CHECKING:
        id: int
        project_id: int
        job_id: int
        review_error_id: int | None
        created_by_id: int
        handler_id: int | None

        def get_request_type_display(self) -> str: ...
        def get_status_display(self) -> str: ...

    def __str__(self):
        return f"{self.get_request_type_display()} · {self.job.name}"


class DailyOutputRecord(models.Model):
    """Sổ sản lượng theo ngày của Annotator (SL01/SL03/SL04/SL06, CS02/CS03).

    Ghi nhận số cuboid 3D / object 2D làm được theo đúng ngày thực hiện — tính cả khi chưa QC
    (qua đồng bộ CVAT) và giữ nguyên sau khi QC (không cộng đúp, không trừ ngược ngày cũ,
    không tính cơ chế cover hộ).
    """

    class Source(models.TextChoices):
        SUBMIT = "submit", "Nộp bài"
        CVAT_SYNC = "cvat_sync", "Đồng bộ CVAT"

    if TYPE_CHECKING:
        id: int
        project_id: int
        job_id: int
        user_id: int

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="daily_outputs")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="daily_outputs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="daily_outputs")
    work_date = models.DateField(help_text="Ngày làm việc theo múi giờ người thực hiện")
    is_rework = models.BooleanField(default=False)
    rework_round = models.PositiveSmallIntegerField(default=0)
    object_count = models.PositiveIntegerField(help_text="Số cuboid/object-frame làm thêm trong lần ghi nhận")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.SUBMIT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-work_date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["project", "user", "work_date"]),
            models.Index(fields=["project", "work_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(object_count__gte=1),
                name="daily_output_object_count_gte_1",
            ),
        ]

    def __str__(self):
        kind = "rework" if self.is_rework else "first_pass"
        return f"{self.work_date} · {self.user_id} · +{self.object_count} ({kind})"


def record_daily_output(
    *,
    job: Job,
    user: Any,
    object_count: int,
    is_rework: bool,
    rework_round: int,
    source: str,
    at: Any = None,
) -> DailyOutputRecord | None:
    if user is None or object_count <= 0:
        return None
    return DailyOutputRecord.objects.create(
        project_id=job.project_id,
        job=job,
        user=user,
        work_date=user_work_date(user, at=at),
        is_rework=is_rework,
        rework_round=rework_round,
        object_count=object_count,
        source=source,
    )
