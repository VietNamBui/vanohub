from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Count, F, Prefetch, Q
from django.db.models.functions import Greatest
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.datetime_utils import PG_INT32_MAX, app_timezone, format_rfc3339_utc, parse_int_param
from accounts.models import Role, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.serializers import UserBriefSerializer
from accounts.validation import validated_dict
from cvat_integration.assignee import schedule_assignee_push
from jobs.models import OPEN_STATUSES, FirstQc1Result, Job, JobStatus, ReworkScope
from jobs.serializers import JobDetailSerializer, JobSerializer
from jobs.views import ensure_editable, ensure_not_escalated, lock_job, order_by_db06_priority
from projects.models import ActivityLog, DataStatus, EscalationPolicy, UserNotification
from projects.notifications import (
    notify_assigned,
    notify_batch_ready_for_qc2,
    notify_escalated,
    notify_rework,
    user_team_ids,
)
from projects.views import StandardPagination

from .models import Audit, AuditSample, ErrorCategory, ErrorVerdict, ReviewError, ReviewStage
from .qc2 import ANNOTATOR_EVENTS, ensure_qc2_sample, four_eyes_conflicts, get_stage_history
from .serializers import (
    AssignAuditorSerializer,
    AuditSampleSerializer,
    AuditSerializer,
    ErrorCategorySerializer,
    PassSerializer,
    Qc1RejectSerializer,
    Qc1StartSerializer,
    RejectSerializer,
)


class ErrorCategoryViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Danh mục lỗi. Không xoá (lỗi đã ghi đang tham chiếu) — tắt bằng is_active=false."""

    serializer_class = ErrorCategorySerializer
    required_capabilities = {"list": Cap.VIEW_PROJECT, "*": Cap.MANAGE_QUALITY_CATALOG}

    def get_queryset(self) -> Any:
        queryset = ErrorCategory.objects.filter(project=self.project)
        stage = self.request.query_params.get("stage")
        if stage in ("qc1", "qc2"):
            queryset = queryset.filter(applies_to__in=[stage, "both"], is_active=True)
        return queryset

    def perform_create(self, serializer: Any) -> None:
        category = serializer.save(project=self.project)
        ActivityLog.record(
            project=self.project,
            actor=self.request.user,
            action="error_category.create",
            target=category,
        )

    def perform_update(self, serializer: Any) -> None:
        category = serializer.save()
        ActivityLog.record(
            project=self.project,
            actor=self.request.user,
            action="error_category.update",
            target=category,
        )


class AuditViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Các đợt QC2 theo task — CHỈ ĐỌC.

    Đợt QC2 tự tạo khi job đầu tiên của task vào Chờ QC2 (quality/qc2.py) và tự chốt khi task bàn giao.
    PM (Cap.MANAGE_AUDITS / Cap.VIEW_DASHBOARD) thấy mọi đợt; QC2 chuyên trách chỉ thấy đợt có lượt của mình.
    """

    serializer_class = AuditSerializer
    required_capabilities = {"*": [Cap.MANAGE_AUDITS, Cap.PERFORM_AUDIT, Cap.VIEW_DASHBOARD]}

    def get_queryset(self) -> Any:
        queryset = (
            Audit.objects.filter(project=self.project)
            .select_related("batch__dataset")
            .annotate(
                sample_count=Count("samples"),
                passed=Count("samples", filter=Q(samples__result=AuditSample.Result.PASS)),
                rejected=Count("samples", filter=Q(samples__result=AuditSample.Result.REJECT)),
                pending=Count("samples", filter=Q(samples__result=AuditSample.Result.PENDING)),
            )
        )
        if not (self.has_cap(Cap.MANAGE_AUDITS) or self.has_cap(Cap.VIEW_DASHBOARD)):
            queryset = queryset.filter(samples__auditor=self.request.user).distinct()
        p = self.request.query_params
        if p.get("status"):
            queryset = queryset.filter(status=p["status"])
        if p.get("batch"):
            queryset = queryset.filter(batch_id=parse_int_param(p["batch"], "batch"))
        return queryset


class AuditSampleViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Thực hiện QC2 theo frame: Pass / Reject từng lượt audit và PM phân auditor."""

    serializer_class = AuditSampleSerializer
    required_capabilities = {"assign": Cap.MANAGE_AUDITS, "*": Cap.PERFORM_AUDIT}

    def _base_queryset(self) -> Any:
        return (
            AuditSample.objects.filter(audit__project=self.project)
            .select_related(
                "audit",
                "job__annotator",
                "job__qc1_reviewer",
                "job__batch",
                "job__dataset",
                "job__project",
                "auditor",
                "reviewed_by",
            )
            .prefetch_related("errors__category", "errors__reported_by")
        )

    def get_queryset(self) -> Any:
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

    def _lock_sample_and_job(self, pk: Any) -> tuple[AuditSample, Job]:
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

    def _check_can_review(self, sample: AuditSample) -> None:
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

    def _finish(self, sample: AuditSample, result: str, comment: str) -> None:
        """Cập nhật kết quả lượt QC2; giữ nguyên checked_object_count=None khi chưa chốt định nghĩa theo frame."""
        sample.result = result
        sample.reviewed_by = self.request.user
        sample.reviewed_at = timezone.now()
        sample.comment = comment
        if not sample.auditor_id:
            sample.auditor = self.request.user
        sample.save(update_fields=["result", "reviewed_by", "reviewed_at", "comment", "auditor"])

    @action(detail=True, methods=["post"], url_path="pass")
    def pass_(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        with transaction.atomic():
            sample, job = self._lock_sample_and_job(pk)
            self._check_can_review(sample)
            data = validated_dict(PassSerializer(data=request.data))
            self._finish(sample, AuditSample.Result.PASS, data["comment"])
            job.status = JobStatus.APPROVED
            job.save(update_fields=["status", "updated_at"])
            schedule_assignee_push([job.pk])
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="qc2.pass",
                target=job,
                job=job,
                before={"status": JobStatus.PENDING_QC2},
                after={"status": JobStatus.APPROVED},
                note=data["comment"],
            )
        return Response(self.get_serializer(self._base_queryset().get(pk=sample.pk)).data)

    @action(detail=True, methods=["post"])
    def reject(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        """Reject → ghi lỗi cấu trúc, job về Rework, tăng vòng rework, vượt ngưỡng thì Escalated."""
        with transaction.atomic():
            sample, job = self._lock_sample_and_job(pk)
            self._check_can_review(sample)
            data = validated_dict(RejectSerializer(data=request.data, context=self.get_serializer_context()))
            errors = data["errors"]
            rework_scope = data["rework_scope"]
            comment = data["comment"]
            self._finish(sample, AuditSample.Result.REJECT, comment)

            round_at_review = max(job.total_rework_rounds, job.rework_round)
            ReviewError.objects.bulk_create([
                ReviewError(
                    job=job,
                    stage=ReviewStage.QC2,
                    rework_round=round_at_review,
                    audit_sample=sample,
                    category=e["category"],
                    severity=e.get("severity") or e["category"].severity,
                    verdict=e.get("verdict") or ErrorVerdict.FAIL,
                    frame_number=e.get("frame_number"),
                    cvat_object_id=e.get("cvat_object_id"),
                    is_missing_object=bool(e.get("is_missing_object", False)),
                    location=e["location"],
                    description=e["description"],
                    reported_by=request.user,
                )
                for e in errors
            ])

            job.status = JobStatus.REWORK
            job.rework_round += 1
            job.total_rework_rounds = max(job.total_rework_rounds + 1, job.rework_round)
            job.rework_scope = rework_scope
            job.round_credited_objects = 0
            job.last_counted_objects = max(job.last_counted_objects, job.object_count)
            newly_escalated = False
            if job.rework_round > self.project.max_rework_rounds and not job.is_escalated:
                job.is_escalated = True
                newly_escalated = True
            job.save(
                update_fields=[
                    "status",
                    "rework_round",
                    "total_rework_rounds",
                    "rework_scope",
                    "round_credited_objects",
                    "last_counted_objects",
                    "is_escalated",
                    "updated_at",
                ]
            )
            schedule_assignee_push([job.pk])
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="qc2.reject",
                target=job,
                job=job,
                before={"status": JobStatus.PENDING_QC2},
                after={
                    "status": JobStatus.REWORK,
                    "rework_round": job.rework_round,
                    "rework_scope": rework_scope,
                    "errors": len(errors),
                    "escalated": job.is_escalated,
                },
                note=comment,
            )
            with timezone.override(app_timezone()):
                notify_rework(
                    self.project,
                    job,
                    error_count=len(errors),
                    stage_label="QC2",
                    reason=comment,
                    actor=request.user,
                    include_qc1=True,
                )
            if newly_escalated:
                notify_escalated(self.project, job, actor=request.user)
        return Response(self.get_serializer(self._base_queryset().get(pk=sample.pk)).data)

    @action(detail=True, methods=["post"])
    def assign(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        """PM phân (lại) auditor cho một lượt QC2 đang chờ."""
        with transaction.atomic():
            sample, job = self._lock_sample_and_job(pk)
            if sample.audit.status != Audit.Status.IN_PROGRESS:
                raise ValidationError("Task đã bàn giao, đợt QC2 đã chốt.")
            if sample.result != AuditSample.Result.PENDING:
                raise ValidationError("Mẫu đã có kết quả.")
            ensure_editable(job)
            ensure_not_escalated(job)
            data = validated_dict(AssignAuditorSerializer(data=request.data))
            auditor = User.objects.filter(pk=data["auditor"], is_active=True).first()
            if not auditor or Role.QC2 not in auditor.get_project_roles(self.project):
                raise ValidationError("Auditor phải có quyền QC2 trong dự án.")
            if auditor.id in four_eyes_conflicts(job):
                raise ValidationError("Luật bốn mắt: người này đã annotate hoặc QC1 job.")
            sample.auditor = auditor
            sample.save(update_fields=["auditor"])
            schedule_assignee_push([sample.job_id])
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="qc2.assign_auditor",
                target=job,
                job=job,
                after={"auditor": auditor.username},
            )
            with timezone.override(app_timezone()):
                notify_assigned(self.project, job, auditor, role_label="QC2", actor=request.user)
        return Response(self.get_serializer(self._base_queryset().get(pk=sample.pk)).data)


SAMPLING_FIELDS = ("sampling_rate",)


class AuditStrategyView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/audit-strategy/ — quy tắc QC2 đang áp dụng (chỉ PM).

    QC2 kiểm MỌI job qua QC1, mỗi job ngẫu nhiên sampling_rate % số frame (làm tròn lên, ít nhất 1).
    PM sửa tỉ lệ qua /settings/. Kèm lịch sử thay đổi và thống kê lượt QC2.
    """

    required_capabilities = {"*": Cap.MANAGE_AUDITS}

    def get(self, request: Any, project_id: Any) -> Response:
        project = self.project
        history = []
        logs = ActivityLog.objects.filter(project=project, action="project.settings").select_related("actor")
        for log in logs.order_by("-created_at")[:50]:
            after = {k: v for k, v in (log.after or {}).items() if k in SAMPLING_FIELDS}
            if after:
                before = {k: (log.before or {}).get(k) for k in after}
                history.append({
                    "at": format_rfc3339_utc(log.created_at),
                    "actor": UserBriefSerializer(log.actor).data if log.actor else None,
                    "before": before,
                    "after": after,
                })
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
    "done": [JobStatus.QC1_PASSED, JobStatus.REWORK, JobStatus.PENDING_QC2, JobStatus.APPROVED, JobStatus.DELIVERED],
}
QC1_REVIEWABLE_STATUSES = {JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING}


