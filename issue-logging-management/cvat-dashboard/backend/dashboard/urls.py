from __future__ import annotations

from typing import Any

from django.urls import include, path
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.routers import DefaultRouter

from .auth_views import CurrentUserView, LoginView, LogoutView
from .views import (
    DailyProductivityView,
    DataCycleFunnelView,
    DefectParetoView,
    DeliveryBatchViewSet,
    ModalityConfigView,
    QualityScorecardView,
    WebhookCvatStageView,
)
from .workflow_views import (
    QcEventsActivityView,
    QcEventsBackfillView,
    QcEventsView,
    WorkflowAuditCloseView,
    WorkflowAuditCreateView,
    WorkflowAuditPassJobView,
    WorkflowAuditReturnJobView,
    WorkflowBatchAssignTeamView,
    WorkflowBatchAutoLockView,
    WorkflowBatchDistributeView,
    WorkflowBatchDueView,
    WorkflowBatchPreviewDistributionView,
    WorkflowBatchPriorityView,
    WorkflowBatchReassignView,
    WorkflowBatchReleaseView,
    WorkflowDataTypeDetailView,
    WorkflowFavoriteToggleView,
    WorkflowJobAssignView,
    WorkflowJobDueView,
    WorkflowJobQc1PassView,
    WorkflowJobQc1ReturnView,
    WorkflowJobQc2PassView,
    WorkflowJobQc2ReturnAnnoView,
    WorkflowJobQc2ReturnQc1View,
    WorkflowJobReassignView,
    WorkflowJobsDeliverView,
    WorkflowJobStartQc1View,
    WorkflowJobStartQc2View,
    WorkflowJobSubmitView,
    WorkflowProjectAssignView,
    WorkflowStateView,
    WorkflowSwitchUserView,
    WorkflowTeamDetailView,
    WorkflowTeamMemberDetailView,
    WorkflowTeamMembersView,
    WorkflowTeamPmView,
    WorkflowTeamsView,
    WorkflowUserDetailView,
    WorkflowUserMoveTeamView,
)

router = DefaultRouter()
router.register("delivery-batches", DeliveryBatchViewSet, basename="delivery-batches")  # type: ignore[reportUnknownMemberType]

router_urls: list[Any] = router.urls  # type: ignore[reportUnknownMemberType, reportUnknownVariableType]

