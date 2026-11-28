from __future__ import annotations

from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    class Dimension(str, models.Choices):
        DIM_3D = "3d"
        DIM_2D = "2d"

    class BatchDimension(str, models.Choices):
        ALL = "all"
        DIM_3D = "3d"
        DIM_2D = "2d"

    class PipelineStep(str, models.Choices):
        PRE_QC = "pre_qc"
        ANNOTATOR = "annotator"
        L1_QC = "l1_qc"
        L2_QC = "l2_qc"
        DEPT_HEAD = "dept_head"
        COMPLETED = "completed"

    class DeliverStatus(str, models.Choices):
        NOT_READY = "not_ready"
        READY = "ready_to_deliver"
        IN_BATCH = "in_batch"
        DELIVERED = "delivered"
        ACCEPTED = "accepted"
        REJECTED = "client_rejected"
else:
    class Dimension(models.TextChoices):
        DIM_3D = "3d", "3D (LiDAR Cuboid)"
        DIM_2D = "2d", "2D (BBox / Landmark / Polygon)"

    class BatchDimension(models.TextChoices):
        ALL = "all", "Tất cả (2D & 3D)"
        DIM_3D = "3d", "3D"
        DIM_2D = "2d", "2D"

    class PipelineStep(models.TextChoices):
        PRE_QC = "pre_qc", "Pre-QC"
        ANNOTATOR = "annotator", "Annotation"
        L1_QC = "l1_qc", "QC1 (L1)"
        L2_QC = "l2_qc", "QC2 (L2)"
        DEPT_HEAD = "dept_head", "Dept Head"
        COMPLETED = "completed", "Completed"

    class DeliverStatus(models.TextChoices):
        NOT_READY = "not_ready", "Chưa hoàn tất QC"
        READY = "ready_to_deliver", "Sẵn sàng bàn giao"
        IN_BATCH = "in_batch", "Đã gom lô"
        DELIVERED = "delivered", "Đã bàn giao"
        ACCEPTED = "accepted", "Khách nghiệm thu"
        REJECTED = "client_rejected", "Khách trả lại"


class SyncedTask(models.Model):
    cvat_task_id = models.PositiveIntegerField(unique=True, db_index=True)
    name = models.CharField(max_length=255)
    project_name = models.CharField(max_length=255, blank=True, default="")
    dimension = models.CharField(
        max_length=16,
        choices=Dimension.choices,
        default=Dimension.DIM_3D,
        db_index=True,
    )
    annotation_type = models.CharField(max_length=32, default="cuboid", db_index=True)
    total_frames = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cvat_task_id"]

    def __str__(self) -> str:
        return f"Task #{self.cvat_task_id}: {self.name}"


class SyncedJob(models.Model):
    cvat_job_id = models.PositiveIntegerField(unique=True, db_index=True)
    task = models.ForeignKey(SyncedTask, on_delete=models.CASCADE, related_name="jobs")
    start_frame = models.PositiveIntegerField(default=0)
    stop_frame = models.PositiveIntegerField(default=0)
    frame_count = models.PositiveIntegerField(default=0)

    pipeline_step = models.CharField(
        max_length=24,
        choices=PipelineStep.choices,
        default=PipelineStep.ANNOTATOR,
        db_index=True,
    )
    work_state = models.CharField(max_length=32, default="new", db_index=True)
    review_round = models.PositiveIntegerField(default=1)
    rework_count = models.PositiveIntegerField(default=0)

    annotator_username = models.CharField(max_length=150, blank=True, default="", db_index=True)
    l1_qc_username = models.CharField(max_length=150, blank=True, default="", db_index=True)
    l2_qc_username = models.CharField(max_length=150, blank=True, default="", db_index=True)
    dept_head_username = models.CharField(max_length=150, blank=True, default="", db_index=True)

    open_issues = models.PositiveIntegerField(default=0)
    addressed_issues = models.PositiveIntegerField(default=0)
    escalations = models.PositiveIntegerField(default=0)
    disputes = models.PositiveIntegerField(default=0)
    resolved_issues = models.PositiveIntegerField(default=0)

    inspected_cuboids = models.PositiveIntegerField(default=0)
    required_cuboids = models.PositiveIntegerField(default=0)
    total_cuboids = models.PositiveIntegerField(default=0)
    l2_required = models.BooleanField(default=True)
    threshold_met = models.BooleanField(default=True)

    deliver_status = models.CharField(
        max_length=24,
        choices=DeliverStatus.choices,
        default=DeliverStatus.NOT_READY,
        db_index=True,
    )
    step_entered_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["cvat_job_id"]

    @property
    def cycle_stage(self) -> str:
        """Maps internal CVAT steps to the 5-stage Data Cycle: job -> annotation -> qc1 -> qc2 -> deliver."""
        if self.deliver_status in (
            DeliverStatus.IN_BATCH,
            DeliverStatus.DELIVERED,
            DeliverStatus.ACCEPTED,
            DeliverStatus.REJECTED,
        ) or self.pipeline_step == PipelineStep.COMPLETED:
            return "deliver"
        if self.pipeline_step == PipelineStep.PRE_QC:
            return "job"
        if self.pipeline_step == PipelineStep.ANNOTATOR:
            return "annotation"
        if self.pipeline_step == PipelineStep.L1_QC:
            return "qc1"
        return "qc2"  # l2_qc or dept_head

    @property
    def dimension(self) -> str:
        return self.task.dimension

    @property
    def inspected_items(self) -> int:
        return self.inspected_cuboids

    @property
    def required_items(self) -> int:
        return self.required_cuboids

    @property
    def total_items(self) -> int:
        return self.total_cuboids

    def __str__(self) -> str:
        return f"Job #{self.cvat_job_id} ({self.pipeline_step})"


