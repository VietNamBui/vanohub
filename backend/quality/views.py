from accounts.datetime_utils import PG_INT32_MAX, format_local_datetime, parse_int_param
from accounts.models import Role, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from cvat_integration.assignee import schedule_assignee_push
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
from django.utils import timezone
from jobs.models import OPEN_STATUSES, Job, JobStatus, ReworkScope
from jobs.serializers import JobDetailSerializer, JobSerializer
from jobs.views import ensure_editable, ensure_not_escalated, lock_job
from projects.models import ActivityLog, DataStatus, UserNotification
from projects.views import StandardPagination
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Audit, AuditSample, ErrorCategory, ReviewError, ReviewStage
from .qc2 import ANNOTATOR_EVENTS, ensure_qc2_sample, four_eyes_conflicts, get_stage_history
from .serializers import (
    AuditSampleSerializer,
    AuditSerializer,
    ErrorCategorySerializer,
    PassSerializer,
    Qc1RejectSerializer,
    Qc1StartSerializer,
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
            queryset = queryset.filter(batch_id=parse_int_param(p["batch"], "batch"))
        return queryset


class AuditSampleViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                         viewsets.GenericViewSet):
    """Thực hiện QC2: Pass / Reject từng job được lấy mẫu."""

    serializer_class = AuditSampleSerializer
    required_capabilities = {"assign": Cap.MANAGE_AUDITS, "*": Cap.PERFORM_AUDIT}

    def _base_queryset(self):
        return (
            AuditSample.objects.filter(audit__project=self.project)
            .select_related(
                "audit",
                "job__annotator",
                "job__qc1_reviewer",
                "job__batch",
                "job__dataset",
                "auditor",
                "reviewed_by",
            )
            .prefetch_related("errors__category", "errors__reported_by")
        )

    def get_queryset(self):
        queryset = self._base_queryset()
        p = self.request.query_params
        if not self.has_cap(Cap.MANAGE_AUDITS) or p.get("mine") == "1":
            queryset = queryset.filter(auditor=self.request.user)
        if p.get("audit"):
            queryset = queryset.filter(audit_id=parse_int_param(p["audit"], "audit"))
        if p.get("result"):
            queryset = queryset.filter(result=p["result"])
        if p.get("open") == "1":
            queryset = queryset.filter(audit__status=Audit.Status.IN_PROGRESS)
        return queryset

    def _lock_sample_and_job(self, pk):
        """Khoá đồng thời AuditSample và Job trước khi kiểm tra điều kiện và cập nhật trạng thái."""
        try:
            sample_id = parse_int_param(pk, "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy mẫu QC2.") from exc
        sample = (
            AuditSample.objects.select_for_update(of=("self",))
            .select_related("audit", "job", "job__batch", "job__dataset")
            .filter(pk=sample_id, audit__project=self.project)
            .first()
        )
        if sample is None:
            raise NotFound("Không tìm thấy mẫu QC2.")
        job = (
            Job.objects.select_for_update(of=("self",))
            .select_related("batch", "dataset", "project", "annotator", "qc1_reviewer")
            .get(pk=sample.job_id)
        )
        sample.job = job
        return sample, job

    def _check_can_review(self, sample):
        user = self.request.user
        if sample.audit.status != Audit.Status.IN_PROGRESS:
            raise ValidationError("Task đã bàn giao, đợt QC2 đã chốt.")
        if sample.result != AuditSample.Result.PENDING:
            raise ValidationError("Mẫu này đã có kết quả.")
        if sample.auditor_id and sample.auditor_id != user.id and not self.has_cap(Cap.MANAGE_AUDITS):
            raise PermissionDenied("Mẫu này được giao cho auditor khác.")
        if user.id in four_eyes_conflicts(sample.job):
            raise PermissionDenied("Luật bốn mắt: bạn đã annotate hoặc QC1 job này.")
        ensure_editable(sample.job)
        ensure_not_escalated(sample.job)
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
        with transaction.atomic():
            sample, job = self._lock_sample_and_job(pk)
            self._check_can_review(sample)
            serializer = PassSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self._finish(sample, AuditSample.Result.PASS, serializer.validated_data["comment"])
            job.status = JobStatus.APPROVED
            job.save(update_fields=["status", "updated_at"])
            schedule_assignee_push([job.pk])
            ActivityLog.record(project=self.project, actor=request.user, action="qc2.pass", target=job, job=job,
                               before={"status": JobStatus.PENDING_QC2}, after={"status": JobStatus.APPROVED})
        return Response(self.get_serializer(self._base_queryset().get(pk=sample.pk)).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, project_id, pk=None):
        """Reject → ghi lỗi, job về Rework, tăng vòng rework, vượt ngưỡng thì Escalated.

        Lưu ý: chưa đẩy trạng thái ngược về CVAT (chỉ đọc CVAT ở giai đoạn này).
        """
        with transaction.atomic():
            sample, job = self._lock_sample_and_job(pk)
            self._check_can_review(sample)
            serializer = RejectSerializer(data=request.data, context=self.get_serializer_context())
            serializer.is_valid(raise_exception=True)
            errors = serializer.validated_data["errors"]
            rework_scope = serializer.validated_data["rework_scope"]
            self._finish(sample, AuditSample.Result.REJECT, serializer.validated_data["comment"])
            ReviewError.objects.bulk_create([
                ReviewError(
                    job=job, stage=ReviewStage.QC2, rework_round=job.rework_round, audit_sample=sample,
                    category=e["category"], severity=e.get("severity") or e["category"].severity,
                    location=e["location"], description=e["description"], reported_by=request.user,
                )
                for e in errors
            ])
            job.status = JobStatus.REWORK
            job.rework_round += 1
            job.total_rework_rounds += 1
            job.rework_scope = rework_scope
            if job.rework_round > self.project.max_rework_rounds:
                job.is_escalated = True
            job.save(
                update_fields=[
                    "status",
                    "rework_round",
                    "total_rework_rounds",
                    "rework_scope",
                    "is_escalated",
                    "updated_at",
                ]
            )
            schedule_assignee_push([job.pk])  # Rework → job quay về annotator
            ActivityLog.record(
                project=self.project, actor=request.user, action="qc2.reject", target=job, job=job,
                before={"status": JobStatus.PENDING_QC2},
                after={"status": JobStatus.REWORK, "rework_round": job.rework_round,
                       "rework_scope": rework_scope, "errors": len(errors), "escalated": job.is_escalated},
            )
            if job.annotator and job.annotator.notify_rework:
                deadline_txt = (
                    f" Hạn sửa {format_local_datetime(job.deadline)}." if job.deadline else ""
                )
                UserNotification.objects.create(
                    recipient=job.annotator,
                    project=self.project,
                    job=job,
                    category=UserNotification.Category.REWORK,
                    title=f"{job.name} bị trả sửa từ QC2 (vòng {job.rework_round})",
                    body=f"QC2 ghi {len(errors)} lỗi theo object-frame.{deadline_txt}",
                    action_url=f"/projects/{self.project.id}/annotator/jobs/{job.id}",
                    is_pinned_pending=True,
                )
        return Response(self.get_serializer(self._base_queryset().get(pk=sample.pk)).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, project_id, pk=None):
        """PM phân (lại) auditor cho một mẫu."""
        with transaction.atomic():
            sample, job = self._lock_sample_and_job(pk)
            if sample.audit.status != Audit.Status.IN_PROGRESS:
                raise ValidationError("Task đã bàn giao, đợt QC2 đã chốt.")
            if sample.result != AuditSample.Result.PENDING:
                raise ValidationError("Mẫu đã có kết quả.")
            ensure_editable(job)
            ensure_not_escalated(job)
            auditor_id = parse_int_param(request.data.get("auditor"), "auditor")
            auditor = User.objects.filter(pk=auditor_id, is_active=True).first()
            if not auditor or Role.QC2 not in auditor.get_project_roles(self.project):
                raise ValidationError("Auditor phải có quyền QC2 trong dự án.")
            if auditor.id in four_eyes_conflicts(job):
                raise ValidationError("Luật bốn mắt: người này đã annotate hoặc QC1 job.")
            sample.auditor = auditor
            sample.save(update_fields=["auditor"])
            schedule_assignee_push([sample.job_id])
            ActivityLog.record(project=self.project, actor=request.user, action="qc2.assign_auditor", target=job,
                               job=job, after={"auditor": auditor.username})
        return Response(self.get_serializer(self._base_queryset().get(pk=sample.pk)).data)


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