urlpatterns: list[URLPattern | URLResolver] = [
    # Unified CVAT Authentication
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("auth/user/", CurrentUserView.as_view(), name="auth-user"),

    # Modality profiles (3D / 2D / All metadata & schemas)
    path("modalities/", ModalityConfigView.as_view(), name="modality-config"),

    # Data Cycle Funnel (WIP, SLA, lead time, rework loops)
    path("funnel/", DataCycleFunnelView.as_view(), name="data-cycle-funnel"),

    # Productivity & Daily Throughput
    path("productivity/", DailyProductivityView.as_view(), name="daily-productivity"),

    # QA/QC Accuracy & Red-Flag Anti-Gaming Scorecard
    path("scorecard/", QualityScorecardView.as_view(), name="quality-scorecard"),

    # E1..E6 Defect Pareto & Root Causes
    path("defects/", DefectParetoView.as_view(), name="defect-pareto"),

    # Outbound webhook from CVAT
    path("webhooks/cvat-stage/", WebhookCvatStageView.as_view(), name="webhook-cvat-stage"),

    # Operational Workflow REST APIs (backs React frontend)
    path("workflow/state/", WorkflowStateView.as_view(), name="workflow-state"),
    path("workflow/switch-user/", WorkflowSwitchUserView.as_view(), name="workflow-switch-user"),
    path("workflow/favorites/toggle/", WorkflowFavoriteToggleView.as_view(), name="workflow-favorite-toggle"),

    path("workflow/jobs/deliver/", WorkflowJobsDeliverView.as_view(), name="workflow-jobs-deliver"),
    path("workflow/jobs/<str:job_code>/assign/", WorkflowJobAssignView.as_view(), name="workflow-job-assign"),
    path("workflow/jobs/<str:job_code>/reassign/", WorkflowJobReassignView.as_view(), name="workflow-job-reassign"),
    path("workflow/jobs/<str:job_code>/submit/", WorkflowJobSubmitView.as_view(), name="workflow-job-submit"),
    path("workflow/jobs/<str:job_code>/qc1-start/", WorkflowJobStartQc1View.as_view(), name="workflow-job-qc1-start"),
    path("workflow/jobs/<str:job_code>/qc1-pass/", WorkflowJobQc1PassView.as_view(), name="workflow-job-qc1-pass"),
    path("workflow/jobs/<str:job_code>/qc1-return/", WorkflowJobQc1ReturnView.as_view(), name="workflow-job-qc1-return"),
    path("workflow/jobs/<str:job_code>/qc2-start/", WorkflowJobStartQc2View.as_view(), name="workflow-job-qc2-start"),
    path("workflow/jobs/<str:job_code>/qc2-pass/", WorkflowJobQc2PassView.as_view(), name="workflow-job-qc2-pass"),
    path("workflow/jobs/<str:job_code>/qc2-return-qc1/", WorkflowJobQc2ReturnQc1View.as_view(), name="workflow-job-qc2-return-qc1"),
    path("workflow/jobs/<str:job_code>/qc2-return-anno/", WorkflowJobQc2ReturnAnnoView.as_view(), name="workflow-job-qc2-return-anno"),
    path("workflow/jobs/<str:job_code>/due/", WorkflowJobDueView.as_view(), name="workflow-job-due"),

    path("workflow/batches/<str:batch_code>/preview-distribution/", WorkflowBatchPreviewDistributionView.as_view(), name="workflow-batch-preview-dist"),
    path("workflow/batches/<str:batch_code>/distribute/", WorkflowBatchDistributeView.as_view(), name="workflow-batch-distribute"),
    path("workflow/batches/<str:batch_code>/assign-team/", WorkflowBatchAssignTeamView.as_view(), name="workflow-batch-assign-team"),
    path("workflow/batches/<str:batch_code>/reassign/", WorkflowBatchReassignView.as_view(), name="workflow-batch-reassign"),
    path("workflow/batches/<str:batch_code>/release/", WorkflowBatchReleaseView.as_view(), name="workflow-batch-release"),
    path("workflow/batches/<str:batch_code>/autolock/", WorkflowBatchAutoLockView.as_view(), name="workflow-batch-autolock"),
    path("workflow/batches/<str:batch_code>/due/", WorkflowBatchDueView.as_view(), name="workflow-batch-due"),
    path("workflow/batches/<str:batch_code>/priority/", WorkflowBatchPriorityView.as_view(), name="workflow-batch-priority"),

    path("workflow/audits/", WorkflowAuditCreateView.as_view(), name="workflow-audit-create"),
    path("workflow/audits/<str:audit_code>/pass-job/", WorkflowAuditPassJobView.as_view(), name="workflow-audit-pass-job"),
    path("workflow/audits/<str:audit_code>/return-job/", WorkflowAuditReturnJobView.as_view(), name="workflow-audit-return-job"),
    path("workflow/audits/<str:audit_code>/close/", WorkflowAuditCloseView.as_view(), name="workflow-audit-close"),

    path("workflow/teams/", WorkflowTeamsView.as_view(), name="workflow-teams"),
    path("workflow/teams/<str:team_code>/", WorkflowTeamDetailView.as_view(), name="workflow-team-detail"),
    path("workflow/teams/<str:team_code>/pm/", WorkflowTeamPmView.as_view(), name="workflow-team-pm"),
    path("workflow/teams/<str:team_code>/members/", WorkflowTeamMembersView.as_view(), name="workflow-team-members"),
    path("workflow/teams/<str:team_code>/members/<str:user_code>/", WorkflowTeamMemberDetailView.as_view(), name="workflow-team-member-detail"),
    path("workflow/users/<str:user_code>/", WorkflowUserDetailView.as_view(), name="workflow-user-detail"),
    path("workflow/users/<str:user_code>/move-team/", WorkflowUserMoveTeamView.as_view(), name="workflow-user-move-team"),
    path("workflow/data-types/<str:dt_code>/", WorkflowDataTypeDetailView.as_view(), name="workflow-data-type-detail"),
    path("workflow/projects/<str:project_code>/assign/", WorkflowProjectAssignView.as_view(), name="workflow-project-assign"),

    # Transactional QC custom events (ported from cvat-di-ext `qc:*`)
    path("qc-events/", QcEventsView.as_view(), name="qc-events"),
    path("qc-events/backfill/", QcEventsBackfillView.as_view(), name="qc-events-backfill"),
    path("qc-events/activity/", QcEventsActivityView.as_view(), name="qc-events-activity"),

    # Delivery batches
    path("", include(router_urls)),
]
