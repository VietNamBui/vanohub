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


# Nhóm trạng thái theo stage, dùng cho tab lọc và Data Queue.
STAGE_STATUSES = {
    "annotation": [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING, JobStatus.REWORK],
    "qc1": [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING],
    "qc2": [JobStatus.PENDING_QC2],
    "done": [JobStatus.APPROVED, JobStatus.DELIVERED],
}
OPEN_STATUSES = STAGE_STATUSES["annotation"] + STAGE_STATUSES["qc1"] + STAGE_STATUSES["qc2"]


class Job(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="jobs")
    # project = organization; dataset = CVAT project; batch = CVAT task (xem projects/models.py).
    dataset = models.ForeignKey("projects.Dataset", on_delete=models.CASCADE, related_name="jobs")
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
    is_escalated = models.BooleanField(default=False)
    is_locked = models.BooleanField(default=False)

    frame_count = models.PositiveIntegerField(default=0)
    object_count = models.PositiveIntegerField(default=0, help_text="Số object/cuboid (đồng bộ từ CVAT)")

    # --- Liên kết CVAT (CVAT là nguồn dữ liệu annotation; trạng thái do Vanohub quản lý) ---
    cvat_job_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    cvat_task_id = models.PositiveIntegerField(null=True, blank=True)
    # Frame đầu của job trong task (CVAT đánh số frame theo task) — để chỉ đúng frame cần QC2 kiểm.
    cvat_start_frame = models.PositiveIntegerField(default=0)
    cvat_stage = models.CharField(max_length=30, blank=True)
    cvat_state = models.CharField(max_length=30, blank=True)
    # Assignee hiện tại bên CVAT (ID user CVAT) — để biết đã đồng bộ người giữ job sang CVAT chưa.
    cvat_assignee_id = models.PositiveIntegerField(null=True, blank=True)

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