class StageTransition(models.Model):
    job = models.ForeignKey(SyncedJob, on_delete=models.CASCADE, related_name="transitions")
    event_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    event_name = models.CharField(max_length=48, blank=True, default="")
    action = models.CharField(max_length=48, blank=True, default="")
    from_step = models.CharField(max_length=24, db_index=True)
    to_step = models.CharField(max_length=24, db_index=True)
    actor_username = models.CharField(max_length=150, blank=True, default="", db_index=True)
    actor_role = models.CharField(max_length=24, blank=True, default="", db_index=True)
    reason = models.TextField(blank=True, default="")
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    duration_prev_step_sec = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]

    @property
    def is_rework_return(self) -> bool:
        return (
            self.event_name in ("stage.returned", "stage.rejected")
            or "return" in self.action.lower()
            or "reject" in self.action.lower()
            or (self.from_step in ("l1_qc", "l2_qc", "dept_head") and self.to_step in ("annotator", "l1_qc"))
        )


class JobQualitySnapshot(models.Model):
    """Per-job quality, diff, and anti-gaming signals synced/computed from CVAT snapshots."""

    job = models.OneToOneField(SyncedJob, on_delete=models.CASCADE, related_name="quality")

    total_source_boxes = models.PositiveIntegerField(default=0)
    added_boxes = models.PositiveIntegerField(default=0)
    deleted_boxes = models.PositiveIntegerField(default=0)
    unchanged_boxes = models.PositiveIntegerField(default=0)
    modified_boxes = models.PositiveIntegerField(default=0)

    # 1. Low-touch / low-effort signals
    touched_rate = models.FloatField(default=0.0)
    source_box_touch_rate = models.FloatField(default=0.0)
    effort_score = models.FloatField(default=0.0)
    rubber_stamp_strata_suspect = models.BooleanField(default=False)

    # 2. Attributes & occlusion editing signals
    attr_modified_count = models.PositiveIntegerField(default=0)
    attr_edit_rate = models.FloatField(default=0.0)
    attr_missed_count = models.PositiveIntegerField(default=0)

    # 3. Unfixed / rubber-stamping issue signals
    rubber_stamp_suspects = models.PositiveIntegerField(default=0)
    issues_tp = models.PositiveIntegerField(default=0)
    issues_fp = models.PositiveIntegerField(default=0)
    issues_resolved_unchanged = models.PositiveIntegerField(default=0)
    issues_reopened = models.PositiveIntegerField(default=0)
    qc_fixed_issues = models.PositiveIntegerField(default=0)
    qa_override_rate = models.FloatField(default=0.0)
    annotator_utility_score = models.FloatField(default=1.0)

    # 4. S0 pre-label deletion anti-gaming signals
    s0_deleted_count = models.PositiveIntegerField(default=0)
    suspicious_deletion_count = models.PositiveIntegerField(default=0)

    # 5. Track ID continuity & switch signals
    track_continuity_ratio = models.FloatField(default=1.0)
    track_id_switch_count = models.PositiveIntegerField(default=0)

    # QC1 -> QC2 & inter-QC consistency signals
    l1_escape_count = models.PositiveIntegerField(default=0)
    l1_escape_rate = models.FloatField(default=0.0)
    made_worse_count = models.PositiveIntegerField(default=0)
    mean_dl_m = models.FloatField(default=0.0)
    mean_dw_m = models.FloatField(default=0.0)
    mean_dh_m = models.FloatField(default=0.0)
    mean_center_shift_m = models.FloatField(default=0.0)
    mean_abs_yaw_deg = models.FloatField(default=0.0)
    drift_warning = models.BooleanField(default=False)
    ruling_agreed_count = models.PositiveIntegerField(default=0)
    ruling_disagreed_count = models.PositiveIntegerField(default=0)

    # Flexible modality-specific geometry metrics (2D px/IoU/landmark or 3D extensions)
    geometry_metrics = models.JSONField(default=dict, blank=True)

    # Honeypot Ground-Truth audit (3D or 2D)
    honeypot_evaluated = models.BooleanField(default=False)
    honeypot_passed = models.BooleanField(default=True)
    honeypot_mean_iou = models.FloatField(null=True, blank=True)
    honeypot_mean_iou_3d = models.FloatField(null=True, blank=True)
    honeypot_missed = models.PositiveIntegerField(default=0)
    honeypot_extra = models.PositiveIntegerField(default=0)
    honeypot_track_switches = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)