QC1_TABS = {
    "queue": [JobStatus.PENDING_QC1],
    "reviewing": [JobStatus.QC1_REVIEWING],
    "done": [JobStatus.REWORK, JobStatus.PENDING_QC2, JobStatus.APPROVED, JobStatus.DELIVERED],
}
QC1_REVIEWABLE_STATUSES = {JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING}


def _check_qc1_access(job, actor):
    """Luật bốn mắt đa giai đoạn (kể cả lịch sử) + kiểm tra quyền sở hữu QC1, khoá và escalation."""
    annotator_ids, _, qc2_ids = get_stage_history(job)
    if actor.id in annotator_ids:
        raise PermissionDenied("Luật bốn mắt: bạn không thể QC1 job đã từng do chính mình annotate.")
    if actor.id in qc2_ids:
        raise PermissionDenied("Luật bốn mắt: bạn không thể QC1 job đã từng do chính mình audit QC2.")
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
    schedule_assignee_push([job.pk])
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
    """QC1 duyệt đạt: PENDING_QC1 / QC1_REVIEWING -> PENDING_QC2 và tự tạo lượt QC2 theo frame."""
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
    ensure_qc2_sample(job)
    schedule_assignee_push([job.pk])
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
    if job.annotator and job.annotator.notify_qc_pass:
        body = (
            "Job đạt ngay lần kiểm đầu — FPY được tính."
            if job.rework_round == 0 and job.total_rework_rounds == 0
            else f"Job đạt QC1 sau vòng sửa {job.rework_round}."
        )
        UserNotification.objects.create(
            recipient=job.annotator,
            project=project,
            job=job,
            category=UserNotification.Category.QC_PASS,
            title=f"{job.name} đạt QC1",
            body=body,
            action_url=f"/projects/{project.id}/annotator/jobs/{job.id}",
        )
    return job


