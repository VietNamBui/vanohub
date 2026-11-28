from __future__ import annotations

from rest_framework import serializers

from .models import (
    DailyUserMetrics,
    DefectRecord,
    DeliveryBatch,
    DeliveryBatchItem,
    JobQualitySnapshot,
    StageTransition,
    SyncedJob,
    SyncedTask,
)


class SyncedTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = SyncedTask
        fields = [
            "id",
            "cvat_task_id",
            "name",
            "project_name",
            "dimension",
            "annotation_type",
            "total_frames",
            "updated_at",
        ]


class SyncedJobSerializer(serializers.ModelSerializer):
    cycle_stage = serializers.ReadOnlyField()
    dimension = serializers.ReadOnlyField()
    inspected_items = serializers.ReadOnlyField()
    required_items = serializers.ReadOnlyField()
    total_items = serializers.ReadOnlyField()

    class Meta:
        model = SyncedJob
        fields = [
            "id",
            "cvat_job_id",
            "task",
            "dimension",
            "start_frame",
            "stop_frame",
            "frame_count",
            "pipeline_step",
            "cycle_stage",
            "work_state",
            "review_round",
            "rework_count",
            "annotator_username",
            "l1_qc_username",
            "l2_qc_username",
            "dept_head_username",
            "open_issues",
            "addressed_issues",
            "escalations",
            "disputes",
            "resolved_issues",
            "inspected_cuboids",
            "required_cuboids",
            "total_cuboids",
            "inspected_items",
            "required_items",
            "total_items",
            "l2_required",
            "threshold_met",
            "deliver_status",
            "step_entered_at",
            "completed_at",
            "updated_at",
        ]


class StageTransitionSerializer(serializers.ModelSerializer):
    is_rework_return = serializers.ReadOnlyField()

    class Meta:
        model = StageTransition
        fields = [
            "id",
            "job",
            "event_id",
            "event_name",
            "action",
            "from_step",
            "to_step",
            "actor_username",
            "actor_role",
            "reason",
            "occurred_at",
            "duration_prev_step_sec",
            "is_rework_return",
        ]


class JobQualitySnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobQualitySnapshot
        fields = "__all__"


class DailyUserMetricsSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyUserMetrics
        fields = "__all__"


class DefectRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DefectRecord
        fields = "__all__"


class DeliveryBatchItemSerializer(serializers.ModelSerializer):
    cvat_job_id = serializers.IntegerField(source="job.cvat_job_id", read_only=True)
    task_name = serializers.CharField(source="job.task.name", read_only=True)
    dimension = serializers.CharField(source="job.task.dimension", read_only=True)
    annotation_type = serializers.CharField(source="job.task.annotation_type", read_only=True)
    pipeline_step = serializers.CharField(source="job.pipeline_step", read_only=True)
    frame_count = serializers.IntegerField(source="job.frame_count", read_only=True)

    class Meta:
        model = DeliveryBatchItem
        fields = [
            "id",
            "batch",
            "job",
            "cvat_job_id",
            "task_name",
            "dimension",
            "annotation_type",
            "pipeline_step",
            "frame_count",
            "gate_passed",
            "gate_blockers",
            "added_at",
        ]


class DeliveryBatchSerializer(serializers.ModelSerializer):
    items = DeliveryBatchItemSerializer(many=True, read_only=True)
    item_count = serializers.IntegerField(source="items.count", read_only=True)
    created_by_username = serializers.CharField(source="created_by.username", read_only=True)

    class Meta:
        model = DeliveryBatch
        fields = [
            "id",
            "batch_code",
            "title",
            "client_name",
            "dimension",
            "status",
            "notes",
            "created_by",
            "created_by_username",
            "created_at",
            "delivered_at",
            "item_count",
            "items",
        ]
        read_only_fields = ["status", "created_by", "created_at", "delivered_at"]
