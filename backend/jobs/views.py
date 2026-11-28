from datetime import timedelta
from typing import Any

from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, When
from django.db.models.functions import Greatest
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.datetime_utils import (
    PG_INT32_MAX,
    format_rfc3339_utc,
    parse_int_param,
    parse_query_date_range,
)
from accounts.models import Role, RoleAssignment, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from accounts.validation import validated_dict
from cvat_integration.assignee import schedule_assignee_push
from projects.models import ActivityLog, Batch, DataStatus, EscalationPolicy, Project, UserNotification
from projects.notifications import notify_assigned, notify_review_needed, project_users_with_roles
from projects.views import StandardPagination
from quality.models import Audit, AuditSample, ReviewError
from teams.models import TeamMember

from .models import (
    ACTIVE_ANNOTATOR_STATUSES,
    OPEN_STATUSES,
    STAGE_STATUSES,
    AnnotatorRequest,
    DailyOutputRecord,
    Job,
    JobStatus,
    ReworkScope,
    record_daily_output,
)
from .serializers import (
    AnnotatorRequestCreateSerializer,
    AnnotatorRequestResolveSerializer,
    AnnotatorRequestSerializer,
    AnnotatorStartSerializer,
    AnnotatorSubmitSerializer,
    AssignSerializer,
    BulkDeadlineSerializer,
    BulkMoveBatchSerializer,
    BulkSerializer,
    DeadlineSerializer,
    JobDetailSerializer,
    JobNoteSerializer,
    JobSerializer,
    JobWithErrorsSerializer,
    ResolveEscalationSerializer,
)

ASSIGN_LOCKED_STATUSES = {JobStatus.QC1_PASSED, JobStatus.PENDING_QC2, JobStatus.APPROVED, JobStatus.DELIVERED}


def _iso(value):
    return format_rfc3339_utc(value)


def _parse_pk(raw, not_found_message="Không tìm thấy bản ghi trong organization."):
    try:
        pk = int(raw)
    except (TypeError, ValueError) as exc:
        raise NotFound(not_found_message) from exc
    if pk < 1 or pk > PG_INT32_MAX:
        raise NotFound(not_found_message)
    return pk


def _parse_int_list(raw: str, field_name: str) -> list[int]:
    return [parse_int_param(part, field_name) for part in raw.split(",")]


def _base_job_queryset(project):
    return (
        Job.objects.filter(project=project)
        .select_related("batch", "dataset", "annotator", "qc1_reviewer", "project")
        .annotate(
            _active_rework_error_count=Count(
                "review_errors",
                filter=(
                    Q(
                        status__in=[JobStatus.REWORK, JobStatus.ANNOTATING],
                        review_errors__rework_round=Greatest(F("total_rework_rounds"), F("rework_round")) - 1,
                        review_errors__is_voided=False,
                    )
                    & (Q(rework_round__gt=0) | Q(total_rework_rounds__gt=0))
                ),
                distinct=True,
            )
        )
        .prefetch_related(
            Prefetch(
                "audit_samples",
                queryset=AuditSample.objects.filter(audit__status=Audit.Status.IN_PROGRESS)
                .select_related("auditor")
                .order_by("id"),
                to_attr="open_samples",
            )
        )
    )


def _count_unique_error_targets(errors) -> tuple[int, int]:
    """Đếm mục tiêu lỗi duy nhất, tách biệt (existing_cuboid_targets, missing_object_targets)."""
    existing: set[tuple[object, ...]] = set()
    missing: set[tuple[object, ...]] = set()
    for err in errors:
        if err.is_missing_object:
            if err.frame_number is not None:
                missing.add(("missing", err.frame_number, err.category_id))
            else:
                missing.add(("missing_err", err.id))
        elif err.frame_number is not None and err.cvat_object_id is not None:
            existing.add(("obj", err.frame_number, err.cvat_object_id))
        elif err.location and err.location.strip():
            existing.add(("loc", err.location.strip().lower()))
        else:
            existing.add(("err", err.id))
    return len(existing), len(missing)


def _qc1_review_targets(project, job) -> list[User]:
    """Xác định người nhận thông báo cần kiểm QC1: ưu tiên người được giao, sau đó QC1 cùng team, cuối cùng toàn org."""
    if job.qc1_reviewer_id:
        return [job.qc1_reviewer]
    if job.batch.team_id:
        team_qc1_ids = list(
            TeamMember.objects.filter(
                team_id=job.batch.team_id,
                user__is_active=True,
                user__role_assignments__project=project,
                user__role_assignments__role=Role.QC1,
            )
            .values_list("user_id", flat=True)
            .distinct()
        )
        if team_qc1_ids:
            return list(User.objects.filter(pk__in=team_qc1_ids, is_active=True))
    return project_users_with_roles(project, Role.QC1)


def ensure_editable(job):
    """Quy tắc chung trước khi sửa hoặc chuyển trạng thái một Job."""
    if job.is_locked:
        raise ValidationError(f"Job {job} đang bị khoá.")
    if job.batch.status != DataStatus.ACTIVE:
        raise ValidationError(f"Task của job {job} đã khoá hoặc đã bàn giao.")
    if job.dataset.status != DataStatus.ACTIVE:
        raise ValidationError(f"Project của job {job} đã khoá.")
    if job.status == JobStatus.DELIVERED:
        raise ValidationError(f"Job {job} đã bàn giao.")


