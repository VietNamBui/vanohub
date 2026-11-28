from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SamplingMethod(models.TextChoices):
    RANDOM = "random", "Random sampling"
    STRATIFIED = "stratified", "Stratified sampling"


class StratifyBy(models.TextChoices):
    ANNOTATOR = "annotator", "Theo annotator"
    QC1_REVIEWER = "qc1_reviewer", "Theo người QC1"
    DATASET = "dataset", "Theo project"


class EscalationPolicy(models.TextChoices):
    BLOCK = "block", "Khoá job chờ PM xử lý"
    WARN_ONLY = "warn_only", "Chỉ cảnh báo (vẫn cho sửa)"


class Project(models.Model):
    """ĐƠN VỊ QUẢN LÝ CAO NHẤT — ứng với MỘT CVAT ORGANIZATION (hiển thị là "Organization").

    Ánh xạ (chốt 2026-11-25), tên model giữ nguyên để không phải đổi toàn bộ code:
        Project (model)  ↔ CVAT Organization   — vai trò, team, cấu hình QC theo đơn vị này
        Dataset (model)  ↔ CVAT Project        — bộ nhãn đặt ở đây
        Batch (model)    ↔ CVAT Task           — deadline, team phụ trách, xác nhận QC2 & bàn giao theo task
        Job              ↔ CVAT Job
    PM = thành viên Owner / Maintainer của CVAT organization (đã liên kết VanoHub).
    Project CVAT ngoài organization (Personal workspace) không đưa lên VanoHub.
    """

    if TYPE_CHECKING:
        id: int
        datasets: Any
        batches: Any
        jobs: Any
        teams: Any
        error_categories: Any
        role_assignments: Any

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- Liên kết CVAT organization --- (null = tạo tay / dữ liệu demo, không gắn CVAT)
    cvat_org_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    cvat_org_slug = models.CharField(max_length=60, blank=True)
    cvat_synced_at = models.DateTimeField(null=True, blank=True)

    # --- Cấu hình Rework & Sampling ---
    max_rework_rounds = models.PositiveSmallIntegerField(
        default=3, help_text="Vượt số vòng này thì job bị Escalated."
    )
    escalation_policy = models.CharField(
        max_length=20,
        choices=EscalationPolicy.choices,
        default=EscalationPolicy.BLOCK,
        help_text="Khoá cứng chờ PM gỡ hoặc chỉ cảnh báo vẫn cho sửa (PM cấu hình).",
    )
    annotator_wip_limit = models.PositiveSmallIntegerField(
        default=2,
        validators=[MinValueValidator(1), MaxValueValidator(50)],
        help_text="Số job tối đa mỗi annotator giữ cùng lúc.",
    )
    sampling_method = models.CharField(
        max_length=20, choices=SamplingMethod.choices, default=SamplingMethod.RANDOM
    )
    # QC2 (chốt 2026-11-25): MỌI job vào QC2 được kiểm ngẫu nhiên sampling_rate % số frame của job.
    # sampling_method / stratify_by không còn dùng (giữ cột để không mất lịch sử cấu hình cũ).
    sampling_rate = models.PositiveSmallIntegerField(
        default=20,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text="% số frame của mỗi job được QC2 kiểm.",
    )
    stratify_by = models.CharField(max_length=20, choices=StratifyBy.choices, default=StratifyBy.ANNOTATOR)

    # --- Ngưỡng chất lượng ---
    quality_cl_threshold = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    defect_rate_threshold = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    kpi_annotation_target = models.PositiveIntegerField(null=True, blank=True, help_text="Object / ngày")
    kpi_qc1_target = models.PositiveIntegerField(null=True, blank=True, help_text="Job / ngày")
    kpi_qc2_target = models.PositiveIntegerField(null=True, blank=True, help_text="Job / ngày")

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_rework_rounds__gte=1),
                name="project_max_rework_rounds_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(annotator_wip_limit__gte=1, annotator_wip_limit__lte=50),
                name="project_wip_limit_1_to_50",
            ),
            models.CheckConstraint(
                condition=models.Q(sampling_rate__gte=1, sampling_rate__lte=100),
                name="project_sampling_rate_1_to_100",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(quality_cl_threshold__isnull=True)
                    | models.Q(quality_cl_threshold__gte=0, quality_cl_threshold__lte=100)
                ),
                name="project_quality_cl_threshold_0_to_100",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(defect_rate_threshold__isnull=True)
                    | models.Q(defect_rate_threshold__gte=0, defect_rate_threshold__lte=100)
                ),
                name="project_defect_rate_threshold_0_to_100",
            ),
        ]

    def __str__(self):
        return self.name