class DailyUserMetrics(models.Model):
    date = models.DateField(db_index=True)
    username = models.CharField(max_length=150, db_index=True)
    role = models.CharField(max_length=24, db_index=True)  # annotator | l1_qc | l2_qc | dept_head
    dimension = models.CharField(
        max_length=16,
        choices=Dimension.choices,
        default=Dimension.DIM_3D,
        db_index=True,
    )

    jobs_submitted = models.PositiveIntegerField(default=0)
    jobs_accepted_l1 = models.PositiveIntegerField(default=0)
    jobs_accepted_l2 = models.PositiveIntegerField(default=0)
    jobs_completed = models.PositiveIntegerField(default=0)
    jobs_returned_rework = models.PositiveIntegerField(default=0)
    frames_processed = models.PositiveIntegerField(default=0)
    cuboids_inspected = models.PositiveIntegerField(default=0)
    issues_raised = models.PositiveIntegerField(default=0)
    working_time_ms = models.BigIntegerField(default=0)

    class Meta:
        unique_together = [("date", "username", "role", "dimension")]
        ordering = ["-date", "username"]

    @property
    def items_inspected(self) -> int:
        return self.cuboids_inspected


class DefectRecord(models.Model):
    """Metadata-only defect log (never stores screenshots or raw sensor payloads)."""

    cvat_issue_id = models.PositiveIntegerField(unique=True, db_index=True)
    job = models.ForeignKey(SyncedJob, on_delete=models.CASCADE, related_name="defects")
    frame = models.PositiveIntegerField(default=0)
    primary_category = models.CharField(max_length=8, db_index=True)  # E1..E6
    defect_code = models.CharField(max_length=32, db_index=True)
    severity = models.CharField(max_length=16, default="major", db_index=True)
    source = models.CharField(max_length=24, default="manual", db_index=True)
    lifecycle_status = models.CharField(max_length=24, default="open", db_index=True)
    root_cause = models.CharField(max_length=32, blank=True, default="", db_index=True)
    is_disputed = models.BooleanField(default=False)
    is_reopened = models.BooleanField(default=False)
    is_dismissed_fp = models.BooleanField(default=False)
    annotator_username = models.CharField(max_length=150, blank=True, default="", db_index=True)
    owner_username = models.CharField(max_length=150, blank=True, default="", db_index=True)
    age_hours = models.FloatField(default=0.0)
    summary_text = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-cvat_issue_id"]


