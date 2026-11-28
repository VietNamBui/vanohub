from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.utils import timezone


class CvatAccount(models.Model):
    """Liên kết một tài khoản VanoHub với một tài khoản CVAT (mỗi người tự liên kết).

    Chỉ lưu ID và username bên CVAT. Access token người dùng dán vào chỉ dùng một lần
    để xác minh rồi bỏ đi — VanoHub giao việc trên CVAT bằng tài khoản hệ thống (backend/.env).
    """

    if TYPE_CHECKING:
        id: int
        user_id: int

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cvat_account")
    # unique: một tài khoản CVAT không được gắn cho hai người VanoHub.
    cvat_user_id = models.PositiveIntegerField(unique=True)
    cvat_username = models.CharField(max_length=150)
    linked_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} ⇄ CVAT {self.cvat_username} (#{self.cvat_user_id})"


class CvatAssigneeOutbox(models.Model):
    """Hàng đợi bền vững để đẩy assignee từ VanoHub sang CVAT kèm backoff và kiểm soát stale-write."""

    class Status(models.TextChoices):
        PENDING = "pending", "Chờ đẩy"
        PROCESSING = "processing", "Đang xử lý"
        DONE = "done", "Hoàn tất"
        DEAD = "dead", "Ngưng thử lại"

    if TYPE_CHECKING:
        id: int
        project_id: int
        job_id: int
        target_holder_id: int | None

        def get_status_display(self) -> str: ...

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="cvat_assignee_outbox"
    )
    job = models.ForeignKey(
        "jobs.Job", on_delete=models.CASCADE, related_name="cvat_assignee_outbox"
    )
    cvat_job_id = models.PositiveIntegerField()
    target_holder = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    target_cvat_user_id = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_retry_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["next_retry_at", "id"]
        indexes = [
            models.Index(fields=["status", "next_retry_at", "id"], name="cvat_outbox_due_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["job"],
                condition=models.Q(status="pending"),
                name="unique_pending_cvat_outbox_per_job",
            ),
            models.CheckConstraint(
                condition=models.Q(cvat_job_id__gte=1),
                name="cvat_outbox_cvat_job_id_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(target_cvat_user_id__isnull=True) | models.Q(target_cvat_user_id__gte=1),
                name="cvat_outbox_target_cvat_user_id_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["pending", "processing", "done", "dead"]),
                name="cvat_outbox_valid_status",
            ),
        ]

    def __str__(self) -> str:
        return f"Outbox #{self.pk} · job={self.job_id} (cvat={self.cvat_job_id}) · {self.status}"
