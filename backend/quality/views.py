import random

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from jobs.models import OPEN_STATUSES, Job, JobStatus
from jobs.serializers import JobDetailSerializer, JobSerializer
from jobs.views import ensure_editable, ensure_not_escalated, lock_job
from projects.models import ActivityLog, Batch, DataStatus, SamplingMethod, StratifyBy
from projects.views import StandardPagination

from . import sampling
from .models import Audit, AuditSample, ErrorCategory, ReviewError, ReviewStage
from .serializers import (
    AuditInputSerializer,
    AuditSampleSerializer,
    AuditSerializer,
    ErrorCategorySerializer,
    PassSerializer,
    Qc1RejectSerializer,
    Qc1StartSerializer,
    RejectSerializer,
    SampleJobSerializer,
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


def _strata_key(stratify_by):
    if stratify_by == StratifyBy.QC1_REVIEWER:
        return lambda job: job.qc1_reviewer.username if job.qc1_reviewer else "(chưa có QC1)"
    if stratify_by == StratifyBy.DATASET:
        return lambda job: job.batch.dataset.name
    return lambda job: job.annotator.username if job.annotator else "(chưa có annotator)"


def _four_eyes_conflicts(job):
    """Luật bốn mắt: không audit job mình đã annotate hoặc đã QC1."""
    return {uid for uid in (job.annotator_id, job.qc1_reviewer_id) if uid}


class AuditViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   viewsets.GenericViewSet):
    """QC2 Internal Audit.

    - Quản lý audit (tạo, xem trước mẫu, chốt): PM (Cap.MANAGE_AUDITS).
    - QC2 chuyên trách: chỉ thấy audit có mẫu được giao cho mình.
    Cùng một bộ API phục vụ cả PM và QC2 — không viết hai hệ thống audit.
    """

    serializer_class = AuditSerializer
    required_capabilities = {
        "list": [Cap.MANAGE_AUDITS, Cap.PERFORM_AUDIT],
        "retrieve": [Cap.MANAGE_AUDITS, Cap.PERFORM_AUDIT],
        "*": Cap.MANAGE_AUDITS,
    }

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

    def _prepare(self, request):
        """Kiểm tra đầu vào chung cho preview và create; trả về (dữ liệu, batch, danh sách job đủ điều kiện)."""
        serializer = AuditInputSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        batch = get_object_or_404(Batch, pk=data["batch"], dataset__project=self.project)
        if batch.status != DataStatus.ACTIVE:
            raise ValidationError("Batch đã khoá hoặc đã bàn giao.")
        if batch.audits.filter(status=Audit.Status.IN_PROGRESS).exists():
            raise ValidationError("Batch đang có một audit chưa chốt.")
        eligible = list(
            Job.objects.filter(batch=batch, status=JobStatus.PENDING_QC2, is_locked=False)
            .select_related("annotator", "qc1_reviewer", "batch__dataset")
            .order_by("id")
        )
        if not eligible:
            raise ValidationError("Batch không có job nào ở trạng thái Chờ QC2.")
        return data, batch, eligible

    def _pick(self, data, eligible):
        seed = data.get("seed") or random.SystemRandom().randrange(1, 2**53)
        if data["method"] == SamplingMethod.STRATIFIED:
            picked = sampling.stratified_sample(eligible, data["sampling_rate"], seed, _strata_key(data["stratify_by"]))
        else:
            picked = sampling.random_sample(eligible, data["sampling_rate"], seed)
        return seed, picked

    @action(detail=False, methods=["post"])
    def preview(self, request, project_id):
        """Xem trước mẫu (không lưu). Gửi lại `seed` khi tạo để chốt đúng mẫu đã xem."""
        data, batch, eligible = self._prepare(request)
        seed, picked = self._pick(data, eligible)
        return Response({
            "batch": batch.id, "method": data["method"], "sampling_rate": data["sampling_rate"],
            "stratify_by": data["stratify_by"] if data["method"] == SamplingMethod.STRATIFIED else "",
            "seed": seed, "eligible_count": len(eligible), "sample_count": len(picked),
            "estimated_objects": sum(job.object_count for job, _ in picked),
            "estimated_frames": sum(job.frame_count for job, _ in picked),
            "samples": [{"stratum": stratum, "job": SampleJobSerializer(job).data} for job, stratum in picked],
        })

    def create(self, request, project_id):
        data, batch, eligible = self._prepare(request)
        seed, picked = self._pick(data, eligible)
        assignment = sampling.assign_auditors([job for job, _ in picked], data["auditors"], _four_eyes_conflicts)
        with transaction.atomic():
            audit = Audit.objects.create(
                project=self.project, batch=batch, method=data["method"], sampling_rate=data["sampling_rate"],
                stratify_by=data["stratify_by"] if data["method"] == SamplingMethod.STRATIFIED else "",
                seed=seed, eligible_count=len(eligible), eligible_job_ids=[j.id for j in eligible],
                note=data["note"], created_by=request.user,
            )
            AuditSample.objects.bulk_create([
                AuditSample(audit=audit, job=job, stratum=stratum, auditor=assignment[job]) for job, stratum in picked
            ])
            ActivityLog.record(project=self.project, actor=request.user, action="audit.create", target=audit,
                               after={"method": audit.method, "rate": audit.sampling_rate,
                                      "eligible": len(eligible), "sampled": len(picked)})
        return Response(self.get_serializer(self.get_queryset().get(pk=audit.pk)).data, status=201)

    @action(detail=True, methods=["post"])
    def complete(self, request, project_id, pk=None):
        """Chốt audit: job đủ điều kiện nhưng KHÔNG được lấy mẫu → Đã duyệt.

        ĐỀ XUẤT (L4 bỏ qua trong MVP): không có bước PM accept/reject cả batch.
        """
        audit = self.get_object()
        if audit.status != Audit.Status.IN_PROGRESS:
            raise ValidationError("Audit đã được chốt.")
        if audit.samples.filter(result=AuditSample.Result.PENDING).exists():
            raise ValidationError("Còn mẫu chưa audit.")
        sampled = set(audit.samples.values_list("job_id", flat=True))
        with transaction.atomic():
            approved = Job.objects.filter(
                pk__in=set(audit.eligible_job_ids) - sampled, status=JobStatus.PENDING_QC2
            ).update(status=JobStatus.APPROVED)
            audit.status = Audit.Status.COMPLETED
            audit.completed_at = timezone.now()
            audit.save(update_fields=["status", "completed_at"])
            ActivityLog.record(project=self.project, actor=request.user, action="audit.complete", target=audit,
                               after={"approved_without_sampling": approved})
        return Response(self.get_serializer(self.get_queryset().get(pk=audit.pk)).data)


class AuditSampleViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    """Thực hiện QC2: Pass / Reject từng job được lấy mẫu."""

    serializer_class = AuditSampleSerializer
    required_capabilities = {"assign": Cap.MANAGE_AUDITS, "*": Cap.PERFORM_AUDIT}

    def get_queryset(self):
        queryset = AuditSample.objects.filter(audit__project=self.project).select_related(
            "audit", "job__annotator", "job__qc1_reviewer", "job__batch", "auditor", "reviewed_by"
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
            raise ValidationError("Audit đã chốt.")
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
        ActivityLog.record(project=self.project, actor=request.user, action="qc2.assign_auditor", target=sample.job,
                           job=sample.job, after={"auditor": auditor.username})
        return Response(self.get_serializer(self.get_queryset().get(pk=sample.pk)).data)


SAMPLING_FIELDS = ("sampling_method", "sampling_rate", "stratify_by")


class AuditStrategyView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/audit-strategy/ — chiến thuật lấy mẫu QC2 đang áp dụng.

    Chỉ dành cho PM (PM luôn kiêm QC2); QC2 chuyên trách không có màn hình này.
    PM sửa qua /settings/. Kèm lịch sử thay đổi và các batch có thể xem trước mẫu.
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
        batches = (
            Batch.objects.filter(dataset__project=project, status=DataStatus.ACTIVE)
            .exclude(audits__status=Audit.Status.IN_PROGRESS)
            .annotate(pending_qc2=Count("jobs", filter=Q(jobs__status=JobStatus.PENDING_QC2, jobs__is_locked=False)))
            .filter(pending_qc2__gt=0)
            .select_related("dataset")
            .order_by("dataset__name", "name")
        )
        return Response({
            "method": project.sampling_method,
            "sampling_rate": project.sampling_rate,
            "stratify_by": project.stratify_by,
            "can_edit": self.has_cap(Cap.MANAGE_SETTINGS),
            "history": history[:20],
            "preview_batches": [
                {"id": b.id, "name": b.name, "dataset_name": b.dataset.name, "pending_qc2": b.pending_qc2} for b in batches
            ],
        })


QC1_TABS = {
    "queue": [JobStatus.PENDING_QC1],
    "reviewing": [JobStatus.QC1_REVIEWING],
    "done": [JobStatus.REWORK, JobStatus.PENDING_QC2, JobStatus.APPROVED, JobStatus.DELIVERED],
}
QC1_REVIEWABLE_STATUSES = {JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING}


def _check_qc1_access(job, actor):
    """Luật bốn mắt + kiểm tra quyền sở hữu QC1, khoá và escalation."""
    if job.annotator_id and job.annotator_id == actor.id:
        raise PermissionDenied("Luật bốn mắt: bạn không thể QC1 job do chính mình annotate.")
    if job.qc1_reviewer_id and job.qc1_reviewer_id != actor.id:
        raise PermissionDenied("Job này đã được giao cho người QC1 khác.")
    ensure_editable(job)
    ensure_not_escalated(job)


@transaction.atomic
def start_qc1(job_id, *, project, actor, note=""):
    """QC1 bắt đầu kiểm tra job: PENDING_QC1 -> QC1_REVIEWING (tự nhận nếu chưa có qc1_reviewer)."""
    job = lock_job(project, job_id)
    _check_qc1_access(job, actor)
    if job.status != JobStatus.PENDING_QC1:
        raise ValidationError(
            f"Chỉ bắt đầu QC1 khi job ở trạng thái Chờ QC1 (hiện tại: {job.get_status_display()})."
        )

    job.status = JobStatus.QC1_REVIEWING
    update_fields = ["status", "updated_at"]
    if not job.qc1_reviewer_id:
        job.qc1_reviewer = actor
        update_fields.append("qc1_reviewer")
    job.save(update_fields=update_fields)
    ActivityLog.record(
        project=project,
        actor=actor,
        action="qc1.start",
        target=job,
        job=job,
        before={"status": JobStatus.PENDING_QC1},
        after={"status": JobStatus.QC1_REVIEWING, "qc1_reviewer": actor.username},
        note=note,
    )
    return job


@transaction.atomic
def qc1_pass(job_id, *, project, actor, comment=""):
    """QC1 duyệt đạt: PENDING_QC1 / QC1_REVIEWING -> PENDING_QC2."""
    job = lock_job(project, job_id)
    _check_qc1_access(job, actor)
    if job.status not in QC1_REVIEWABLE_STATUSES:
        raise ValidationError(
            f"Chỉ có thể duyệt QC1 khi job đang Chờ QC1 hoặc Đang QC1 (hiện tại: {job.get_status_display()})."
        )

    prev_status = job.status
    job.status = JobStatus.PENDING_QC2
    update_fields = ["status", "updated_at"]
    if not job.qc1_reviewer_id:
        job.qc1_reviewer = actor
        update_fields.append("qc1_reviewer")
    job.save(update_fields=update_fields)
    ActivityLog.record(
        project=project,
        actor=actor,
        action="qc1.pass",
        target=job,
        job=job,
        before={"status": prev_status},
        after={"status": JobStatus.PENDING_QC2, "rework_round": job.rework_round},
        note=comment,
    )
    return job


@transaction.atomic
def qc1_reject(job_id, *, project, actor, errors, comment=""):
    """QC1 trả về Rework: ghi ReviewError (stage=QC1), tăng rework_round, vượt ngưỡng -> is_escalated."""
    job = lock_job(project, job_id)
    _check_qc1_access(job, actor)
    if job.status not in QC1_REVIEWABLE_STATUSES:
        raise ValidationError(
            f"Chỉ có thể trả rework QC1 khi job đang Chờ QC1 hoặc Đang QC1 (hiện tại: {job.get_status_display()})."
        )

    prev_status = job.status
    round_at_review = job.rework_round
    ReviewError.objects.bulk_create([
        ReviewError(
            job=job,
            stage=ReviewStage.QC1,
            rework_round=round_at_review,
            audit_sample=None,
            category=e["category"],
            severity=e.get("severity") or e["category"].severity,
            location=e["location"],
            description=e["description"],
            reported_by=actor,
        )
        for e in errors
    ])
    job.status = JobStatus.REWORK
    job.rework_round += 1
    if job.rework_round > project.max_rework_rounds:
        job.is_escalated = True
    update_fields = ["status", "rework_round", "is_escalated", "updated_at"]
    if not job.qc1_reviewer_id:
        job.qc1_reviewer = actor
        update_fields.append("qc1_reviewer")
    job.save(update_fields=update_fields)
    ActivityLog.record(
        project=project,
        actor=actor,
        action="qc1.reject",
        target=job,
        job=job,
        before={"status": prev_status},
        after={
            "status": JobStatus.REWORK,
            "rework_round": job.rework_round,
            "errors": len(errors),
            "escalated": job.is_escalated,
        },
        note=comment,
    )
    return job


class Qc1JobViewSet(
    ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Không gian làm việc Level 1 QC (QC1 & Team Leader):
    xem hàng chờ QC1, nhận kiểm tra, Pass sang QC2 hoặc Reject trả về Rework kèm danh mục lỗi.
    """

    pagination_class = StandardPagination
    lookup_value_regex = r"\d+"
    required_capabilities = {"*": Cap.PERFORM_QC1}

    def get_serializer_class(self):
        return JobDetailSerializer if self.action == "retrieve" else JobSerializer

    def _base_queryset(self):
        return Job.objects.filter(project=self.project).select_related(
            "batch__dataset", "annotator", "qc1_reviewer", "project"
        ).prefetch_related(Prefetch(
            "audit_samples",
            queryset=AuditSample.objects.filter(audit__status=Audit.Status.IN_PROGRESS).select_related("auditor"),
            to_attr="open_samples",
        ))

    def get_queryset(self):
        queryset = self._base_queryset()
        user = self.request.user

        if self.action == "retrieve":
            return queryset.filter(
                Q(qc1_reviewer=user) | Q(qc1_reviewer__isnull=True, status=JobStatus.PENDING_QC1)
            ).exclude(annotator=user)

        queryset = queryset.exclude(annotator=user)
        p = self.request.query_params
        scope = p.get("scope", "mine")
        pool_filter = Q(
            qc1_reviewer__isnull=True,
            status=JobStatus.PENDING_QC1,
            is_locked=False,
            is_escalated=False,
        )
        if scope == "pool":
            queryset = queryset.filter(pool_filter)
        elif scope == "all":
            queryset = queryset.filter(Q(qc1_reviewer=user) | pool_filter)
        else:
            queryset = queryset.filter(qc1_reviewer=user)

        tab = p.get("tab")
        if tab in QC1_TABS:
            queryset = queryset.filter(status__in=QC1_TABS[tab])
        if p.get("status"):
            queryset = queryset.filter(status__in=p["status"].split(","))
        if p.get("batch"):
            if not p["batch"].isdigit():
                raise ValidationError({"batch": "Mã batch không hợp lệ."})
            queryset = queryset.filter(batch_id=int(p["batch"]))
        if p.get("annotator"):
            if not p["annotator"].isdigit():
                raise ValidationError({"annotator": "Mã annotator không hợp lệ."})
            queryset = queryset.filter(annotator_id=int(p["annotator"]))
        if p.get("overdue") == "1":
            queryset = queryset.filter(deadline__lt=timezone.now(), status__in=OPEN_STATUSES)
        if p.get("search"):
            term = p["search"].strip()
            cond = Q(name__icontains=term) | Q(batch__name__icontains=term) | Q(annotator__username__icontains=term)
            if term.isdigit():
                cond |= Q(cvat_job_id=int(term)) | Q(pk=int(term))
            queryset = queryset.filter(cond)
        ordering = p.get("ordering")
        if ordering in {"deadline", "-deadline", "rework_round", "-rework_round", "updated_at", "-updated_at"}:
            queryset = queryset.order_by(ordering, "id")
        return queryset

    def _detail(self, job):
        fresh = self._base_queryset().get(pk=job.pk)
        return Response(JobDetailSerializer(fresh, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def start(self, request, project_id, pk=None):
        """Bắt đầu kiểm tra QC1 (PENDING_QC1 -> QC1_REVIEWING; tự nhận nếu job chưa có qc1_reviewer)."""
        serializer = Qc1StartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = start_qc1(
            int(pk),
            project=self.project,
            actor=request.user,
            note=serializer.validated_data["note"],
        )
        return self._detail(updated)

    @action(detail=True, methods=["post"], url_path="pass")
    def pass_(self, request, project_id, pk=None):
        """Duyệt đạt QC1 (PENDING_QC1 / QC1_REVIEWING -> PENDING_QC2)."""
        serializer = PassSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = qc1_pass(
            int(pk),
            project=self.project,
            actor=request.user,
            comment=serializer.validated_data["comment"],
        )
        return self._detail(updated)

    @action(detail=True, methods=["post"])
    def reject(self, request, project_id, pk=None):
        """Trả về Rework từ QC1: bắt buộc ghi ít nhất 1 lỗi (ReviewError stage=qc1)."""
        serializer = Qc1RejectSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        updated = qc1_reject(
            int(pk),
            project=self.project,
            actor=request.user,
            errors=serializer.validated_data["errors"],
            comment=serializer.validated_data["comment"],
        )
        return self._detail(updated)
