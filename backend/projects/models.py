from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class SamplingMethod(models.TextChoices):
    RANDOM = "random", "Random sampling"
    STRATIFIED = "stratified", "Stratified sampling"


class StratifyBy(models.TextChoices):
    ANNOTATOR = "annotator", "Theo annotator"
    QC1_REVIEWER = "qc1_reviewer", "Theo người QC1"
    DATASET = "dataset", "Theo dataset"


class Project(models.Model):
    """ĐƠN VỊ QUẢN LÝ CAO NHẤT — ứng với MỘT CVAT ORGANIZATION (hiển thị là "Organization").

    Ánh xạ (chốt 2026-11-25), tên model giữ nguyên để không phải đổi toàn bộ code:
        Project (model)  ↔ CVAT Organization   — vai trò, team, cấu hình QC theo đơn vị này
        Dataset (model)  ↔ CVAT Project        — bộ nhãn đặt ở đây
        Batch (model)    ↔ CVAT Task           — deadline, team phụ trách, bàn giao theo task
        Job              ↔ CVAT Job
    PM = thành viên Owner / Maintainer của CVAT organization (đã liên kết VanoHub).
    Project CVAT ngoài organization (Personal workspace) không đưa lên VanoHub.

    Các trường cấu hình (rework, sampling, ngưỡng) đặt thẳng trên Project vì mỗi dự án
    có đúng một bộ cấu hình — đơn giản hơn tách bảng riêng. Giá trị mặc định là ĐỀ XUẤT.
    """

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

    # --- Cấu hình Rework & Sampling (PM-10) ---
    max_rework_rounds = models.PositiveSmallIntegerField(
        default=3, help_text="Vượt số vòng này thì job bị Escalated."
    )
    sampling_method = models.CharField(
        max_length=20, choices=SamplingMethod.choices, default=SamplingMethod.RANDOM
    )
    # QC2 (chốt 2026-11-25): MỌI job qua QC1 đều được audit, kiểm ngẫu nhiên sampling_rate % số frame của job.
    # sampling_method / stratify_by không còn dùng (giữ cột để không mất lịch sử cấu hình cũ).
    sampling_rate = models.PositiveSmallIntegerField(
        default=20, validators=[MinValueValidator(1), MaxValueValidator(100)], help_text="% số frame của mỗi job được QC2 kiểm."
    )
    stratify_by = models.CharField(max_length=20, choices=StratifyBy.choices, default=StratifyBy.ANNOTATOR)

    # --- Ngưỡng chất lượng (PM-11). Công thức KPI chưa chốt → chỉ lưu ngưỡng. ---
    quality_cl_threshold = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    defect_rate_threshold = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    kpi_annotation_target = models.PositiveIntegerField(null=True, blank=True, help_text="Object / ngày")
    kpi_qc1_target = models.PositiveIntegerField(null=True, blank=True, help_text="Job / ngày")
    kpi_qc2_target = models.PositiveIntegerField(null=True, blank=True, help_text="Job / ngày")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class DataStatus(models.TextChoices):
    ACTIVE = "active", "Đang xử lý"
    LOCKED = "locked", "Đã khoá"
    DELIVERED = "delivered", "Đã bàn giao"


class Dataset(models.Model):
    """Ứng với MỘT CVAT PROJECT trong organization (hiển thị là "Project"). Tạo bằng đồng bộ từ CVAT."""

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

    def __str__(self):
        return self.name


class Batch(models.Model):
    """Ứng với MỘT CVAT TASK (hiển thị là "Task"). Tạo bằng đồng bộ từ CVAT.

    Deadline, team phụ trách (mỗi team một task) và bàn giao tính theo task.
    `project` = organization (giữ để lọc / phân quyền nhanh), `dataset` = CVAT project chứa task.
    """

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="batches")
    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="batches")
    cvat_task_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=DataStatus.choices, default=DataStatus.ACTIVE)
    deadline = models.DateTimeField(null=True, blank=True)
    # Team phụ trách batch. Chỉ ghi nhận (chưa tự giao job cho thành viên team).
    team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="batches")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Không ràng buộc trùng tên: tên lấy từ CVAT task.
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Delivery(models.Model):
    """Một lần bàn giao một Batch cho khách hàng."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="deliveries")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="deliveries")
    note = models.TextField(blank=True)
    client_feedback = models.TextField(blank=True)
    delivered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    delivered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-delivered_at"]


class ActivityLog(models.Model):
    """Nhật ký mọi thao tác quan trọng trong dự án (PM-20). Cũng là "dòng thời gian" của Job."""

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
        indexes = [models.Index(fields=["project", "-created_at"])]

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
    """Thông báo PM gửi trong dự án (PM-12). Gửi theo vai trò và/hoặc team."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="announcements")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    target_roles = models.JSONField(default=list, blank=True, help_text="Rỗng = mọi vai trò")
    target_team = models.ForeignKey("teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Guideline(models.Model):
    """Hướng dẫn gán nhãn có phiên bản (PM-18). Mỗi lần lưu tạo một phiên bản mới."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="guidelines")
    version = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    content = models.TextField(help_text="Markdown")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="unique_guideline_version")]
