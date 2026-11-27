from datetime import timedelta

from accounts.datetime_utils import PG_INT32_MAX, parse_int_param
from accounts.models import Role, RoleAssignment, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from cvat_integration.assignee import schedule_assignee_push
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, When
from django.utils import timezone
from projects.models import ActivityLog, DataStatus, UserNotification
from projects.views import StandardPagination
from quality.models import Audit, AuditSample
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from teams.models import TeamMember

from .models import (
    ACTIVE_ANNOTATOR_STATUSES,
    OPEN_STATUSES,
    STAGE_STATUSES,
    AnnotatorRequest,
    Job,
    JobStatus,
)
from .serializers import (
    AnnotatorRequestCreateSerializer,
    AnnotatorRequestResolveSerializer,
    AnnotatorRequestSerializer,
    AnnotatorStartSerializer,
    AnnotatorSubmitSerializer,
    AssignSerializer,
    BulkSerializer,
    DeadlineSerializer,
    JobDetailSerializer,
    JobSerializer,
)

ASSIGN_LOCKED_STATUSES = {JobStatus.PENDING_QC2, JobStatus.APPROVED, JobStatus.DELIVERED}


def _iso(value):
    return value.isoformat() if value else None


def _parse_pk(raw, not_found_message="Không tìm thấy bản ghi trong organization."):
    try:
        pk = int(raw)
    except (TypeError, ValueError) as exc:
        raise NotFound(not_found_message) from exc
    if pk < 1 or pk > PG_INT32_MAX:
        raise NotFound(not_found_message)
    return pk


def _base_job_queryset(project):
    return (
        Job.objects.filter(project=project)
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
                queryset=AuditSample.objects.filter(audit__status=Audit.Status.IN_PROGRESS).select_related("auditor"),
                to_attr="open_samples",
            )
        )
    )


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
    if job.is_escalated:
        raise ValidationError("Job đang ở trạng thái Escalated, chờ PM xử lý.")


def lock_job(project, job_id):
    """Khoá dòng Job bằng select_for_update(of=("self",)) để an toàn trên PostgreSQL."""
    job = (
        Job.objects.select_for_update(of=("self",))
        .select_related("batch", "dataset", "project", "annotator", "qc1_reviewer")
        .filter(pk=job_id, project=project)
        .first()
    )
    if job is None:
        raise NotFound("Không tìm thấy job trong organization.")
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
            f"Chỉ có thể nộp bài khi job ở trạng thái Đang annotate "
            f"(hiện tại: {job.get_status_display()})."
        )

    prev_status = job.status
    prev_objects = job.object_count
    job.status = JobStatus.PENDING_QC1
    job.submitted_at = timezone.now()
    update_fields = ["status", "submitted_at", "updated_at"]
    if object_count is not None:
        job.object_count = object_count
        update_fields.append("object_count")
    job.save(update_fields=update_fields)

    # TB03: gỡ ghim thông báo rework/deadline của job sau khi đã nộp xử lý.
    UserNotification.objects.filter(
        recipient=actor,
        project=project,
        job=job,
        is_pinned_pending=True,
    ).update(is_pinned_pending=False)

    before = {"status": prev_status}
    after = {
        "status": JobStatus.PENDING_QC1,
        "event": "annotator.resubmit" if job.rework_round > 0 else "annotator.submit",
        "rework_round": job.rework_round,
        "object_count": job.object_count,
    }
    if object_count is not None and object_count != prev_objects:
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
    schedule_assignee_push([job.pk])
    return job


