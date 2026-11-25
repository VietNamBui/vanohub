from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class JobStatus(models.TextChoices):
    """ĐỀ XUẤT (đã được đồng ý dùng tạm, chưa chốt chính thức).

    L3 (TL xác nhận lên QC2) và L4 (PM accept batch) bỏ qua trong MVP:
    QC1 pass → Chờ QC2; QC2 xong → Đã duyệt.
    """

    PENDING_ANNOTATION = "pending_annotation", "Chờ annotate"
    ANNOTATING = "annotating", "Đang annotate"
    PENDING_QC1 = "pending_qc1", "Chờ QC1"
    QC1_REVIEWING = "qc1_reviewing", "Đang QC1"
    REWORK = "rework", "Rework"
    PENDING_QC2 = "pending_qc2", "Chờ QC2"
    APPROVED = "approved", "Đã duyệt"
    DELIVERED = "delivered", "Đã bàn giao"


class ReworkScope(models.TextChoices):
    PARTIAL = "partial", "Sửa một phần"
    FULL = "full", "Sửa toàn job"


# Nhóm trạng thái theo stage, dùng cho tab lọc và Data Queue.
STAGE_STATUSES = {
    "annotation": [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING, JobStatus.REWORK],
    "qc1": [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING],
    "qc2": [JobStatus.PENDING_QC2],
    "done": [JobStatus.APPROVED, JobStatus.DELIVERED],
}
OPEN_STATUSES = STAGE_STATUSES["annotation"] + STAGE_STATUSES["qc1"] + STAGE_STATUSES["qc2"]
ACTIVE_ANNOTATOR_STATUSES = [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING, JobStatus.REWORK]
SUBMITTED_OR_DONE_STATUSES = [
    JobStatus.PENDING_QC1,
    JobStatus.QC1_REVIEWING,
    JobStatus.PENDING_QC2,
    JobStatus.APPROVED,
    JobStatus.DELIVERED,
]


class Job(models.Model):
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
    rework_scope = models.CharField(max_length=16, choices=ReworkScope.choices, default=ReworkScope.PARTIAL)
    is_escalated = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)

    frame_count = models.PositiveIntegerField(default=0)
    object_count = models.PositiveIntegerField(default=0, help_text="Số object/cuboid (đồng bộ từ CVAT)")
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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["deadline", "id"]
        indexes = [models.Index(fields=["project", "status"])]

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
        if not self.deadline:
            return None
        delta = (self.deadline - timezone.now()).total_seconds() / 3600
        return round(delta, 1)

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
        PENDING_TL = "pending_tl", "Đang chờ TL"
        PENDING_PM = "pending_pm", "Đang chờ PM"
        RESOLVED = "resolved", "Đã giải quyết"
        REJECTED = "rejected", "Từ chối"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="annotator_requests")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="annotator_requests")
    review_error = models.ForeignKey(
        "quality.ReviewError", on_delete=models.SET_NULL, null=True, blank=True, related_name="disputes"
    )
    request_type = models.CharField(max_length=20, choices=RequestType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_TL)
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
    handler_role = models.CharField(max_length=16, blank=True, default="TL")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["project", "created_by", "status"])]

    def __str__(self):
        return f"{self.get_request_type_display()} · {self.job.name}"