class DataStatus(models.TextChoices):
    ACTIVE = "active", "Đang xử lý"
    LOCKED = "locked", "Đã khoá"
    DELIVERED = "delivered", "Đã bàn giao"


class Dataset(models.Model):
    """Ứng với MỘT CVAT PROJECT trong organization (hiển thị là "Project"). Tạo bằng đồng bộ từ CVAT."""

    if TYPE_CHECKING:
        id: int
        project_id: int
        batches: Any
        jobs: Any

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="datasets")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=DataStatus.choices, default=DataStatus.ACTIVE)
    cvat_project_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Không ràng buộc trùng tên: tên lấy từ CVAT, CVAT cho phép trùng.
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cvat_project_id__isnull=True) | models.Q(cvat_project_id__gte=1),
                name="dataset_cvat_project_id_positive",
            ),
        ]

    def __str__(self):
        return self.name


class Batch(models.Model):
    """Ứng với MỘT CVAT TASK (hiển thị là "Task"). Tạo bằng đồng bộ từ CVAT.

    Deadline, team phụ trách, xác nhận chuyển QC2 và bàn giao tính theo task.
    `project` = organization (giữ để lọc / phân quyền nhanh), `dataset` = CVAT project chứa task.
    """

    if TYPE_CHECKING:
        id: int
        project_id: int
        dataset_id: int
        team_id: int | None
        qc2_confirmed_by_id: int | None
        jobs: Any
        audits: Any
        deliveries: Any
        job_count: int
        done_count: int
        approved_count: int
        qc1_passed_count: int
        blocking_qc2_count: int
        pending_qc2_count: int
        escalated_count: int
        pending_qc2_samples: int
        locked_jobs: int

    class SyncStatus(models.TextChoices):
        IDLE = "", "Chưa đồng bộ"
        OK = "ok", "Thành công"
        ERROR = "error", "Lỗi"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="batches")
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="batches")
    cvat_task_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    source_missing = models.BooleanField(
        default=False, help_text="True nếu CVAT task không còn tồn tại ở lần đồng bộ gần nhất"
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(
        max_length=16, choices=SyncStatus.choices, blank=True, default=SyncStatus.IDLE
    )
    last_sync_error = models.TextField(blank=True, default="")
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=DataStatus.choices, default=DataStatus.ACTIVE)
    deadline = models.DateTimeField(null=True, blank=True)
    team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="batches")
    qc2_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    qc2_confirmed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Không ràng buộc trùng tên: tên lấy từ CVAT task.
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(cvat_task_id__isnull=True) | models.Q(cvat_task_id__gte=1),
                name="batch_cvat_task_id_positive",
            ),
        ]

    def __str__(self):
        return self.name


