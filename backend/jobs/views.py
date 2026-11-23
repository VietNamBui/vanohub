from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import Cap, ProjectScopedViewMixin
from projects.models import ActivityLog, DataStatus
from projects.views import StandardPagination
from quality.models import Audit, AuditSample

from .models import OPEN_STATUSES, STAGE_STATUSES, Job, JobStatus
from .serializers import (
    AnnotatorStartSerializer,
    AnnotatorSubmitSerializer,
    AssignSerializer,
    BulkSerializer,
    DeadlineSerializer,
    JobDetailSerializer,
    JobSerializer,
)


def _iso(value):
    return value.isoformat() if value else None


def _base_job_queryset(project):
    return Job.objects.filter(project=project).select_related(
        "batch__dataset", "annotator", "qc1_reviewer", "project"
    ).prefetch_related(Prefetch(
        "audit_samples",
        queryset=AuditSample.objects.filter(audit__status=Audit.Status.IN_PROGRESS).select_related("auditor"),
        to_attr="open_samples",
    ))


def ensure_editable(job):
    """Quy tắc chung trước khi sửa hoặc chuyển trạng thái một Job."""
    if job.is_locked:
        raise ValidationError(f"Job {job} đang bị khoá.")
    if job.batch.status != DataStatus.ACTIVE:
        raise ValidationError(f"Batch của job {job} đã khoá hoặc đã bàn giao.")
    if job.batch.dataset.status != DataStatus.ACTIVE:
        raise ValidationError(f"Dataset của job {job} đã khoá hoặc đã bàn giao.")
    if job.status == JobStatus.DELIVERED:
        raise ValidationError(f"Job {job} đã bàn giao.")


def ensure_not_escalated(job):
    if job.is_escalated:
        raise ValidationError("Job đang ở trạng thái Escalated, chờ PM xử lý.")


def lock_job(project, job_id):
    """Khoá dòng Job bằng select_for_update(of=("self",)) để an toàn trên PostgreSQL."""
    job = (
        Job.objects.select_for_update(of=("self",))
        .select_related("batch__dataset", "project", "annotator", "qc1_reviewer")
        .filter(pk=job_id, project=project)
        .first()
    )
    if job is None:
        raise NotFound("Không tìm thấy job trong dự án.")
    return job


@transaction.atomic
def start_annotation(job_id, *, project, actor, note=""):
    """Annotator bắt đầu gán nhãn hoặc sửa rework: PENDING_ANNOTATION / REWORK -> ANNOTATING."""
    job = lock_job(project, job_id)
    if job.annotator_id != actor.id:
        raise PermissionDenied("Bạn chỉ có thể thao tác trên job được giao cho mình.")
    ensure_editable(job)
    ensure_not_escalated(job)

    if job.status not in {JobStatus.PENDING_ANNOTATION, JobStatus.REWORK}:
        raise ValidationError(
            f"Chỉ bắt đầu gán nhãn khi job ở trạng thái Chờ annotate hoặc Rework "
            f"(hiện tại: {job.get_status_display()})."
        )

    prev_status = job.status
    job.status = JobStatus.ANNOTATING
    job.save(update_fields=["status", "updated_at"])
    ActivityLog.record(
        project=project,
        actor=actor,
        action="job.status",
        target=job,
        job=job,
        before={"status": prev_status},
        after={
            "status": JobStatus.ANNOTATING,
            "event": "annotator.start_rework" if prev_status == JobStatus.REWORK else "annotator.start",
            "rework_round": job.rework_round,
        },
        note=note,
    )
    return job