def assign_job(job, data, actor, project, *, push_cvat=True):
    ensure_editable(job)
    if job.status in ASSIGN_LOCKED_STATUSES:
        raise ValidationError(
            f"Không thể đổi annotator hoặc người QC1 khi job ở trạng thái {job.get_status_display()}."
        )

    from quality.qc2 import get_stage_history

    annotator_ids, qc1_ids, qc2_ids = get_stage_history(job)
    new_annotator = data.get("annotator", job.annotator)
    new_qc1 = data.get("qc1_reviewer", job.qc1_reviewer)
    new_ann_id = new_annotator.pk if new_annotator else None
    new_qc1_id = new_qc1.pk if new_qc1 else None

    if new_ann_id and new_ann_id == new_qc1_id:
        raise ValidationError("Luật bốn mắt: người QC1 không được là annotator của chính job đó.")
    if "annotator" in data and new_ann_id and new_ann_id in (qc1_ids | qc2_ids):
        raise ValidationError("Luật bốn mắt: người này đã tham gia QC1 hoặc QC2 job này.")
    if "qc1_reviewer" in data and new_qc1_id and new_qc1_id in (annotator_ids | qc2_ids):
        raise ValidationError("Luật bốn mắt: người này đã annotate hoặc QC2 job này.")

    before, after = {}, {}
    for field in ("annotator", "qc1_reviewer"):
        if field in data:
            before[field] = getattr(job, f"{field}_id")
            setattr(job, field, data[field])
            after[field] = data[field].pk if data[field] else None
    if after:
        job.save(update_fields=[*after.keys(), "updated_at"])
    ActivityLog.record(project=project, actor=actor, action="job.assign", target=job, job=job,
                       before=before, after=after, note=data.get("note", ""))
    if push_cvat:
        # Người nhận chưa liên kết CVAT vẫn giao được; assignee CVAT được đẩy khi họ liên kết xong.
        schedule_assignee_push([job.pk])


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
            queryset = queryset.filter(batch_id=parse_int_param(p["batch"], "batch"))
        if p.get("dataset"):
            queryset = queryset.filter(dataset_id=parse_int_param(p["dataset"], "dataset"))
        if p.get("assignee"):
            assignee_id = parse_int_param(p["assignee"], "assignee")
            queryset = queryset.filter(Q(annotator_id=assignee_id) | Q(qc1_reviewer_id=assignee_id))
        if p.get("escalated") == "1":
            queryset = queryset.filter(is_escalated=True)
        if p.get("locked") == "1":
            queryset = queryset.filter(is_locked=True)
        if p.get("unassigned") == "1":
            queryset = queryset.filter(annotator__isnull=True)
        if p.get("overdue") == "1":
            queryset = queryset.filter(deadline__lt=timezone.now(), status__in=OPEN_STATUSES)
        if p.get("due_soon") == "1":
            now = timezone.now()
            queryset = queryset.filter(
                deadline__gte=now,
                deadline__lte=now + timedelta(hours=24),
                status__in=OPEN_STATUSES,
            )
        if p.get("search"):
            term = p["search"].strip()
            cond = Q(name__icontains=term)
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
        serializer = AssignSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            job = lock_job(self.project, _parse_pk(pk, "Không tìm thấy job trong organization."))
            assign_job(job, serializer.validated_data, request.user, self.project)
        return self._detail(job)

    @action(detail=True, methods=["post"])
    def deadline(self, request, project_id, pk=None):
        serializer = DeadlineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            job = lock_job(self.project, _parse_pk(pk, "Không tìm thấy job trong organization."))
            set_job_deadline(job, serializer.validated_data["deadline"], serializer.validated_data["note"],
                             request.user, self.project)
        return self._detail(job)

    def _toggle_lock(self, request, pk, locked):
        with transaction.atomic():
            job = lock_job(self.project, _parse_pk(pk, "Không tìm thấy job trong organization."))
            if job.is_locked == locked:
                raise ValidationError("Job đã ở trạng thái này.")
            job.is_locked = locked
            job.save(update_fields=["is_locked", "updated_at"])
            ActivityLog.record(project=self.project, actor=request.user, action="job.lock" if locked else "job.unlock",
                               target=job, job=job, note=request.data.get("note", ""))
        return self._detail(job)

    @action(detail=True, methods=["post"])
    def lock(self, request, project_id, pk=None):
        return self._toggle_lock(request, pk, True)

    @action(detail=True, methods=["post"])
    def unlock(self, request, project_id, pk=None):
        return self._toggle_lock(request, pk, False)

    @action(detail=True, methods=["post"], url_path="resolve-escalation")
    def resolve_escalation(self, request, project_id, pk=None):
        """PM xử lý job Escalated: giao cho annotator khác (tuỳ chọn) và gỡ cờ escalated.

        ĐỀ XUẤT: gỡ escalation thì đặt lại rework_round = 0 cho người mới (total_rework_rounds giữ nguyên).
        """
        with transaction.atomic():
            job = lock_job(self.project, _parse_pk(pk, "Không tìm thấy job trong organization."))
            ensure_editable(job)
            if not job.is_escalated:
                raise ValidationError("Job không ở trạng thái Escalated.")
            if "annotator" in request.data:
                serializer = AssignSerializer(
                    data={"annotator": request.data["annotator"]},
                    context=self.get_serializer_context(),
                )
                serializer.is_valid(raise_exception=True)
                assign_job(job, serializer.validated_data, request.user, self.project)
            before_round = job.rework_round
            job.is_escalated = False
            job.rework_round = 0
            job.save(update_fields=["is_escalated", "rework_round", "updated_at"])
            ActivityLog.record(
                project=self.project,
                actor=request.user,
                action="job.resolve_escalation",
                target=job,
                job=job,
                before={"rework_round": before_round},
                after={"rework_round": 0, "total_rework_rounds": job.total_rework_rounds},
                note=request.data.get("note", ""),
            )
        return self._detail(job)

    @action(detail=False, methods=["post"], url_path="bulk-assign")
    def bulk_assign(self, request, project_id):
        ids = BulkSerializer(data=request.data)
        ids.is_valid(raise_exception=True)
        data = AssignSerializer(data=request.data, context=self.get_serializer_context())
        data.is_valid(raise_exception=True)
        changed_ids = []
        with transaction.atomic():  # một job lỗi → không job nào bị đổi
            jobs = list(
                Job.objects.select_for_update(of=("self",))
                .select_related("batch", "dataset", "project", "annotator", "qc1_reviewer")
                .filter(project=self.project, pk__in=ids.validated_data["ids"])
                .order_by("id")
            )
            for job in jobs:
                assign_job(job, data.validated_data, request.user, self.project, push_cvat=False)
                changed_ids.append(job.pk)
            if changed_ids:
                schedule_assignee_push(changed_ids)
        return Response({"updated": len(jobs)})

    @action(detail=False, methods=["post"], url_path="bulk-deadline")
    def bulk_deadline(self, request, project_id):
        ids = BulkSerializer(data=request.data)
        ids.is_valid(raise_exception=True)
        data = DeadlineSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        with transaction.atomic():
            jobs = list(
                Job.objects.select_for_update(of=("self",))
                .select_related("batch", "dataset", "project")
                .filter(project=self.project, pk__in=ids.validated_data["ids"])
                .order_by("id")
            )
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
            jobs = jobs.filter(batch_id=parse_int_param(batch, "batch"))
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
    "active": [JobStatus.REWORK, JobStatus.ANNOTATING, JobStatus.PENDING_ANNOTATION],
    "todo": [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING],
    "rework": [JobStatus.REWORK],
    "submitted": [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING, JobStatus.PENDING_QC2],
    "done": [JobStatus.APPROVED, JobStatus.DELIVERED],
}