@transaction.atomic
def qc1_reject(job_id, *, project, actor, errors, comment="", rework_scope=ReworkScope.PARTIAL):
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
    job.total_rework_rounds += 1
    job.rework_scope = rework_scope
    if job.rework_round > project.max_rework_rounds:
        job.is_escalated = True
    update_fields = [
        "status",
        "rework_round",
        "total_rework_rounds",
        "rework_scope",
        "is_escalated",
        "updated_at",
    ]
    if not job.qc1_reviewer_id:
        job.qc1_reviewer = actor
        update_fields.append("qc1_reviewer")
    job.save(update_fields=update_fields)
    schedule_assignee_push([job.pk])
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
            "rework_scope": rework_scope,
            "errors": len(errors),
            "escalated": job.is_escalated,
        },
        note=comment,
    )
    if job.annotator and job.annotator.notify_rework:
        deadline_txt = (
            f" Hạn sửa {format_local_datetime(job.deadline)}." if job.deadline else ""
        )
        UserNotification.objects.create(
            recipient=job.annotator,
            project=project,
            job=job,
            category=UserNotification.Category.REWORK,
            title=f"{job.name} bị trả sửa (vòng {job.rework_round})",
            body=f"QC1 ghi {len(errors)} lỗi theo object-frame.{deadline_txt}",
            action_url=f"/projects/{project.id}/annotator/jobs/{job.id}",
            is_pinned_pending=True,
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
        return (
            Job.objects.filter(project=self.project)
            .select_related("batch", "dataset", "annotator", "qc1_reviewer", "project")
            .annotate(
                _active_rework_error_count=Count(
                    "review_errors",
                    filter=Q(
                        status__in=[JobStatus.REWORK, JobStatus.ANNOTATING],
                        rework_round__gt=0,
                        review_errors__rework_round=F("rework_round") - 1,
                    ),
                    distinct=True,
                )
            )
            .prefetch_related(
                Prefetch(
                    "audit_samples",
                    queryset=AuditSample.objects.filter(
                        audit__status=Audit.Status.IN_PROGRESS,
                        result=AuditSample.Result.PENDING,
                    )
                    .select_related("auditor")
                    .order_by("-id"),
                    to_attr="open_samples",
                )
            )
        )

    def _exclude_four_eyes_conflicts(self, queryset, user):
        hist_ann_job_ids = (
            ActivityLog.objects.filter(project=self.project, actor=user, job_id__isnull=False)
            .filter(
                Q(action__in=ANNOTATOR_EVENTS)
                | Q(action__in=("job.status", "job.assign"), after__event__in=ANNOTATOR_EVENTS)
            )
            .values("job_id")
        )
        hist_qc2_sample_job_ids = (
            AuditSample.objects.filter(audit__project=self.project)
            .filter(Q(auditor=user) | Q(reviewed_by=user))
            .values("job_id")
        )
        hist_qc2_err_job_ids = ReviewError.objects.filter(
            job__project=self.project, stage=ReviewStage.QC2, reported_by=user
        ).values("job_id")
        return queryset.exclude(
            Q(annotator=user)
            | Q(pk__in=hist_ann_job_ids)
            | Q(pk__in=hist_qc2_sample_job_ids)
            | Q(pk__in=hist_qc2_err_job_ids)
        )

    def get_queryset(self):
        queryset = self._exclude_four_eyes_conflicts(self._base_queryset(), self.request.user)
        user = self.request.user
        pool_filter = Q(
            qc1_reviewer__isnull=True,
            status=JobStatus.PENDING_QC1,
            is_locked=False,
            is_escalated=False,
            batch__status=DataStatus.ACTIVE,
            dataset__status=DataStatus.ACTIVE,
        )

        if self.action == "retrieve":
            return queryset.filter(Q(qc1_reviewer=user) | pool_filter)

        p = self.request.query_params
        scope = p.get("scope", "mine")
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
            queryset = queryset.filter(batch_id=parse_int_param(p["batch"], "batch"))
        if p.get("annotator"):
            queryset = queryset.filter(annotator_id=parse_int_param(p["annotator"], "annotator"))
        if p.get("overdue") == "1":
            queryset = queryset.filter(deadline__lt=timezone.now(), status__in=OPEN_STATUSES)
        if p.get("search"):
            term = p["search"].strip()
            cond = Q(name__icontains=term) | Q(batch__name__icontains=term) | Q(annotator__username__icontains=term)
            if term.isdigit():
                num = int(term)
                if num <= PG_INT32_MAX:
                    cond |= Q(cvat_job_id=num) | Q(pk=num)
            queryset = queryset.filter(cond)
        ordering = p.get("ordering")
        if ordering in {"deadline", "-deadline", "rework_round", "-rework_round", "updated_at", "-updated_at"}:
            queryset = queryset.order_by(ordering, "id")
        else:
            queryset = queryset.order_by("deadline", "id")
        return queryset

    def _parse_job_pk(self, pk):
        try:
            return parse_int_param(pk, "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy job trong organization.") from exc

    def _detail(self, job):
        fresh = self._base_queryset().get(pk=job.pk)
        return Response(JobDetailSerializer(fresh, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def start(self, request, project_id, pk=None):
        """Bắt đầu kiểm tra QC1 (PENDING_QC1 -> QC1_REVIEWING; tự nhận nếu job chưa có qc1_reviewer)."""
        job_id = self._parse_job_pk(pk)
        serializer = Qc1StartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = start_qc1(
            job_id,
            project=self.project,
            actor=request.user,
            note=serializer.validated_data["note"],
        )
        return self._detail(updated)

    @action(detail=True, methods=["post"], url_path="pass")
    def pass_(self, request, project_id, pk=None):
        """Duyệt đạt QC1 (PENDING_QC1 / QC1_REVIEWING -> PENDING_QC2)."""
        job_id = self._parse_job_pk(pk)
        serializer = PassSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = qc1_pass(
            job_id,
            project=self.project,
            actor=request.user,
            comment=serializer.validated_data["comment"],
        )
        return self._detail(updated)

    @action(detail=True, methods=["post"])
    def reject(self, request, project_id, pk=None):
        """Trả về Rework từ QC1: bắt buộc ghi ít nhất 1 lỗi (ReviewError stage=qc1)."""
        job_id = self._parse_job_pk(pk)
        serializer = Qc1RejectSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        updated = qc1_reject(
            job_id,
            project=self.project,
            actor=request.user,
            errors=serializer.validated_data["errors"],
            comment=serializer.validated_data["comment"],
            rework_scope=serializer.validated_data["rework_scope"],
        )
        return self._detail(updated)