class DeliveryBatch(models.Model):
    if TYPE_CHECKING:
        class Status(str, models.Choices):
            DRAFT = "draft"
            GATE_READY = "gate_ready"
            DELIVERED = "delivered"
            ACCEPTED = "accepted"
            REJECTED = "rejected"
    else:
        class Status(models.TextChoices):
            DRAFT = "draft", "Đang đóng gói"
            GATE_READY = "gate_ready", "Đạt chuẩn xuất"
            DELIVERED = "delivered", "Đã bàn giao"
            ACCEPTED = "accepted", "Khách nghiệm thu"
            REJECTED = "rejected", "Khách trả lại"

    batch_code = models.CharField(max_length=64, unique=True, db_index=True)
    title = models.CharField(max_length=255)
    client_name = models.CharField(max_length=150, blank=True, default="")
    dimension = models.CharField(
        max_length=16,
        choices=BatchDimension.choices,
        default=BatchDimension.ALL,
        db_index=True,
    )
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    notes = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class DeliveryBatchItem(models.Model):
    batch = models.ForeignKey(DeliveryBatch, on_delete=models.CASCADE, related_name="items")
    job = models.ForeignKey(SyncedJob, on_delete=models.CASCADE, related_name="delivery_items")
    gate_passed = models.BooleanField(default=False)
    gate_blockers = models.JSONField(default=list, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("batch", "job")]


# ==============================================================================
# Operational Workflow Models (Canonical Contract for React Dashboard)
# ==============================================================================


if TYPE_CHECKING:
    class WorkflowRole(str, models.Choices):
        ADMIN = "admin"
        PM = "pm"
        LEAD = "lead"
        ANNOTATOR = "annotator"

    class WorkflowJobStage(str, models.Choices):
        UNASSIGNED_POOL = "unassigned_pool"
        TEAM_POOL = "team_pool"
        ANNO_IN_PROGRESS = "anno_in_progress"
        QC1_PENDING = "qc1_pending"
        QC1_IN_PROGRESS = "qc1_in_progress"
        QC2_PENDING = "qc2_pending"
        QC2_IN_PROGRESS = "qc2_in_progress"
        READY_TO_DELIVER = "ready_to_deliver"
        DELIVERED = "delivered"

    class WorkflowBatchStatus(str, models.Choices):
        PENDING = "pending"
        IN_PROGRESS = "in_progress"
        IN_AUDIT = "in_audit"
        READY = "ready"
        DELIVERED = "delivered"
        RELEASED = "released"
else:
    class WorkflowRole(models.TextChoices):
        ADMIN = "admin", "Admin"
        PM = "pm", "PM"
        LEAD = "lead", "Team Lead"
        ANNOTATOR = "annotator", "Annotator"

    class WorkflowJobStage(models.TextChoices):
        UNASSIGNED_POOL = "unassigned_pool", "Chờ giao"
        TEAM_POOL = "team_pool", "Kho team"
        ANNO_IN_PROGRESS = "anno_in_progress", "Đang gán nhãn"
        QC1_PENDING = "qc1_pending", "Chờ QC1"
        QC1_IN_PROGRESS = "qc1_in_progress", "QC1 đang kiểm tra"
        QC2_PENDING = "qc2_pending", "Chờ QC2 · Audit"
        QC2_IN_PROGRESS = "qc2_in_progress", "QC2 · Audit đang kiểm tra"
        READY_TO_DELIVER = "ready_to_deliver", "Sẵn sàng giao"
        DELIVERED = "delivered", "Đã giao"

    class WorkflowBatchStatus(models.TextChoices):
        PENDING = "pending", "Chưa chia"
        IN_PROGRESS = "in_progress", "Đang làm"
        IN_AUDIT = "in_audit", "Đang audit"
        READY = "ready", "Sẵn sàng giao"
        DELIVERED = "delivered", "Đã giao"
        RELEASED = "released", "Đã release"


class WorkflowDataType(models.Model):
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    dimension = models.CharField(
        max_length=16,
        choices=Dimension.choices,
        default=Dimension.DIM_3D,
        db_index=True,
    )
    shape_type = models.CharField(max_length=32, default="cuboid")
    kpi_per_day = models.PositiveIntegerField(default=1200)
    threshold_cm = models.FloatField(default=5.0)
    threshold_deg = models.FloatField(default=3.0)
    error_categories = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.shape_type})"