def order_by_db06_priority(queryset, now=None):
    """Sắp xếp hàng đợi theo DB06: quá hạn → sắp hạn (<= 24h) → rework → còn lại, deadline sớm trước."""
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
        """Nhận job mới từ hàng chờ chưa phân công (GV02: tôn trọng giới hạn số job đang giữ)."""
        user = request.user
        wip_limit = self.project.annotator_wip_limit
        team_ids = list(
            TeamMember.objects.filter(user=user, team__project=self.project).values_list("team_id", flat=True)
        )

        with transaction.atomic():
            # Khoá dòng User để tuần tự hoá các yêu cầu claim đồng thời của cùng một annotator.
            User.objects.select_for_update().get(pk=user.pk)
            active_count = Job.objects.filter(
                project=self.project, annotator=user, status__in=ACTIVE_ANNOTATOR_STATUSES
            ).count()
            if active_count >= wip_limit:
                raise ValidationError(
                    f"Bạn đang giữ {active_count}/{wip_limit} job (GV02). Hoàn tất bớt job trước khi nhận thêm."
                )

            pool = (
                Job.objects.select_for_update(of=("self",), skip_locked=True)
                .select_related("batch", "dataset")
                .filter(
                    project=self.project,
                    annotator__isnull=True,
                    status=JobStatus.PENDING_ANNOTATION,
                    is_locked=False,
                    is_escalated=False,
                    batch__status=DataStatus.ACTIVE,
                    dataset__status=DataStatus.ACTIVE,
                )
                .exclude(qc1_reviewer=user)
            )
            if team_ids:
                pool = pool.annotate(
                    _team_pref=Case(
                        When(batch__team_id__in=team_ids, then=0),
                        When(batch__team__isnull=True, then=1),
                        default=2,
                        output_field=IntegerField(),
                    )
                ).order_by("_team_pref", F("deadline").asc(nulls_last=True), "id")
            else:
                pool = pool.order_by(F("deadline").asc(nulls_last=True), "id")

            job = pool.first()
            if job is None:
                raise ValidationError("Hiện không còn job mới sẵn sàng để nhận trong organization.")

            job.annotator = user
            job.save(update_fields=["annotator", "updated_at"])
            ActivityLog.record(
                project=self.project,
                actor=user,
                action="job.assign",
                target=job,
                job=job,
                before={"annotator": None},
                after={"annotator": user.pk, "event": "annotator.claim"},
                note="Tự nhận job từ hàng chờ",
            )
            schedule_assignee_push([job.pk])
        return self._detail(job)

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


def _project_pms(project):
    """Danh sách PM của dự án, sắp theo user_id để chọn handler nhất quán."""
    assignments = (
        RoleAssignment.objects.filter(project=project, role=Role.PROJECT_MANAGER)
        .select_related("user")
        .order_by("user_id")
    )
    seen = set()
    pms = []
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

    def get_queryset(self):
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
        serializer = AnnotatorRequestCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        job_id = data["job_obj"].pk
        review_error = data["review_error_obj"]
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
                action="annotator.dispute" if req_type == AnnotatorRequest.RequestType.ERROR_DISPUTE else "annotator.data_issue",
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
        """PM kết luận yêu cầu (RESOLVED hoặc REJECTED)."""
        serializer = AnnotatorRequestResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]
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
            if serializer.validated_data["progress_note"]:
                req.progress_note = serializer.validated_data["progress_note"]
            if serializer.validated_data["resolution_note"]:
                req.resolution_note = serializer.validated_data["resolution_note"]
            req.handler = request.user
            req.handler_role = "PM"
            req.resolved_at = timezone.now()
            req.save()

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
                after={"request_id": req.id, "status": new_status},
                note=req.resolution_note or req.progress_note,
            )

        fresh = self._base_queryset().get(pk=req.pk)
        return Response(AnnotatorRequestSerializer(fresh).data)


class AnnotatorQuickSearchView(ProjectScopedViewMixin, APIView):
    """GET /api/projects/{id}/annotator/search/?q=... — Tìm kiếm nhanh (⌘K) trong phạm vi PQ01."""

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