def _qc1_team_pool_q(project: Any, user: Any) -> Q:
    """Chặn chặt theo team cho pool QC1: chỉ thấy/nhận job thuộc batch của team mình hoặc batch chung."""
    t_ids = user_team_ids(project, user)
    if t_ids:
        return Q(batch__team_id__in=t_ids) | Q(batch__team__isnull=True)
    return Q(batch__team__isnull=True)


def _check_qc1_access(job: Job, actor: Any) -> None:
    """Luật bốn mắt đa giai đoạn (kể cả lịch sử) + kiểm tra quyền sở hữu QC1, phạm vi team, khoá và escalation."""
    annotator_ids, _, qc2_ids = get_stage_history(job)
    if actor.id in annotator_ids:
        raise PermissionDenied("Luật bốn mắt: bạn không thể QC1 job đã từng do chính mình annotate.")
    if actor.id in qc2_ids:
        raise PermissionDenied("Luật bốn mắt: bạn không thể QC1 job đã từng do chính mình audit QC2.")
    if job.qc1_reviewer_id and job.qc1_reviewer_id != actor.id:
        raise PermissionDenied("Job này đã được giao cho người QC1 khác.")
    if not job.qc1_reviewer_id and job.batch.team_id:
        t_ids = user_team_ids(job.project, actor)
        if job.batch.team_id not in t_ids:
            raise PermissionDenied("Job thuộc batch của team khác — bạn không thể nhận kiểm tra.")
    ensure_editable(job)
    ensure_not_escalated(job)


