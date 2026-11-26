from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from jobs.models import JobStatus
from accounts.serializers import UserBriefSerializer
from cvat_integration.assignee import schedule_assignee_push
from projects.models import ActivityLog

from .models import Audit, AuditSample, ErrorCategory, ReviewError, ReviewStage
from .serializers import (
    AuditSampleSerializer,
    AuditSerializer,
    ErrorCategorySerializer,
    PassSerializer,
    RejectSerializer,
)


class ErrorCategoryViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.CreateModelMixin,
                           mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Danh mục lỗi. Không xoá (lỗi đã ghi đang tham chiếu) — tắt bằng is_active=false."""

    serializer_class = ErrorCategorySerializer
    required_capabilities = {"list": Cap.VIEW_PROJECT, "*": Cap.MANAGE_QUALITY_CATALOG}

    def get_queryset(self):
        queryset = ErrorCategory.objects.filter(project=self.project)
        stage = self.request.query_params.get("stage")
        if stage in ("qc1", "qc2"):
            queryset = queryset.filter(applies_to__in=[stage, "both"], is_active=True)
        return queryset

    def perform_create(self, serializer):
        category = serializer.save(project=self.project)
        ActivityLog.record(project=self.project, actor=self.request.user, action="error_category.create",
                           target=category)

    def perform_update(self, serializer):
        category = serializer.save()
        ActivityLog.record(project=self.project, actor=self.request.user, action="error_category.update",
                           target=category)


def _four_eyes_conflicts(job):
    """Luật bốn mắt: không audit job mình đã annotate hoặc đã QC1."""
    return {uid for uid in (job.annotator_id, job.qc1_reviewer_id) if uid}


class AuditViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    """Các đợt QC2 theo task — CHỈ ĐỌC. Đợt QC2 tự tạo khi job đầu tiên của task vào Chờ QC2
    (quality/qc2.py) và tự chốt khi task được bàn giao.

    - PM (Cap.MANAGE_AUDITS) thấy mọi đợt; QC2 chuyên trách chỉ thấy đợt có lượt được giao cho mình.
    """

    serializer_class = AuditSerializer
    required_capabilities = {"*": [Cap.MANAGE_AUDITS, Cap.PERFORM_AUDIT]}

    def get_queryset(self):
        queryset = Audit.objects.filter(project=self.project).select_related("batch__dataset", "created_by").annotate(
            sample_count=Count("samples"),
            passed=Count("samples", filter=Q(samples__result=AuditSample.Result.PASS)),
            rejected=Count("samples", filter=Q(samples__result=AuditSample.Result.REJECT)),
            pending=Count("samples", filter=Q(samples__result=AuditSample.Result.PENDING)),
        )
        if not self.has_cap(Cap.MANAGE_AUDITS):
            queryset = queryset.filter(samples__auditor=self.request.user).distinct()
        p = self.request.query_params
        if p.get("status"):
            queryset = queryset.filter(status=p["status"])
        if p.get("batch"):
            queryset = queryset.filter(batch_id=p["batch"])
        return queryset


class AuditSampleViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    """Thực hiện QC2: Pass / Reject từng job được lấy mẫu."""

    serializer_class = AuditSampleSerializer
    required_capabilities = {"assign": Cap.MANAGE_AUDITS, "*": Cap.PERFORM_AUDIT}

    def get_queryset(self):
        queryset = AuditSample.objects.filter(audit__project=self.project).select_related(
            "audit", "job__annotator", "job__qc1_reviewer", "job__batch", "job__dataset", "auditor", "reviewed_by"
        ).prefetch_related("errors__category", "errors__reported_by")
        p = self.request.query_params
        if not self.has_cap(Cap.MANAGE_AUDITS) or p.get("mine") == "1":
            queryset = queryset.filter(auditor=self.request.user)
        if p.get("audit"):
            queryset = queryset.filter(audit_id=p["audit"])
        if p.get("result"):
            queryset = queryset.filter(result=p["result"])
        if p.get("open") == "1":
            queryset = queryset.filter(audit__status=Audit.Status.IN_PROGRESS)
        return queryset

    def _check_can_review(self, sample):
        user = self.request.user
        if sample.audit.status != Audit.Status.IN_PROGRESS:
            raise ValidationError("Task đã bàn giao, đợt QC2 đã chốt.")
        if sample.result != AuditSample.Result.PENDING:
            raise ValidationError("Mẫu này đã có kết quả.")
        if sample.auditor_id and sample.auditor_id != user.id and not self.has_cap(Cap.MANAGE_AUDITS):
            raise PermissionDenied("Mẫu này được giao cho auditor khác.")
        if user.id in _four_eyes_conflicts(sample.job):
            raise PermissionDenied("Luật bốn mắt: bạn đã annotate hoặc QC1 job này.")
        if sample.job.status != JobStatus.PENDING_QC2:
            raise ValidationError("Job không còn ở trạng thái Chờ QC2.")

    def _finish(self, sample, result, comment):
        sample.result = result
        sample.reviewed_by = self.request.user
        sample.reviewed_at = timezone.now()
        sample.comment = comment
        if not sample.auditor_id:
            sample.auditor = self.request.user
        sample.save()

    @action(detail=True, methods=["post"], url_path="pass")
    def pass_(self, request, project_id, pk=None):
        sample = self.get_object()
        self._check_can_review(sample)
        serializer = PassSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        job = sample.job
        with transaction.atomic():
            self._finish(sample, AuditSample.Result.PASS, serializer.validated_data["comment"])
            job.status = JobStatus.APPROVED
            job.save(update_fields=["status", "updated_at"])
            schedule_assignee_push([job.pk])
            ActivityLog.record(project=self.project, actor=request.user, action="qc2.pass", target=job, job=job,
                               before={"status": JobStatus.PENDING_QC2}, after={"status": JobStatus.APPROVED})
        return Response(self.get_serializer(self.get_queryset().get(pk=sample.pk)).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, project_id, pk=None):
        """Reject → ghi lỗi, job về Rework, tăng vòng rework, vượt ngưỡng thì Escalated.

        Lưu ý: chưa đẩy trạng thái ngược về CVAT (chỉ đọc CVAT ở giai đoạn này).
        """
        sample = self.get_object()
        self._check_can_review(sample)
        serializer = RejectSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        job = sample.job
        with transaction.atomic():
            self._finish(sample, AuditSample.Result.REJECT, serializer.validated_data["comment"])
            ReviewError.objects.bulk_create([
                ReviewError(
                    job=job, stage=ReviewStage.QC2, rework_round=job.rework_round, audit_sample=sample,
                    category=e["category"], severity=e.get("severity") or e["category"].severity,
                    location=e["location"], description=e["description"], reported_by=request.user,
                )
                for e in serializer.validated_data["errors"]
            ])
            job.status = JobStatus.REWORK
            job.rework_round += 1
            if job.rework_round > self.project.max_rework_rounds:
                job.is_escalated = True
            job.save(update_fields=["status", "rework_round", "is_escalated", "updated_at"])
            schedule_assignee_push([job.pk])  # Rework → job quay về annotator
            ActivityLog.record(
                project=self.project, actor=request.user, action="qc2.reject", target=job, job=job,
                before={"status": JobStatus.PENDING_QC2},
                after={"status": JobStatus.REWORK, "rework_round": job.rework_round,
                       "errors": len(serializer.validated_data["errors"]), "escalated": job.is_escalated},
            )
        return Response(self.get_serializer(self.get_queryset().get(pk=sample.pk)).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, project_id, pk=None):
        """PM phân (lại) auditor cho một mẫu."""
        sample = self.get_object()
        if sample.result != AuditSample.Result.PENDING:
            raise ValidationError("Mẫu đã có kết quả.")
        auditor = User.objects.filter(pk=request.data.get("auditor")).first()
        if not auditor or Role.QC2 not in auditor.get_project_roles(self.project):
            raise ValidationError("Auditor phải có quyền QC2 trong dự án.")
        if auditor.id in _four_eyes_conflicts(sample.job):
            raise ValidationError("Luật bốn mắt: người này đã annotate hoặc QC1 job.")
        sample.auditor = auditor
        sample.save(update_fields=["auditor"])
        schedule_assignee_push([sample.job_id])
        ActivityLog.record(project=self.project, actor=request.user, action="qc2.assign_auditor", target=sample.job,
                           job=sample.job, after={"auditor": auditor.username})
        return Response(self.get_serializer(self.get_queryset().get(pk=sample.pk)).data)


SAMPLING_FIELDS = ("sampling_rate",)


class AuditStrategyView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/audit-strategy/ — quy tắc QC2 đang áp dụng (chỉ PM).

    QC2 kiểm MỌI job qua QC1, mỗi job ngẫu nhiên sampling_rate % số frame (làm tròn lên, ít nhất 1).
    PM sửa tỉ lệ qua /settings/. Kèm lịch sử thay đổi và thống kê lượt QC2.
    """

    required_capabilities = {"*": Cap.MANAGE_AUDITS}

    def get(self, request, project_id):
        project = self.project
        history = []
        logs = ActivityLog.objects.filter(project=project, action="project.settings").select_related("actor")
        for log in logs.order_by("-created_at")[:50]:
            after = {k: v for k, v in (log.after or {}).items() if k in SAMPLING_FIELDS}
            if after:
                before = {k: (log.before or {}).get(k) for k in after}
                history.append({"at": log.created_at, "actor": UserBriefSerializer(log.actor).data if log.actor else None,
                                "before": before, "after": after})
        samples = AuditSample.objects.filter(audit__project=project)
        return Response({
            "sampling_rate": project.sampling_rate,
            "can_edit": self.has_cap(Cap.MANAGE_SETTINGS),
            "history": history[:20],
            "stats": {
                "pending": samples.filter(result=AuditSample.Result.PENDING).count(),
                "passed": samples.filter(result=AuditSample.Result.PASS).count(),
                "rejected": samples.filter(result=AuditSample.Result.REJECT).count(),
            },
        })
