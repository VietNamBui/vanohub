from django.contrib import admin

from .models import (
    DailyUserMetrics,
    DefectRecord,
    DeliveryBatch,
    DeliveryBatchItem,
    JobQualitySnapshot,
    QcEvent,
    StageTransition,
    SyncedJob,
    SyncedTask,
    WorkflowAudit,
    WorkflowBatch,
    WorkflowBatchEvent,
    WorkflowDataset,
    WorkflowDataType,
    WorkflowJob,
    WorkflowJobEvent,
    WorkflowKpiDaily,
    WorkflowProject,
    WorkflowTeam,
    WorkflowUser,
)

admin.site.register(SyncedTask)
admin.site.register(SyncedJob)
admin.site.register(StageTransition)
admin.site.register(JobQualitySnapshot)
admin.site.register(DailyUserMetrics)
admin.site.register(DefectRecord)
admin.site.register(DeliveryBatch)
admin.site.register(DeliveryBatchItem)
admin.site.register(WorkflowDataType)
admin.site.register(WorkflowUser)
admin.site.register(WorkflowTeam)
admin.site.register(WorkflowProject)
admin.site.register(WorkflowDataset)
admin.site.register(WorkflowBatch)
admin.site.register(WorkflowJob)
admin.site.register(WorkflowJobEvent)
admin.site.register(WorkflowBatchEvent)
admin.site.register(WorkflowAudit)
admin.site.register(WorkflowKpiDaily)
admin.site.register(QcEvent)