@transaction.atomic
def start_qc1(job_id: int, *, project: Any, actor: Any, note: str = "") -> Job:
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
def qc1_pass(job_id: int, *, project: Any, actor: Any, comment: str = "") -> Job:
    """QC1 duyệt đạt (Hybrid A2 anti-deadlock):
    - Nếu task chưa được PM xác nhận QC2 (qc2_confirmed_at is None): chuyển QC1_PASSED và báo PM khi đủ 100%.
    - Nếu task đã được PM xác nhận QC2 (rework hậu QC2): chuyển thẳng PENDING_QC2 và tự tạo lượt QC2.
    """
    job = lock_job(project, job_id)
    _check_qc1_access(job, actor)
    if job.status not in QC1_REVIEWABLE_STATUSES:
        raise ValidationError(
            f"Chỉ có thể duyệt QC1 khi job đang Chờ QC1 hoặc Đang QC1 (hiện tại: {job.get_status_display()})."
        )

    prev_status = job.status
    is_post_qc2_rework = job.batch.qc2_confirmed_at is not None
    target_status = JobStatus.PENDING_QC2 if is_post_qc2_rework else JobStatus.QC1_PASSED

    job.status = target_status
    update_fields = ["status", "updated_at"]
    if not job.first_qc1_result and job.total_rework_rounds == 0 and job.rework_round == 0:
        job.first_qc1_result = FirstQc1Result.PASS
        update_fields.append("first_qc1_result")
    if not job.qc1_reviewer_id:
        job.qc1_reviewer = actor
        update_fields.append("qc1_reviewer")
    job.save(update_fields=update_fields)

    UserNotification.objects.filter(
        project=project,
        job=job,
        category=UserNotification.Category.REVIEW_NEEDED,
        is_pinned_pending=True,
    ).update(is_pinned_pending=False)

    ActivityLog.record(
        project=project,
        actor=actor,
        action="qc1.pass",
        target=job,
        job=job,
        before={"status": prev_status},
        after={
            "status": target_status,
            "rework_round": job.rework_round,
            "deadline": format_rfc3339_utc(job.deadline),
        },
        note=comment,
    )

    if is_post_qc2_rework:
        ensure_qc2_sample(job)
    schedule_assignee_push([job.pk])
    if job.annotator and job.annotator.notify_qc_pass:
        is_first_pass = job.rework_round == 0 and job.total_rework_rounds == 0
        suffix = "chuyển thẳng sang QC2." if is_post_qc2_rework else "chờ PM xác nhận chuyển QC2."
        body = (
            f"Job đạt QC1 ngay lần kiểm đầu — {suffix}"
            if is_first_pass
            else f"Job đạt QC1 sau vòng sửa {job.rework_round} — {suffix}"
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
    if not is_post_qc2_rework:
        notify_batch_ready_for_qc2(project, job.batch, actor=actor)
    return job


@transaction.atomic
def qc1_reject(
    job_id: int,
    *,
    project: Any,
    actor: Any,
    errors: list[dict[str, Any]],
    comment: str = "",
    rework_scope: str = ReworkScope.PARTIAL,
) -> Job:
    """QC1 trả về Rework: ghi ReviewError (stage=QC1), tăng rework_round, vượt ngưỡng -> is_escalated + báo PM."""
    job = lock_job(project, job_id)
    _check_qc1_access(job, actor)
    if job.status not in QC1_REVIEWABLE_STATUSES:
        raise ValidationError(
            f"Chỉ có thể trả rework QC1 khi job đang Chờ QC1 hoặc Đang QC1 (hiện tại: {job.get_status_display()})."
        )

    prev_status = job.status
    round_at_review = max(job.total_rework_rounds, job.rework_round)
    was_first_qc1 = not job.first_qc1_result and job.total_rework_rounds == 0 and job.rework_round == 0

    ReviewError.objects.bulk_create([
        ReviewError(
            job=job,
            stage=ReviewStage.QC1,
            rework_round=round_at_review,
            audit_sample=None,
            category=e["category"],
            severity=e.get("severity") or e["category"].severity,
            verdict=e.get("verdict") or ErrorVerdict.FAIL,
            frame_number=e.get("frame_number"),
            cvat_object_id=e.get("cvat_object_id"),
            is_missing_object=bool(e.get("is_missing_object", False)),
            location=e["location"],
            description=e["description"],
            reported_by=actor,
        )
        for e in errors
    ])

    job.status = JobStatus.REWORK
    job.rework_round += 1
    job.total_rework_rounds = max(job.total_rework_rounds + 1, job.rework_round)
    job.rework_scope = rework_scope
    job.round_credited_objects = 0
    job.last_counted_objects = max(job.last_counted_objects, job.object_count)
    newly_escalated = False
    if job.rework_round > project.max_rework_rounds and not job.is_escalated:
        job.is_escalated = True
        newly_escalated = True
    update_fields = [
        "status",
        "rework_round",
        "total_rework_rounds",
        "rework_scope",
        "round_credited_objects",
        "last_counted_objects",
        "is_escalated",
        "updated_at",
    ]
    if was_first_qc1:
        job.first_qc1_result = FirstQc1Result.REJECT
        update_fields.append("first_qc1_result")
    if not job.qc1_reviewer_id:
        job.qc1_reviewer = actor
        update_fields.append("qc1_reviewer")
    job.save(update_fields=update_fields)

    UserNotification.objects.filter(
        project=project,
        job=job,
        category=UserNotification.Category.REVIEW_NEEDED,
        is_pinned_pending=True,
    ).update(is_pinned_pending=False)
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
            "deadline": format_rfc3339_utc(job.deadline),
        },
        note=comment,
    )
    with timezone.override(app_timezone()):
        notify_rework(project, job, error_count=len(errors), stage_label="QC1", reason=comment, actor=actor)
    if newly_escalated:
        notify_escalated(project, job, actor=actor)
    return job