@transaction.atomic
def submit_annotation(job_id, *, project, actor, note="", object_count=None):
    """Annotator nộp bài sang hàng chờ QC1: ANNOTATING -> PENDING_QC1.

    Ghi action="job.status" với after.status="pending_qc1" để khớp với chỉ số
    submitted_in_period trong analytics.ProjectOverviewView.
    """
    job = lock_job(project, job_id)
    if job.annotator_id != actor.id:
        raise PermissionDenied("Bạn chỉ có thể nộp job được giao cho mình.")
    ensure_editable(job)
    ensure_not_escalated(job)

    if job.status != JobStatus.ANNOTATING:
        raise ValidationError(
            f"Chỉ có thể nộp bài khi job ở trạng thái Đang annotate "
            f"(hiện tại: {job.get_status_display()})."
        )

    prev_status = job.status
    prev_objects = job.object_count
    job.status = JobStatus.PENDING_QC1
    update_fields = ["status", "updated_at"]
    if object_count is not None:
        job.object_count = object_count
        update_fields.append("object_count")
    job.save(update_fields=update_fields)

    before = {"status": prev_status}
    after = {
        "status": JobStatus.PENDING_QC1,
        "event": "annotator.resubmit" if job.rework_round > 0 else "annotator.submit",
        "rework_round": job.rework_round,
    }
    if object_count is not None and object_count != prev_objects:
        before["object_count"] = prev_objects
        after["object_count"] = object_count

    ActivityLog.record(
        project=project,
        actor=actor,
        action="job.status",
        target=job,
        job=job,
        before=before,
        after=after,
        note=note,
    )
    return job


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
        queryset = _base_job_queryset(self.project)
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


ANNOTATOR_TABS = {
    "todo": [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING],
    "rework": [JobStatus.REWORK],
    "submitted": [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING, JobStatus.PENDING_QC2],
    "done": [JobStatus.APPROVED, JobStatus.DELIVERED],
}


class AnnotatorJobViewSet(
    ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Không gian làm việc của Annotator: chỉ thấy và thao tác trên job được giao cho mình."""

    pagination_class = StandardPagination
    lookup_value_regex = r"\d+"
    required_capabilities = {"*": Cap.ANNOTATE_JOBS}

    def get_serializer_class(self):
        return JobDetailSerializer if self.action == "retrieve" else JobSerializer

    def get_queryset(self):
        queryset = _base_job_queryset(self.project).filter(annotator=self.request.user)
        p = self.request.query_params
        tab = p.get("tab")
        if tab in ANNOTATOR_TABS:
            queryset = queryset.filter(status__in=ANNOTATOR_TABS[tab])
        if p.get("status"):
            queryset = queryset.filter(status__in=p["status"].split(","))
        if p.get("batch"):
            if not p["batch"].isdigit():
                raise ValidationError({"batch": "Mã batch không hợp lệ."})
            queryset = queryset.filter(batch_id=int(p["batch"]))
        if p.get("escalated") == "1":
            queryset = queryset.filter(is_escalated=True)
        if p.get("overdue") == "1":
            queryset = queryset.filter(deadline__lt=timezone.now(), status__in=OPEN_STATUSES)
        if p.get("search"):
            term = p["search"].strip()
            cond = Q(name__icontains=term) | Q(batch__name__icontains=term)
            if term.isdigit():
                cond |= Q(cvat_job_id=int(term)) | Q(pk=int(term))
            queryset = queryset.filter(cond)
        ordering = p.get("ordering")
        if ordering in {"deadline", "-deadline", "rework_round", "-rework_round", "updated_at", "-updated_at"}:
            queryset = queryset.order_by(ordering, "id")
        return queryset

    def _detail(self, job):
        fresh = _base_job_queryset(self.project).get(pk=job.pk)
        return Response(JobDetailSerializer(fresh, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def start(self, request, project_id, pk=None):
        """Bắt đầu gán nhãn hoặc bắt đầu sửa Rework (PENDING_ANNOTATION / REWORK -> ANNOTATING)."""
        job = self.get_object()
        serializer = AnnotatorStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = start_annotation(
            job.pk,
            project=self.project,
            actor=request.user,
            note=serializer.validated_data["note"],
        )
        return self._detail(updated)

    @action(detail=True, methods=["post"])
    def submit(self, request, project_id, pk=None):
        """Nộp bài sang hàng chờ QC1 (ANNOTATING -> PENDING_QC1)."""
        job = self.get_object()
        serializer = AnnotatorSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = submit_annotation(
            job.pk,
            project=self.project,
            actor=request.user,
            note=serializer.validated_data["note"],
            object_count=serializer.validated_data.get("object_count"),
        )
        return self._detail(updated)