class WorkflowUser(models.Model):
    code = models.CharField(max_length=64, unique=True, db_index=True)
    django_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="workflow_profile",
    )
    name = models.CharField(max_length=150)
    cvat_username = models.CharField(max_length=150, unique=True, db_index=True)
    role = models.CharField(max_length=24, choices=WorkflowRole.choices, default=WorkflowRole.ANNOTATOR, db_index=True)
    is_qc = models.BooleanField(default=False)
    employee_id = models.PositiveIntegerField(default=1000)
    favorites = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.name} ({self.cvat_username})"


class WorkflowTeam(models.Model):
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    lead = models.ForeignKey(
        WorkflowUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="led_teams",
    )
    pm = models.ForeignKey(
        WorkflowUser,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_teams",
    )
    members = models.ManyToManyField(WorkflowUser, blank=True, related_name="teams")
    allowed_steps = models.JSONField(default=list, blank=True)
    can_qa = models.BooleanField(default=False)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class WorkflowProject(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        PAUSED = "paused", "Paused"
        DONE = "done", "Done"

    code = models.CharField(max_length=64, unique=True, db_index=True)
    display_code = models.CharField(max_length=64, blank=True, default="")
    name = models.CharField(max_length=255)
    data_type = models.ForeignKey(WorkflowDataType, on_delete=models.PROTECT, related_name="projects")
    pms = models.ManyToManyField(WorkflowUser, blank=True, related_name="managed_projects")
    pm_order = models.JSONField(default=list, blank=True)
    teams = models.ManyToManyField(WorkflowTeam, blank=True, related_name="projects")
    partner = models.JSONField(default=dict, blank=True)
    assigned_at = models.DateTimeField(default=timezone.now)
    due_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING, db_index=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class WorkflowDataset(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ARCHIVED = "archived", "Archived"

    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    nas_path = models.CharField(max_length=512, blank=True, default="")
    data_type = models.ForeignKey(WorkflowDataType, on_delete=models.PROTECT, related_name="datasets")
    project = models.ForeignKey(WorkflowProject, on_delete=models.CASCADE, related_name="datasets")
    file_count = models.PositiveIntegerField(default=0)
    frame_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    received_at = models.DateTimeField(default=timezone.now)
    last_distributed_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    preprocessed_pct = models.PositiveSmallIntegerField(default=100)
    on_cvat_pct = models.PositiveSmallIntegerField(default=100)
    scene_count = models.PositiveIntegerField(default=0)
    partner_note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class WorkflowBatch(models.Model):
    code = models.CharField(max_length=64, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    dataset = models.ForeignKey(WorkflowDataset, on_delete=models.CASCADE, related_name="batches")
    project = models.ForeignKey(WorkflowProject, on_delete=models.CASCADE, related_name="batches")
    team = models.ForeignKey(
        WorkflowTeam,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="batches",
    )
    cvat_task_id = models.PositiveIntegerField(db_index=True)
    status = models.CharField(
        max_length=24,
        choices=WorkflowBatchStatus.choices,
        default=WorkflowBatchStatus.PENDING,
        db_index=True,
    )
    step_pic = models.JSONField(default=dict, blank=True)
    auto_lock_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    step_buffer_days = models.JSONField(default=dict, blank=True)
    priority = models.PositiveSmallIntegerField(default=3)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code}: {self.name}"


class WorkflowJob(models.Model):
    code = models.CharField(max_length=64, unique=True, db_index=True)
    cvat_job_id = models.PositiveIntegerField(unique=True, db_index=True)
    batch = models.ForeignKey(WorkflowBatch, on_delete=models.CASCADE, related_name="jobs")
    project = models.ForeignKey(WorkflowProject, on_delete=models.CASCADE, related_name="jobs")
    team = models.ForeignKey(WorkflowTeam, null=True, blank=True, on_delete=models.SET_NULL, related_name="jobs")
    annotator = models.ForeignKey(WorkflowUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="annotated_jobs")
    qc1 = models.ForeignKey(WorkflowUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="qc1_jobs")
    qc2 = models.ForeignKey(WorkflowUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="qc2_jobs")
    stage = models.CharField(
        max_length=24,
        choices=WorkflowJobStage.choices,
        default=WorkflowJobStage.UNASSIGNED_POOL,
        db_index=True,
    )
    prelabel_cuboids = models.PositiveIntegerField(default=0)
    edited_cuboids = models.PositiveIntegerField(default=0)
    frames = models.PositiveIntegerField(default=0)
    rework_count = models.PositiveIntegerField(default=0)
    first_submitted_at = models.DateTimeField(null=True, blank=True)
    cvat_drift = models.TextField(blank=True, default="")
    due = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} (CVAT #{self.cvat_job_id})"


class WorkflowJobEvent(models.Model):
    """Append-only immutable workflow transition log per job."""

    code = models.CharField(max_length=64, unique=True, db_index=True)
    job = models.ForeignKey(WorkflowJob, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(WorkflowUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_code = models.CharField(max_length=64, blank=True, default="")
    type = models.CharField(max_length=32, db_index=True)
    from_stage = models.CharField(max_length=24, null=True, blank=True)
    to_stage = models.CharField(max_length=24)
    reason = models.TextField(blank=True, default="")
    error_category = models.CharField(max_length=128, blank=True, default="")
    rework_against = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["at", "id"]


class WorkflowBatchEvent(models.Model):
    """Append-only immutable audit log per batch."""

    code = models.CharField(max_length=64, unique=True, db_index=True)
    batch = models.ForeignKey(WorkflowBatch, on_delete=models.CASCADE, related_name="events")
    at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(WorkflowUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_code = models.CharField(max_length=64, blank=True, default="")
    type = models.CharField(max_length=32, db_index=True)
    detail = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["at", "id"]


class WorkflowAudit(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    code = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(WorkflowUser, null=True, blank=True, on_delete=models.SET_NULL, related_name="created_audits")
    project = models.ForeignKey(WorkflowProject, on_delete=models.CASCADE, related_name="audits")
    batches = models.ManyToManyField(WorkflowBatch, blank=True, related_name="audits")
    batch_codes = models.JSONField(default=list, blank=True)
    levels = models.JSONField(default=list, blank=True)
    current_level_index = models.PositiveSmallIntegerField(default=0)
    percent = models.PositiveSmallIntegerField(default=100)
    sampled_job_codes = models.JSONField(default=list, blank=True)
    results = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]


class WorkflowKpiDaily(models.Model):
    user = models.ForeignKey(WorkflowUser, on_delete=models.CASCADE, related_name="kpi_daily")
    date = models.DateField(db_index=True)
    edited_cuboids = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("user", "date")]
        ordering = ["date", "user_id"]


# ==============================================================================
# Transactional QC Custom Events (Ported from cvat-di-ext `qc:*` JSONL/Analytics)
# ==============================================================================


class QcEvent(models.Model):
    """
    ACID-transactional ledger for custom `qc:*` events ported from `cvat-di-ext`
    (`qc_event_log.py`). Replaces fire-and-forget JSONL + ClickHouse logging with
    idempotent DB persistence atomic with job/defect/KPI transitions.
    """

    idempotency_key = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True)
    scope = models.CharField(max_length=96, db_index=True)       # e.g. "qc:job_submitted"
    event_type = models.CharField(max_length=64, db_index=True)  # e.g. "job_submitted"
    timestamp_utc = models.DateTimeField(default=timezone.now, db_index=True)

    job_id = models.PositiveIntegerField(db_index=True)
    task_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    project_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    workflow_job = models.ForeignKey(
        WorkflowJob,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="qc_events",
    )

    stage = models.CharField(max_length=32, blank=True, default="")
    actor_role = models.CharField(max_length=32, blank=True, default="", db_index=True)
    user_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    username = models.CharField(max_length=150, blank=True, default="", db_index=True)

    issue_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    defect_code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    severity = models.CharField(max_length=24, blank=True, default="")
    status = models.CharField(max_length=32, blank=True, default="")

    frame_number = models.IntegerField(null=True, blank=True)
    frames_span = models.JSONField(default=list, blank=True)
    track_id = models.IntegerField(null=True, blank=True)
    shape_id = models.IntegerField(null=True, blank=True)
    label_class = models.CharField(max_length=64, blank=True, default="")
    dwell_ms = models.PositiveIntegerField(null=True, blank=True)

    params = models.JSONField(default=dict, blank=True)
    metric_delta = models.JSONField(default=dict, blank=True)
    extra = models.JSONField(default=dict, blank=True)

    applied_to_workflow = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp_utc", "-id"]
        indexes = [
            models.Index(fields=["job_id", "event_type"]),
            models.Index(fields=["scope", "timestamp_utc"]),
        ]

    def __str__(self) -> str:
        return f"{self.scope} job=#{self.job_id}"