class Qc1JobViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Không gian làm việc Level 1 QC:
    xem hàng chờ QC1 (chặn chặt theo team ở pool), nhận kiểm tra, Pass hoặc Reject trả về Rework.
    """

    pagination_class = StandardPagination
    lookup_value_regex = r"\d+"
    required_capabilities = {"*": Cap.PERFORM_QC1}

    def get_serializer_class(self) -> Any:
        return JobDetailSerializer if self.action == "retrieve" else JobSerializer

    def _base_queryset(self) -> Any:
        return (
            Job.objects.filter(project=self.project)
            .select_related("batch", "dataset", "batch__team", "annotator", "qc1_reviewer", "project")
            .annotate(
                _active_rework_error_count=Count(
                    "review_errors",
                    filter=Q(
                        status__in=[JobStatus.REWORK, JobStatus.ANNOTATING],
                        review_errors__is_voided=False,
                        review_errors__rework_round=Greatest(F("total_rework_rounds"), F("rework_round")) - 1,
                    )
                    & (Q(rework_round__gt=0) | Q(total_rework_rounds__gt=0)),
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

    def _exclude_four_eyes_conflicts(self, queryset: Any, user: Any) -> Any:
        hist_ann_job_ids = (
            ActivityLog.objects.filter(project=self.project, actor=user, job_id__isnull=False)
            .filter(
                Q(action__in=ANNOTATOR_EVENTS)
                | Q(action__in=("job.status", "job.assign"), after__event__in=ANNOTATOR_EVENTS)
                | Q(action="job.status", after__status__in=[JobStatus.ANNOTATING, JobStatus.PENDING_QC1])
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

    def get_queryset(self) -> Any:
        user = self.request.user
        queryset = self._exclude_four_eyes_conflicts(self._base_queryset(), user)
        pool_filter = Q(
            qc1_reviewer__isnull=True,
            status=JobStatus.PENDING_QC1,
            is_locked=False,
            batch__status=DataStatus.ACTIVE,
            dataset__status=DataStatus.ACTIVE,
        ) & _qc1_team_pool_q(self.project, user)
        if self.project.escalation_policy == EscalationPolicy.BLOCK:
            pool_filter &= Q(is_escalated=False)

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

        now = timezone.now()
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
            queryset = queryset.filter(deadline__lt=now, status__in=OPEN_STATUSES)
        if p.get("due_soon") == "1":
            queryset = queryset.filter(
                deadline__gte=now, deadline__lte=now + timedelta(hours=24), status__in=OPEN_STATUSES
            )
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
            queryset = order_by_db06_priority(queryset, now=now)
        return queryset

    def _parse_job_pk(self, pk: Any) -> int:
        try:
            return parse_int_param(pk, "pk")
        except ValidationError as exc:
            raise NotFound("Không tìm thấy job trong organization.") from exc

    def _detail(self, job: Job) -> Response:
        fresh = self._base_queryset().get(pk=job.pk)
        return Response(JobDetailSerializer(fresh, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def start(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        """Bắt đầu kiểm tra QC1 (PENDING_QC1 -> QC1_REVIEWING; tự nhận nếu job chưa có qc1_reviewer)."""
        job_id = self._parse_job_pk(pk)
        data = validated_dict(Qc1StartSerializer(data=request.data))
        updated = start_qc1(
            job_id,
            project=self.project,
            actor=request.user,
            note=data["note"],
        )
        return self._detail(updated)

    @action(detail=True, methods=["post"], url_path="pass")
    def pass_(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        """Duyệt đạt QC1 (Hybrid A2: QC1_PASSED trước confirm-qc2, PENDING_QC2 + auto sample sau confirm-qc2)."""
        job_id = self._parse_job_pk(pk)
        data = validated_dict(PassSerializer(data=request.data))
        updated = qc1_pass(
            job_id,
            project=self.project,
            actor=request.user,
            comment=data["comment"],
        )
        return self._detail(updated)

    @action(detail=True, methods=["post"])
    def reject(self, request: Any, project_id: Any, pk: Any = None) -> Response:
        """Trả về Rework từ QC1: bắt buộc ghi ít nhất 1 lỗi (ReviewError stage=qc1)."""
        job_id = self._parse_job_pk(pk)
        data = validated_dict(Qc1RejectSerializer(data=request.data, context=self.get_serializer_context()))
        updated = qc1_reject(
            job_id,
            project=self.project,
            actor=request.user,
            errors=data["errors"],
            comment=data["comment"],
            rework_scope=data["rework_scope"],
        )
        return self._detail(updated)