class Delivery(models.Model):
    """Một lần bàn giao một Task (Batch) cho khách hàng."""

    if TYPE_CHECKING:
        id: int
        project_id: int
        batch_id: int
        delivered_by_id: int | None

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="deliveries")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="deliveries")
    recipient = models.CharField(max_length=200, blank=True, default="", help_text="Người nhận / khách hàng")
    output_path = models.CharField(max_length=500, blank=True, default="", help_text="Đường dẫn đầu ra / link bàn giao")
    note = models.TextField(blank=True)
    client_feedback = models.TextField(blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    delivered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-delivered_at"]
        constraints = [
            models.UniqueConstraint(fields=["batch"], name="unique_delivery_per_batch"),
        ]

    def __str__(self):
        return f"Delivery #{self.pk} · {self.batch}"


class ActivityLog(models.Model):
    """Nhật ký mọi thao tác quan trọng trong organization. Cũng là "dòng thời gian" của Job."""

    if TYPE_CHECKING:
        id: int
        project_id: int
        actor_id: int | None
        job_id: int | None

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="activity_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    action = models.CharField(max_length=60)  # vd. "job.assign", "batch.lock"
    target_type = models.CharField(max_length=40)
    target_id = models.PositiveIntegerField(null=True)
    target_label = models.CharField(max_length=255, blank=True)
    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, null=True, blank=True, related_name="events")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["project", "-created_at"]),
            models.Index(fields=["project", "action", "created_at"]),
        ]

    def __str__(self):
        return f"{self.action} · {self.target_label}"

    @classmethod
    def record(cls, *, project, actor, action, target, before=None, after=None, note="", job=None):
        return cls.objects.create(
            project=project,
            actor=actor if actor and actor.is_authenticated else None,
            action=action,
            target_type=target.__class__.__name__.lower(),
            target_id=target.pk,
            target_label=str(target)[:255],
            job=job,
            before=before,
            after=after,
            note=note,
        )


class Announcement(models.Model):
    """Thông báo PM gửi trong organization. Gửi theo vai trò và/hoặc team."""

    if TYPE_CHECKING:
        id: int
        project_id: int
        sender_id: int | None
        target_team_id: int | None

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="announcements")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    target_roles = models.JSONField(default=list, blank=True, help_text="Rỗng = mọi vai trò")
    target_team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Announcement #{self.pk} · {self.project}"


class AnnouncementRead(models.Model):
    """Đánh dấu đã đọc thông báo chung (Announcement) theo từng người dùng."""

    if TYPE_CHECKING:
        id: int
        announcement_id: int
        user_id: int

    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="announcement_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["announcement", "user"], name="unique_announcement_read"),
        ]

    def __str__(self):
        return f"{self.user} read Announcement #{self.announcement_id}"


class Guideline(models.Model):
    """Hướng dẫn gán nhãn có phiên bản. Mỗi lần lưu tạo một phiên bản mới."""

    if TYPE_CHECKING:
        id: int
        project_id: int
        created_by_id: int | None

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="guidelines")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    content = models.TextField(help_text="Markdown")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [
            models.UniqueConstraint(fields=["project", "version"], name="unique_guideline_version"),
            models.CheckConstraint(condition=models.Q(version__gte=1), name="guideline_version_gte_1"),
        ]

    def __str__(self):
        return f"v{self.version} · {self.title}"


class UserNotification(models.Model):
    """Thông báo cá nhân theo sự kiện hệ thống: giao việc, trả sửa, cần duyệt, escalated, hạn, phản hồi."""

    if TYPE_CHECKING:
        id: int
        recipient_id: int
        project_id: int
        batch_id: int | None
        job_id: int | None

    class Category(models.TextChoices):
        ASSIGNED = "assigned", "Được giao việc"
        REWORK = "rework", "Trả sửa (Rework)"
        REVIEW_NEEDED = "review_needed", "Cần duyệt"
        ESCALATED = "escalated", "Escalated (vượt giới hạn)"
        DEADLINE = "deadline", "Sắp / quá hạn"
        DISPUTE = "dispute", "Phản hồi lỗi / Yêu cầu"
        QC_PASS = "qc_pass", "Đạt QC1"
        ANNOUNCEMENT = "announcement", "Thông báo"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="notifications")
    batch = models.ForeignKey("projects.Batch", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    job = models.ForeignKey("jobs.Job", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.ANNOUNCEMENT)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    action_url = models.CharField(max_length=255, blank=True, default="")
    is_read = models.BooleanField(default=False)
    is_pinned_pending = models.BooleanField(default=False, help_text="Treo tới khi xử lý xong")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["recipient", "project", "is_read"])]

    def __str__(self):
        return f"{self.recipient} · {self.title}"