def ensure_not_escalated(job):
    """Chỉ chặn thao tác khi job bị Escalated và organization áp dụng chế độ BLOCK."""
    if job.is_escalated and job.project.escalation_policy == EscalationPolicy.BLOCK:
        raise ValidationError("Job đang ở trạng thái Escalated, chờ PM xử lý.")


def lock_job(project, job_id):
    """Khoá dòng Job bằng select_for_update(of=("self",)) để an toàn trên PostgreSQL."""
    job = (
        Job.objects.select_for_update(of=("self",))
        .select_related("batch", "dataset", "batch__team", "project", "annotator", "qc1_reviewer")
        .filter(pk=job_id, project=project)
        .first()
    )
    if job is None:
        raise NotFound("Không tìm thấy job trong organization.")
    return job


def lock_job_with_batch(project, job_id):
    """Khoá theo thứ tự chuẩn Batch → Job để tránh AB-BA deadlock với thao tác cấp Task."""
    batch_id = Job.objects.filter(pk=job_id, project=project).values_list("batch_id", flat=True).first()
    if batch_id is None:
        raise NotFound("Không tìm thấy job trong organization.")
    Batch.objects.select_for_update(of=("self",)).filter(pk=batch_id).first()
    job = lock_job(project, job_id)
    if job.batch_id != batch_id:
        raise ValidationError("Job vừa được chuyển task, vui lòng thử lại.")
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
    job.started_at = timezone.now()
    job.save(update_fields=["status", "started_at", "updated_at"])
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
    schedule_assignee_push([job.pk])
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
            f"Chỉ có thể nộp bài khi job ở trạng thái Đang annotate (hiện tại: {job.get_status_display()})."
        )

    prev_status = job.status
    prev_objects = job.object_count
    job.status = JobStatus.PENDING_QC1
    job.submitted_at = timezone.now()
    update_fields = ["status", "submitted_at", "last_counted_objects", "round_credited_objects", "updated_at"]
    manual_object_count_applied = False
    if object_count is not None:
        if (
            isinstance(object_count, bool)
            or not isinstance(object_count, int)
            or object_count < 0
            or object_count > PG_INT32_MAX
        ):
            raise ValidationError({"object_count": f"Số object phải là số nguyên từ 0 đến {PG_INT32_MAX}."})
        # Job liên kết CVAT dùng số đếm đồng bộ từ CVAT làm nguồn chuẩn (tránh ghi đè tay khi nộp).
        if job.cvat_job_id is None:
            job.object_count = object_count
            update_fields.append("object_count")
            manual_object_count_applied = True

    # Tính sản lượng cuboid ghi bổ sung vào DailyOutputRecord:
    # - Không cộng đúp phần đã ghi qua đồng bộ CVAT trước QC.
    # - Vòng partial rework: chỉ tính trên các lỗi chưa bị hủy của ĐÚNG vòng hiện hành
    #   (max(total_rework_rounds, rework_round) - 1).
    # - Vòng full rework: tính theo khối lượng làm lại trừ phần đã ghi trong vòng hiện tại.
    is_rework = job.total_rework_rounds > 0 or job.rework_round > 0
    count_delta = max(0, job.object_count - job.last_counted_objects)
    if not is_rework:
        credited = count_delta
    elif job.rework_scope == ReworkScope.FULL:
        credited = max(0, job.object_count - job.round_credited_objects)
    else:
        active_round = max(job.total_rework_rounds, job.rework_round) - 1
        if active_round >= 0:
            active_errs = job.review_errors.filter(
                rework_round=active_round,
                is_voided=False,
            )
            existing_targets, missing_targets = _count_unique_error_targets(active_errs)
        else:
            existing_targets, missing_targets = 0, 0
        total_added_in_round = job.round_credited_objects + count_delta
        target_round_work = existing_targets + max(missing_targets, total_added_in_round)
        credited = max(0, target_round_work - job.round_credited_objects)

    job.last_counted_objects = max(job.last_counted_objects, job.object_count)
    job.round_credited_objects += credited
    job.save(update_fields=update_fields)

    if credited > 0:
        record_daily_output(
            job=job,
            user=actor,
            object_count=credited,
            is_rework=is_rework,
            rework_round=max(job.total_rework_rounds, job.rework_round),
            source=DailyOutputRecord.Source.SUBMIT,
            at=job.submitted_at,
        )

    # Gỡ ghim thông báo rework/deadline của job sau khi đã nộp xử lý.
    UserNotification.objects.filter(
        recipient=actor,
        project=project,
        job=job,
        is_pinned_pending=True,
    ).update(is_pinned_pending=False)

    before: dict[str, object] = {"status": prev_status}
    after: dict[str, object] = {
        "status": JobStatus.PENDING_QC1,
        "event": "annotator.resubmit" if is_rework else "annotator.submit",
        "rework_round": job.rework_round,
        "object_count": job.object_count,
        "credited_objects": credited,
        "deadline": _iso(job.deadline),
    }
    if manual_object_count_applied and object_count != prev_objects:
        before["object_count"] = prev_objects

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
    review_targets = _qc1_review_targets(project, job)
    if review_targets:
        notify_review_needed(
            project,
            review_targets,
            title=f"{job.name} chờ kiểm tra QC1",
            body=f"{actor.get_full_name() or actor.username} vừa nộp bài (vòng {job.rework_round}).",
            action_url=f"/projects/{project.id}/qc1/work",
            job=job,
            actor=actor,
        )
    schedule_assignee_push([job.pk])
    return job


