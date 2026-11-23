from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import Cap, ProjectScopedViewMixin
from projects.models import ActivityLog, DataStatus
from projects.views import StandardPagination
from quality.models import Audit, AuditSample

from .models import OPEN_STATUSES, STAGE_STATUSES, Job, JobStatus
from .serializers import AssignSerializer, BulkSerializer, DeadlineSerializer, JobDetailSerializer, JobSerializer


def _iso(value):
    return value.isoformat() if value else None


def ensure_editable(job):
    """Quy tắc chung trước khi PM sửa job."""
    if job.is_locked:
        raise ValidationError(f"Job {job} đang bị khoá.")
    if job.batch.status != DataStatus.ACTIVE:
        raise ValidationError(f"Batch của job {job} đã khoá hoặc đã bàn giao.")
    if job.status == JobStatus.DELIVERED:
        raise ValidationError(f"Job {job} đã bàn giao.")


def assign_job(job, data, actor, project):
    ensure_editable(job)
    before, after = {}, {}
    for field in ("annotator", "qc1_reviewer"):
        if field in data:
            before[field] = getattr(job, f"{field}_id")
            setattr(job, field, data[field])
            after[field] = data[field].pk if data[field] else None
    if job.annotator_id and job.annotator_id == job.qc1_reviewer_id:
        raise ValidationError("Luật bốn mắt: người QC1 không được là annotator của chính job đó.")
    job.save()
    ActivityLog.record(project=project, actor=actor, action="job.assign", target=job, job=job,
                       before=before, after=after, note=data.get("note", ""))


def set_job_deadline(job, deadline, note, actor, project):
    ensure_editable(job)
    before = job.deadline
    job.deadline = deadline
    job.save(update_fields=["deadline", "updated_at"])
    ActivityLog.record(project=project, actor=actor, action="job.deadline", target=job, job=job,
                       before={"deadline": _iso(before)}, after={"deadline": _iso(deadline)}, note=note)


class JobViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Danh sách & chi tiết Job cấp dự án (PM). Tạo Job: qua Batch → Nhập từ CVAT."""

    pagination_class = StandardPagination
    required_capabilities = {"list": Cap.VIEW_JOBS, "retrieve": Cap.VIEW_JOBS, "*": Cap.MANAGE_JOBS}

    def get_serializer_class(self):
        return JobDetailSerializer if self.action == "retrieve" else JobSerializer

    def get_queryset(self):
        queryset = Job.objects.filter(project=self.project).select_related(
            "batch__dataset", "annotator", "qc1_reviewer", "project"
        ).prefetch_related(Prefetch(
            "audit_samples",
            queryset=AuditSample.objects.filter(audit__status=Audit.Status.IN_PROGRESS).select_related("auditor"),
            to_attr="open_samples",
        ))
        p = self.request.query_params
        if p.get("status"):
            queryset = queryset.filter(status__in=p["status"].split(","))
        if p.get("stage") in STAGE_STATUSES:
            queryset = queryset.filter(status__in=STAGE_STATUSES[p["stage"]])
        if p.get("batch"):
            queryset = queryset.filter(batch_id=p["batch"])
        if p.get("dataset"):
            queryset = queryset.filter(batch__dataset_id=p["dataset"])
        if p.get("assignee"):
            queryset = queryset.filter(Q(annotator_id=p["assignee"]) | Q(qc1_reviewer_id=p["assignee"]))
        if p.get("escalated") == "1":
            queryset = queryset.filter(is_escalated=True)
        if p.get("locked") == "1":
            queryset = queryset.filter(is_locked=True)
        if p.get("unassigned") == "1":
            queryset = queryset.filter(annotator__isnull=True)
        if p.get("overdue") == "1":
            queryset = queryset.filter(deadline__lt=timezone.now(), status__in=OPEN_STATUSES)
        if p.get("search"):
            term = p["search"].strip()
            cond = Q(name__icontains=term)
            if term.isdigit():
                cond |= Q(cvat_job_id=int(term)) | Q(pk=int(term))
            queryset = queryset.filter(cond)
        ordering = p.get("ordering")
        if ordering in {"deadline", "-deadline", "rework_round", "-rework_round", "updated_at", "-updated_at"}:
            queryset = queryset.order_by(ordering, "id")
        return queryset

    def _detail(self, job):
        return Response(JobDetailSerializer(self.get_queryset().get(pk=job.pk), context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, project_id, pk=None):
        job = self.get_object()
        serializer = AssignSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        assign_job(job, serializer.validated_data, request.user, self.project)
        return self._detail(job)

    @action(detail=True, methods=["post"])
    def deadline(self, request, project_id, pk=None):
        job = self.get_object()
        serializer = DeadlineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        set_job_deadline(job, serializer.validated_data["deadline"], serializer.validated_data["note"],
                         request.user, self.project)
        return self._detail(job)

    def _toggle_lock(self, request, locked):
        job = self.get_object()
        if job.is_locked == locked:
            raise ValidationError("Job đã ở trạng thái này.")
        job.is_locked = locked
        job.save(update_fields=["is_locked", "updated_at"])
        ActivityLog.record(project=self.project, actor=request.user, action="job.lock" if locked else "job.unlock",
                           target=job, job=job, note=request.data.get("note", ""))
        return self._detail(job)

    @action(detail=True, methods=["post"])
    def lock(self, request, project_id, pk=None):
        return self._toggle_lock(request, True)

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        return self._toggle_lock(request, False)

    @action(detail=True, methods=["post"], url_path="resolve-escalation")
    def resolve_escalation(self, request, project_id, pk=None):
        """PM xử lý job Escalated: giao cho annotator khác (tuỳ chọn) và gỡ cờ escalated.

        ĐỀ XUẤT: gỡ escalation thì đặt lại rework_round = 0 cho người mới, lịch sử lỗi vẫn giữ.
        """
        job = self.get_object()
        if not job.is_escalated:
            raise ValidationError("Job không ở trạng thái Escalated.")
        with transaction.atomic():
            if "annotator" in request.data:
                serializer = AssignSerializer(data={"annotator": request.data["annotator"]},
                                              context=self.get_serializer_context())
                serializer.is_valid(raise_exception=True)
                assign_job(job, serializer.validated_data, request.user, self.project)
            before_round = job.rework_round
            job.is_escalated = False
            job.rework_round = 0
            job.save(update_fields=["is_escalated", "rework_round", "updated_at"])
            ActivityLog.record(project=self.project, actor=request.user, action="job.resolve_escalation",
                               target=job, job=job, before={"rework_round": before_round},
                               after={"rework_round": 0}, note=request.data.get("note", ""))
        return self._detail(job)

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request, project_id):
        ids = BulkSerializer(data=request.data)
        ids.is_valid(raise_exception=True)
        data = AssignSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        jobs = list(self.get_queryset().filter(pk__in=ids.validated_data["ids"]))
        with transaction.atomic():  # một job lỗi → không job nào bị đổi
            for job in jobs:
                assign_job(job, data.validated_data, request.user, self.project)
        return Response({"updated": len(jobs)})

    @action(detail=False, methods=["post"], url_path="bulk-deadline")
    def bulk_deadline(self, request, project_id):
        ids = BulkSerializer(data=request.data)
        ids.is_valid(raise_exception=True)
        data = DeadlineSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        jobs = list(self.get_queryset().filter(pk__in=ids.validated_data["ids"]))
        with transaction.atomic():
            for job in jobs:
                set_job_deadline(job, data.validated_data["deadline"], data.validated_data["note"],
                                 request.user, self.project)
        return Response({"updated": len(jobs)})


class JobQueueView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/job-queue/ — Data Queue.

    Quyết định (đề xuất): Data Queue là CÁCH XEM job theo stage, không phải bảng hàng đợi
    riêng trong DB. Đủ để PM theo dõi backlog mà không cần Queue Engine.
    """

    required_capabilities = {"*": Cap.VIEW_JOBS}

    def get(self, request, project_id):
        jobs = Job.objects.filter(project=self.project)
        batch = request.query_params.get("batch")
        if batch:
            jobs = jobs.filter(batch_id=batch)
        now = timezone.now()
        result = []
        for stage in ("annotation", "qc1", "qc2"):
            stats = jobs.filter(status__in=STAGE_STATUSES[stage]).aggregate(
                total=Count("id"),
                unassigned=Count("id", filter=Q(annotator__isnull=True) if stage == "annotation"
                                 else Q(qc1_reviewer__isnull=True) if stage == "qc1" else Q(pk__isnull=True)),
                rework=Count("id", filter=Q(status=JobStatus.REWORK)),
                escalated=Count("id", filter=Q(is_escalated=True)),
                overdue=Count("id", filter=Q(deadline__lt=now)),
                locked=Count("id", filter=Q(is_locked=True)),
            )
            by_status = dict(
                jobs.filter(status__in=STAGE_STATUSES[stage]).values_list("status").annotate(n=Count("id"))
            )
            result.append({"stage": stage, **stats, "by_status": by_status})
        done = jobs.filter(status__in=STAGE_STATUSES["done"]).count()
        return Response({"stages": result, "done": done, "total": jobs.count()})