def assign_job(job, data, actor, project, *, push_cvat=True):
    ensure_editable(job)
    if job.status in ASSIGN_LOCKED_STATUSES:
        raise ValidationError(
            f"Không thể đổi annotator hoặc người QC1 khi job ở trạng thái {job.get_status_display()}."
        )

    lock_user_ids = sorted({
        user.pk
        for field in ("annotator", "qc1_reviewer")
        if (user := data.get(field)) is not None
    })
    locked_users: dict[int, User] = {}
    if lock_user_ids:
        locked_users = {
            u.pk: u
            for u in User.objects.select_for_update().filter(pk__in=lock_user_ids).order_by("id")
        }

    resolved_data = dict(data)
    for field, role, label in (
        ("annotator", Role.ANNOTATOR, "Annotator"),
        ("qc1_reviewer", Role.QC1, "Người QC1"),
    ):
        if field in resolved_data and resolved_data[field] is not None:
            locked_user = locked_users.get(resolved_data[field].pk)
            if not locked_user or not locked_user.is_active or role not in locked_user.get_project_roles(project):
                raise ValidationError(f"{label} phải là người có vai trò {Role(role).label} trong organization.")
            resolved_data[field] = locked_user

    from quality.qc2 import get_stage_history

    annotator_ids, qc1_ids, qc2_ids = get_stage_history(job)
    new_annotator = resolved_data.get("annotator", job.annotator)
    new_qc1 = resolved_data.get("qc1_reviewer", job.qc1_reviewer)
    new_ann_id = new_annotator.pk if new_annotator else None
    new_qc1_id = new_qc1.pk if new_qc1 else None

    if new_ann_id and new_ann_id == new_qc1_id:
        raise ValidationError("Luật bốn mắt: người QC1 không được là annotator của chính job đó.")
    if "annotator" in resolved_data and new_ann_id and new_ann_id in (qc1_ids | qc2_ids):
        raise ValidationError("Luật bốn mắt: người này đã tham gia QC1 hoặc QC2 job này.")
    if "qc1_reviewer" in resolved_data and new_qc1_id and new_qc1_id in (annotator_ids | qc2_ids):
        raise ValidationError("Luật bốn mắt: người này đã annotate hoặc QC2 job này.")

    before: dict[str, int | None] = {}
    after: dict[str, int | None] = {}
    for field in ("annotator", "qc1_reviewer"):
        if field in resolved_data:
            before[field] = getattr(job, f"{field}_id")
            setattr(job, field, resolved_data[field])
            after[field] = resolved_data[field].pk if resolved_data[field] else None
    if after:
        job.save(update_fields=[*after.keys(), "updated_at"])
    ActivityLog.record(
        project=project,
        actor=actor,
        action="job.assign",
        target=job,
        job=job,
        before=before,
        after=after,
        note=resolved_data.get("note", ""),
    )
    if "annotator" in after and after["annotator"] and after["annotator"] != before.get("annotator"):
        notify_assigned(project, job, job.annotator, role_label="Annotator", actor=actor)
    if "qc1_reviewer" in after and after["qc1_reviewer"] and after["qc1_reviewer"] != before.get("qc1_reviewer"):
        notify_assigned(project, job, job.qc1_reviewer, role_label="QC1", actor=actor)
    if push_cvat:
        schedule_assignee_push([job.pk])


def set_job_deadline(job, deadline, note, actor, project):
    ensure_editable(job)
    clean_note = (note or "").strip()
    if job.deadline is not None and deadline != job.deadline and not clean_note:
        raise ValidationError({"note": "Vui lòng nhập lý do khi thay đổi deadline đã đặt."})
    before = job.deadline
    job.deadline = deadline
    job.save(update_fields=["deadline", "updated_at"])
    ActivityLog.record(
        project=project,
        actor=actor,
        action="job.deadline",
        target=job,
        job=job,
        before={"deadline": _iso(before)},
        after={"deadline": _iso(deadline)},
        note=clean_note,
    )


class JobViewSet(ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Danh sách & chi tiết Job cấp organization (PM)."""

    pagination_class = StandardPagination
    required_capabilities = {"list": Cap.VIEW_JOBS, "retrieve": Cap.VIEW_JOBS, "*": Cap.MANAGE_JOBS}

    def get_serializer_class(self) -> Any:
        return JobDetailSerializer if self.action == "retrieve" else JobSerializer

    def get_queryset(self) -> Any:
        queryset = _base_job_queryset(self.project)
        p = self.request.query_params
        now = timezone.now()
        if p.get("status"):
            queryset = queryset.filter(status__in=p["status"].split(","))
        if p.get("stage") in STAGE_STATUSES:
            queryset = queryset.filter(status__in=STAGE_STATUSES[p["stage"]])
        if p.get("batch"):
            queryset = queryset.filter(batch_id__in=_parse_int_list(p["batch"], "batch"))
        if p.get("dataset"):
            queryset = queryset.filter(dataset_id__in=_parse_int_list(p["dataset"], "dataset"))
        if p.get("assignee"):
            assignee_id = parse_int_param(p["assignee"], "assignee")
            queryset = queryset.filter(Q(annotator_id=assignee_id) | Q(qc1_reviewer_id=assignee_id))
        if p.get("annotator"):
            queryset = queryset.filter(annotator_id=parse_int_param(p["annotator"], "annotator"))
        if p.get("qc1_reviewer"):
            queryset = queryset.filter(qc1_reviewer_id=parse_int_param(p["qc1_reviewer"], "qc1_reviewer"))
        if p.get("min_rework"):
            queryset = queryset.filter(rework_round__gte=parse_int_param(p["min_rework"], "min_rework", min_value=0))
        if p.get("max_rework"):
            queryset = queryset.filter(rework_round__lte=parse_int_param(p["max_rework"], "max_rework", min_value=0))
        deadline_from, deadline_to = parse_query_date_range(
            p,
            from_key="deadline_from",
            to_key="deadline_to",
            allow_datetime=True,
        )
        if deadline_from is not None:
            queryset = queryset.filter(deadline__gte=deadline_from)
        if deadline_to is not None:
            queryset = queryset.filter(deadline__lte=deadline_to)
        if p.get("escalated") == "1":
            queryset = queryset.filter(is_escalated=True)
        if p.get("locked") == "1":
            queryset = queryset.filter(is_locked=True)
        if p.get("unassigned") == "1":
            queryset = queryset.filter(annotator__isnull=True)
        if p.get("overdue") == "1":
            queryset = queryset.filter(deadline__lt=now, status__in=OPEN_STATUSES)
        if p.get("due_soon") == "1":
            queryset = queryset.filter(
                deadline__gte=now,
                deadline__lte=now + timedelta(hours=24),
                status__in=OPEN_STATUSES,
            )
        if p.get("search"):
            term = p["search"].strip()
            cond = Q(name__icontains=term) | Q(batch__name__icontains=term)
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

    def _detail(self, job):
        fresh = _base_job_queryset(self.project).get(pk=job.pk)
        return Response(JobDetailSerializer(fresh, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def assign(self, request, project_id, pk=None):
        data = validated_dict(AssignSerializer(data=request.data, context=self.get_serializer_context()))
        with transaction.atomic():
            job = lock_job(self.project, _parse_pk(pk, "Không tìm thấy job trong organization."))
            assign_job(job, data, request.user, self.project)
        return self._detail(job)

    @action(detail=True, methods=["post"])
    def deadline(self, request, project_id, pk=None):
        data = validated_dict(DeadlineSerializer(data=request.data))
        with transaction.atomic():
            job = lock_job(self.project, _parse_pk(pk, "Không tìm thấy job trong organization."))
            set_job_deadline(job, data["deadline"], data["note"], request.user, self.project)
        return self._detail(job)

    def _toggle_lock(self, request, pk, locked: bool):
        note_data = validated_dict(JobNoteSerializer(data=request.data))
        with transaction.atomic():
            job = lock_job(self.project, _parse_pk(pk, "Không tìm thấy job trong organization."))
            if job.status == JobStatus.DELIVERED:
                raise ValidationError("Job đã bàn giao, không thể khoá hoặc mở khoá.")
            if job.is_locked == locked:
                raise ValidationError("Job đã ở trạng thái này.")
            job.is_locked = locked
            job.save(update_fields=["is_locked", "updated_at"])
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="job.lock" if locked else "job.unlock",
                target=job,
                job=job,
                note=note_data["note"],
            )
        return self._detail(job)

    @action(detail=True, methods=["post"])
    def lock(self, request, project_id, pk=None):
        return self._toggle_lock(request, pk, True)

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        return self._toggle_lock(request, pk, False)

    @action(detail=True, methods=["post"], url_path="resolve-escalation")
    def resolve_escalation(self, request, project_id, pk=None):
        """PM xử lý job Escalated: giao cho annotator khác (tuỳ chọn), gỡ cờ escalated và unpin thông báo."""
        res_data = validated_dict(ResolveEscalationSerializer(data=request.data))
        with transaction.atomic():
            job = lock_job(self.project, _parse_pk(pk, "Không tìm thấy job trong organization."))
            ensure_editable(job)
            if not job.is_escalated:
                raise ValidationError("Job không ở trạng thái Escalated.")
            if job.status in ASSIGN_LOCKED_STATUSES:
                raise ValidationError(
                    f"Không thể xử lý escalation khi job ở trạng thái {job.get_status_display()}."
                )
            if "annotator" in res_data:
                assign_data = validated_dict(
                    AssignSerializer(
                        data={"annotator": res_data["annotator"]},
                        context=self.get_serializer_context(),
                    )
                )
                assign_job(job, assign_data, request.user, self.project)
            before_round = job.rework_round
            job.total_rework_rounds = max(job.total_rework_rounds, before_round)
            job.is_escalated = False
            job.rework_round = 0
            job.save(update_fields=["is_escalated", "rework_round", "total_rework_rounds", "updated_at"])
            UserNotification.objects.filter(
                project=self.project,
                job=job,
                category=UserNotification.Category.ESCALATED,
                is_pinned_pending=True,
            ).update(is_pinned_pending=False, is_read=True)
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="job.resolve_escalation",
                target=job,
                job=job,
                before={"rework_round": before_round},
                after={"rework_round": 0, "total_rework_rounds": job.total_rework_rounds},
                note=res_data["note"],
            )
        return self._detail(job)

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request, project_id):
        ids_data = validated_dict(BulkSerializer(data=request.data))
        assign_data = validated_dict(AssignSerializer(data=request.data, context=self.get_serializer_context()))
        changed_ids: list[int] = []
        with transaction.atomic():  # một job lỗi → không job nào bị đổi
            jobs = list(
                Job.objects.select_for_update(of=("self",))
                .select_related("batch", "dataset", "project", "annotator", "qc1_reviewer")
                .filter(project=self.project, pk__in=ids_data["ids"])
                .order_by("id")
            )
            for job in jobs:
                assign_job(job, assign_data, request.user, self.project, push_cvat=False)
                changed_ids.append(job.pk)
            if changed_ids:
                schedule_assignee_push(changed_ids)
        return Response({"updated": len(jobs)})

    @action(detail=False, methods=["post"], url_path="bulk-deadline")
    def bulk_deadline(self, request, project_id):
        data = validated_dict(BulkDeadlineSerializer(data=request.data))
        with transaction.atomic():
            jobs = list(
                Job.objects.select_for_update(of=("self",))
                .select_related("batch", "dataset", "project")
                .filter(project=self.project, pk__in=data["ids"])
                .order_by("id")
            )
            for job in jobs:
                set_job_deadline(job, data["deadline"], data["note"], request.user, self.project)
        return Response({"updated": len(jobs)})

    @action(detail=False, methods=["post"], url_path="bulk-move-batch")
    def bulk_move_batch(self, request, project_id):
        """Chuyển hàng loạt job nội bộ sang một task đích trong cùng organization (chặn job liên kết CVAT)."""
        move_data = validated_dict(BulkMoveBatchSerializer(data=request.data, context=self.get_serializer_context()))
        target_batch_id = move_data["batch"].pk
        note = move_data["note"]
        with transaction.atomic():
            target_batch = (
                Batch.objects.select_for_update(of=("self",))
                .select_related("dataset")
                .filter(pk=target_batch_id, project=self.project)
                .first()
            )
            if target_batch is None:
                raise ValidationError({"batch": "Task đích không thuộc organization này."})
            if target_batch.status != DataStatus.ACTIVE or target_batch.dataset.status != DataStatus.ACTIVE:
                raise ValidationError("Task hoặc Project đích đã khoá hoặc đã bàn giao.")

            jobs = list(
                Job.objects.select_for_update(of=("self",))
                .select_related("batch", "dataset", "project")
                .filter(project=self.project, pk__in=move_data["ids"])
                .order_by("id")
            )
            if not jobs:
                raise ValidationError("Không tìm thấy job phù hợp để chuyển task.")

            for job in jobs:
                ensure_editable(job)
                if job.cvat_job_id is not None:
                    raise ValidationError(
                        f"Job {job} đã liên kết CVAT (job #{job.cvat_job_id}) — không thể chuyển task trên VanoHub."
                    )
                if job.audit_samples.filter(audit__status=Audit.Status.IN_PROGRESS).exists():
                    raise ValidationError(f"Job {job} đang thuộc một đợt audit QC2 chưa chốt.")
                if job.batch_id == target_batch.id and job.dataset_id == target_batch.dataset_id:
                    continue
                before_name = job.batch.name
                before_dataset_id = job.dataset_id
                job.batch = target_batch
                job.dataset = target_batch.dataset
                job.save(update_fields=["batch", "dataset", "updated_at"])
                ActivityLog.record(
                    project=self.project,
                    actor=request.user,
                    action="job.move_batch",
                    target=job,
                    job=job,
                    before={"batch": before_name, "dataset_id": before_dataset_id},
                    after={
                        "batch": target_batch.name,
                        "batch_id": target_batch.id,
                        "dataset_id": target_batch.dataset_id,
                    },
                    note=note,
                )
        return Response({"updated": len(jobs), "batch": target_batch.id, "batch_name": target_batch.name})


class JobQueueView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/job-queue/ — Data Queue tổng hợp số lượng job theo stage."""

    required_capabilities = {"*": Cap.VIEW_JOBS}

    def get(self, request, project_id):
        jobs = Job.objects.filter(project=self.project)
        batch = request.query_params.get("batch")
        if batch:
            jobs = jobs.filter(batch_id=parse_int_param(batch, "batch"))
        now = timezone.now()
        result = []
        for stage in ("annotation", "qc1", "qc2"):
            stats = jobs.filter(status__in=STAGE_STATUSES[stage]).aggregate(
                total=Count("id"),
                unassigned=Count(
                    "id",
                    filter=Q(annotator__isnull=True)
                    if stage == "annotation"
                    else Q(qc1_reviewer__isnull=True)
                    if stage == "qc1"
                    else Q(pk__isnull=True),
                ),
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
    "active": [JobStatus.REWORK, JobStatus.ANNOTATING, JobStatus.PENDING_ANNOTATION],
    "todo": [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING],
    "rework": [JobStatus.REWORK],
    "submitted": [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING, JobStatus.QC1_PASSED, JobStatus.PENDING_QC2],
    "done": [JobStatus.APPROVED, JobStatus.DELIVERED],
}


def order_by_db06_priority(queryset, now=None):
    """Sắp xếp hàng đợi theo mức độ ưu tiên: quá hạn → sắp hạn (<= 24h) → rework → còn lại, deadline sớm trước."""
    now = now or timezone.now()
    soon_cutoff = now + timedelta(hours=24)
    return queryset.annotate(
        _db06_rank=Case(
            When(status__in=OPEN_STATUSES, deadline__lt=now, then=0),
            When(status__in=OPEN_STATUSES, deadline__lte=soon_cutoff, then=1),
            When(status=JobStatus.REWORK, then=2),
            default=3,
            output_field=IntegerField(),
        )
    ).order_by("_db06_rank", F("deadline").asc(nulls_last=True), "id")


class AnnotatorJobViewSet(
    ProjectScopedViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Không gian làm việc của Annotator: chỉ thấy và thao tác trên job được giao cho mình."""

    pagination_class = StandardPagination
    lookup_value_regex = r"\d+"
    required_capabilities = {"*": Cap.ANNOTATE_JOBS}

    def get_serializer_class(self) -> Any:
        if self.action == "retrieve":
            return JobDetailSerializer
        if self.action == "list" and self.request.query_params.get("include_errors") == "1":
            return JobWithErrorsSerializer
        return JobSerializer

    def get_queryset(self) -> Any:
        queryset = _base_job_queryset(self.project).filter(annotator=self.request.user)
        p = self.request.query_params
        if self.action == "list" and p.get("include_errors") == "1":
            queryset = queryset.prefetch_related(
                Prefetch("review_errors", queryset=ReviewError.objects.select_related("category", "reported_by"))
            )
        tab = p.get("tab")
        if tab in ANNOTATOR_TABS:
            queryset = queryset.filter(status__in=ANNOTATOR_TABS[tab])
        if p.get("status"):
            queryset = queryset.filter(status__in=p["status"].split(","))
        if p.get("batch"):
            queryset = queryset.filter(batch_id=parse_int_param(p["batch"], "batch"))
        if p.get("escalated") == "1":
            queryset = queryset.filter(is_escalated=True)
        if p.get("overdue") == "1":
            queryset = queryset.filter(deadline__lt=timezone.now(), status__in=OPEN_STATUSES)
        if p.get("due_soon") == "1":
            now = timezone.now()
            queryset = queryset.filter(
                deadline__gte=now,
                deadline__lte=now + timedelta(hours=24),
                status__in=ACTIVE_ANNOTATOR_STATUSES,
            )
        if p.get("search"):
            term = p["search"].strip()
            cond = Q(name__icontains=term) | Q(batch__name__icontains=term)
            if term.isdigit():
                num = int(term)
                if num <= PG_INT32_MAX:
                    cond |= Q(cvat_job_id=num) | Q(pk=num)
            queryset = queryset.filter(cond)
        ordering = p.get("ordering")
        if ordering in {"deadline", "-deadline", "rework_round", "-rework_round", "updated_at", "-updated_at"}:
            queryset = queryset.order_by(ordering, "id")
        else:
            queryset = order_by_db06_priority(queryset)
        return queryset

    def _detail(self, job):
        fresh = _base_job_queryset(self.project).get(pk=job.pk)
        return Response(JobDetailSerializer(fresh, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["post"])
    def claim(self, request, project_id):
        """Nhận job mới từ hàng chờ chưa phân công (tôn trọng giới hạn số job đang giữ)."""
        user = request.user

        with transaction.atomic():
            # Khoá dòng User để tuần tự hoá các yêu cầu claim đồng thời của cùng một annotator,
            # sau đó mới đọc vai trò, WIP limit và team_ids bên trong cùng giao dịch.
            locked_user = User.objects.select_for_update().get(pk=user.pk)
            project = Project.objects.only("id", "annotator_wip_limit").get(pk=self.project.pk)
            if Role.ANNOTATOR not in locked_user.get_project_roles(project):
                raise PermissionDenied("Bạn không còn vai trò Annotator trong organization.")
            wip_limit = project.annotator_wip_limit
            team_ids = list(
                TeamMember.objects.filter(user=locked_user, team__project=project).values_list("team_id", flat=True)
            )
            active_count = Job.objects.filter(
                project=project, annotator=locked_user, status__in=ACTIVE_ANNOTATOR_STATUSES
            ).count()
            if active_count >= wip_limit:
                raise ValidationError(
                    f"Bạn đang giữ {active_count}/{wip_limit} job. Hoàn tất bớt job trước khi nhận thêm."
                )

            pool = (
                Job.objects.select_for_update(of=("self",), skip_locked=True)
                .select_related("batch", "dataset")
                .filter(
                    project=project,
                    annotator__isnull=True,
                    status=JobStatus.PENDING_ANNOTATION,
                    is_locked=False,
                    is_escalated=False,
                    batch__status=DataStatus.ACTIVE,
                    dataset__status=DataStatus.ACTIVE,
                )
                .exclude(qc1_reviewer=locked_user)
                .exclude(
                    events__action__in=["qc1.start", "qc1.pass", "qc1.reject"],
                    events__actor=locked_user,
                )
                .exclude(audit_samples__auditor=locked_user)
                .exclude(audit_samples__reviewed_by=locked_user)
                .exclude(review_errors__reported_by=locked_user)
            )
            if team_ids:
                # Chặn chặt theo team: chỉ nhận job thuộc task của team mình hoặc task chung (chưa gán team).
                pool = (
                    pool.filter(Q(batch__team_id__in=team_ids) | Q(batch__team__isnull=True))
                    .annotate(
                        _team_pref=Case(
                            When(batch__team_id__in=team_ids, then=0),
                            default=1,
                            output_field=IntegerField(),
                        )
                    )
                    .order_by("_team_pref", F("deadline").asc(nulls_last=True), "id")
                )
            else:
                pool = pool.filter(batch__team__isnull=True).order_by(F("deadline").asc(nulls_last=True), "id")

            job = pool.first()
            if job is None:
                raise ValidationError("Hiện không còn job mới sẵn sàng để nhận trong organization.")

            job.annotator = locked_user
            job.save(update_fields=["annotator", "updated_at"])
            ActivityLog.record(
                project=self.project,
                actor=locked_user,
                action="job.assign",
                target=job,
                job=job,
                before={"annotator": None},
                after={"annotator": locked_user.pk, "event": "annotator.claim"},
                note="Tự nhận job từ hàng chờ",
            )
            schedule_assignee_push([job.pk])
        return self._detail(job)

    @action(detail=True, methods=["post"])
    def start(self, request, project_id, pk=None):
        """Bắt đầu gán nhãn hoặc bắt đầu sửa Rework (PENDING_ANNOTATION / REWORK -> ANNOTATING)."""
        job = self.get_object()
        data = validated_dict(AnnotatorStartSerializer(data=request.data))
        updated = start_annotation(
            job.pk,
            project=self.project,
            actor=request.user,
            note=data["note"],
        )
        return self._detail(updated)

    @action(detail=True, methods=["post"])
    def submit(self, request, project_id, pk=None):
        """Nộp bài sang hàng chờ QC1 (ANNOTATING -> PENDING_QC1)."""
        job = self.get_object()
        data = validated_dict(AnnotatorSubmitSerializer(data=request.data))
        updated = submit_annotation(
            job.pk,
            project=self.project,
            actor=request.user,
            note=data["note"],
            object_count=data.get("object_count"),
        )
        return self._detail(updated)


def _project_pms(project) -> list[User]:
    """Danh sách PM của organization, sắp theo user_id để chọn handler nhất quán."""
    assignments = (
        RoleAssignment.objects.filter(project=project, role=Role.PROJECT_MANAGER)
        .select_related("user")
        .order_by("user_id")
    )
    seen: set[int] = set()
    pms: list[User] = []
    for a in assignments:
        if a.user_id not in seen:
            seen.add(a.user_id)
            pms.append(a.user)
    return pms


class AnnotatorRequestViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Yêu cầu của Annotator: phản hồi lỗi QC & báo dữ liệu bị chặn."""

    serializer_class = AnnotatorRequestSerializer
    lookup_value_regex = r"\d+"
    required_capabilities = {
        "list": [Cap.ANNOTATE_JOBS, Cap.MANAGE_JOBS],
        "retrieve": [Cap.ANNOTATE_JOBS, Cap.MANAGE_JOBS],
        "create": Cap.ANNOTATE_JOBS,
        "resolve": Cap.MANAGE_JOBS,
        "*": [Cap.ANNOTATE_JOBS, Cap.MANAGE_JOBS],
    }

    def _base_queryset(self):
        return AnnotatorRequest.objects.filter(project=self.project).select_related(
            "job__batch", "review_error__category", "created_by", "handler"
        )

    def get_queryset(self) -> Any:
        qs = self._base_queryset()
        if not self.has_cap(Cap.MANAGE_JOBS):
            qs = qs.filter(created_by=self.request.user)

        p = self.request.query_params
        if p.get("request_type"):
            qs = qs.filter(request_type=p["request_type"])
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("job"):
            qs = qs.filter(job_id=parse_int_param(p["job"], "job"))
        return qs

    def create(self, request, project_id):
        data = validated_dict(AnnotatorRequestCreateSerializer(data=request.data, context=self.get_serializer_context()))
        job_id = data["job_obj"].pk
        review_error_obj = data["review_error_obj"]
        review_error_id = review_error_obj.pk if review_error_obj is not None else None
        req_type = data["request_type"]

        pms = _project_pms(self.project)
        handler = pms[0] if pms else None
        handler_role = "PM"
        initial_status = AnnotatorRequest.Status.PENDING_PM
        default_progress = (
            "PM đang đối chiếu lỗi được phản hồi."
            if req_type == AnnotatorRequest.RequestType.ERROR_DISPUTE
            else "PM đang kiểm tra dữ liệu bị chặn và phương án thay thế."
        )

        with transaction.atomic():
            job = lock_job(self.project, job_id)
            if job.annotator_id != request.user.id:
                raise ValidationError({"job": "Bạn chỉ có thể gửi yêu cầu trên job được giao cho mình."})
            if job.status in (JobStatus.APPROVED, JobStatus.DELIVERED):
                raise ValidationError({"job": "Không thể gửi yêu cầu trên job đã duyệt hoặc đã bàn giao."})

            review_error = None
            if review_error_id is not None:
                review_error = (
                    ReviewError.objects.select_for_update().filter(pk=review_error_id, job=job).first()
                )
                if review_error is None:
                    raise ValidationError({"review_error": "Lỗi không thuộc job này."})
                if review_error.is_voided:
                    raise ValidationError({"review_error": "Lỗi này đã được gỡ bỏ, không thể phản hồi lại."})

            if req_type == AnnotatorRequest.RequestType.ERROR_DISPUTE:
                dup_qs = AnnotatorRequest.objects.filter(
                    project=self.project,
                    job=job,
                    request_type=req_type,
                    status=AnnotatorRequest.Status.PENDING_PM,
                )
                if review_error is not None:
                    dup_qs = dup_qs.filter(review_error=review_error)
                else:
                    dup_qs = dup_qs.filter(review_error__isnull=True)
                if dup_qs.exists():
                    raise ValidationError("Đã có yêu cầu phản hồi lỗi đang chờ PM xử lý cho mục này.")
            elif (
                req_type == AnnotatorRequest.RequestType.DATA_ISSUE
                and AnnotatorRequest.objects.filter(
                    project=self.project,
                    job=job,
                    request_type=req_type,
                    status=AnnotatorRequest.Status.PENDING_PM,
                ).exists()
            ):
                raise ValidationError("Đã có báo cáo dữ liệu bị chặn đang chờ PM xử lý cho job này.")

            req = AnnotatorRequest.objects.create(
                project=self.project,
                job=job,
                review_error=review_error,
                request_type=req_type,
                status=initial_status,
                title=data["title"],
                reason=data["reason"].strip(),
                progress_note=default_progress,
                created_by=request.user,
                handler=handler,
                handler_role=handler_role,
            )
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action=(
                    "annotator.dispute"
                    if req_type == AnnotatorRequest.RequestType.ERROR_DISPUTE
                    else "annotator.data_issue"
                ),
                target=job,
                job=job,
                after={"request_id": req.id, "type": req_type, "status": initial_status},
                note=req.title,
            )
            if request.user.notify_request_updates:
                handler_name = handler.get_full_name() or handler.username if handler else handler_role
                UserNotification.objects.create(
                    recipient=request.user,
                    project=self.project,
                    job=job,
                    category=UserNotification.Category.DISPUTE,
                    title=f"{handler_role} đã nhận {req.get_request_type_display().lower()}",
                    body=f"{handler_name} đang xem yêu cầu '{req.title}' trên {job.name}.",
                    action_url=f"/projects/{self.project.id}/annotator/requests",
                    is_pinned_pending=True,
                )
            for pm in pms:
                if pm.id != request.user.id and pm.notify_request_updates:
                    UserNotification.objects.create(
                        recipient=pm,
                        project=self.project,
                        job=job,
                        category=UserNotification.Category.DISPUTE,
                        title=f"{req.get_request_type_display()} · {job.name}",
                        body=req.title,
                        action_url=f"/projects/{self.project.id}/annotator/requests",
                        is_pinned_pending=True,
                    )

        fresh = self._base_queryset().get(pk=req.pk)
        return Response(AnnotatorRequestSerializer(fresh).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def resolve(self, request, project_id, pk=None):
        """PM kết luận yêu cầu (RESOLVED hoặc REJECTED); nếu chấp nhận error_dispute thì gỡ lỗi (is_voided=True)."""
        data = validated_dict(AnnotatorRequestResolveSerializer(data=request.data))
        new_status = data["status"]
        req_pk = _parse_pk(pk, "Không tìm thấy yêu cầu trong organization.")

        with transaction.atomic():
            req = (
                AnnotatorRequest.objects.select_for_update(of=("self",))
                .select_related("job", "created_by")
                .filter(pk=req_pk, project=self.project)
                .first()
            )
            if req is None:
                raise NotFound("Không tìm thấy yêu cầu trong organization.")
            if req.status != AnnotatorRequest.Status.PENDING_PM:
                raise ValidationError("Yêu cầu này đã được xử lý, không thể cập nhật lại.")

            before_status = req.status
            req.status = new_status
            if data["progress_note"]:
                req.progress_note = data["progress_note"]
            if data["resolution_note"]:
                req.resolution_note = data["resolution_note"]
            req.handler = request.user
            req.handler_role = "PM"
            req.resolved_at = timezone.now()
            req.save()

            voided_error_id: int | None = None
            if (
                req.request_type == AnnotatorRequest.RequestType.ERROR_DISPUTE
                and new_status == AnnotatorRequest.Status.RESOLVED
                and req.review_error_id
            ):
                err = ReviewError.objects.select_for_update().filter(pk=req.review_error_id).first()
                if err is not None:
                    if not err.is_voided:
                        err.is_voided = True
                        err.save(update_fields=["is_voided"])
                    voided_error_id = err.pk

            pm_ids = list(
                RoleAssignment.objects.filter(project=self.project, role=Role.PROJECT_MANAGER)
                .values_list("user_id", flat=True)
                .distinct()
            )
            unpin_recipients = set(pm_ids) | {req.created_by_id}
            UserNotification.objects.filter(
                recipient_id__in=unpin_recipients,
                project=self.project,
                job=req.job,
                category=UserNotification.Category.DISPUTE,
                is_pinned_pending=True,
            ).update(is_pinned_pending=False)

            if req.created_by.notify_request_updates:
                UserNotification.objects.create(
                    recipient=req.created_by,
                    project=self.project,
                    job=req.job,
                    category=UserNotification.Category.DISPUTE,
                    title=f"{req.get_status_display()} · {req.job.name}",
                    body=req.resolution_note or req.title,
                    action_url=f"/projects/{self.project.id}/annotator/requests",
                )

            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="annotator.request_resolve",
                target=req.job,
                job=req.job,
                before={"request_id": req.id, "status": before_status},
                after={"request_id": req.id, "status": new_status, "voided_error_id": voided_error_id},
                note=req.resolution_note or req.progress_note,
            )

        fresh = self._base_queryset().get(pk=req.pk)
        return Response(AnnotatorRequestSerializer(fresh).data)


class AnnotatorQuickSearchView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/annotator/search/?q=... — Tìm kiếm nhanh (⌘K) trong phạm vi job của Annotator."""

    required_capabilities = {"*": Cap.ANNOTATE_JOBS}

    def get(self, request, project_id):
        q = (request.query_params.get("q") or "").strip()
        qs = order_by_db06_priority(
            Job.objects.filter(project=self.project, annotator=request.user).select_related("batch")
        )
        if q:
            cond = Q(name__icontains=q) | Q(batch__name__icontains=q)
            if q.isdigit():
                num = int(q)
                if num <= PG_INT32_MAX:
                    cond |= Q(cvat_job_id=num) | Q(pk=num)
            qs = qs.filter(cond)
        jobs = list(qs[:8])
        return Response({
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "batch_name": j.batch.name,
                    "status": j.status,
                    "status_label": j.get_status_display(),
                    "rework_round": j.rework_round,
                    "progress_percent": j.progress_percent,
                }
                for j in jobs
            ]
        })
