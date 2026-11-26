from datetime import timedelta

from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, Prefetch, Q, When
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.datetime_utils import format_rfc3339_utc, parse_query_date_range
from accounts.models import Role, RoleAssignment, User
from accounts.permissions import Cap, ProjectScopedViewMixin
from projects.models import ActivityLog, DataStatus, EscalationPolicy, UserNotification
from projects.notifications import notify_assigned, notify_review_needed, project_users_with_roles
from projects.views import StandardPagination
from quality.models import Audit, AuditSample, ReviewError
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
    BulkMoveBatchSerializer,
    BulkSerializer,
    DeadlineSerializer,
    JobDetailSerializer,
    JobSerializer,
    JobWithErrorsSerializer,
)


def _iso(value):
    return format_rfc3339_utc(value)


def _base_job_queryset(project):
    return (
        Job.objects.filter(project=project)
        .select_related("batch__dataset", "annotator", "qc1_reviewer", "project")
        .annotate(_open_error_count=Count("review_errors", distinct=True))
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
        raise ValidationError(f"Batch của job {job} đã khoá hoặc đã bàn giao.")
    if job.batch.dataset.status != DataStatus.ACTIVE:
        raise ValidationError(f"Dataset của job {job} đã khoá hoặc đã bàn giao.")
    if job.status == JobStatus.DELIVERED:
        raise ValidationError(f"Job {job} đã bàn giao.")


def ensure_not_escalated(job):
    if job.is_escalated and job.project.escalation_policy == EscalationPolicy.BLOCK:
        raise ValidationError("Job đang ở trạng thái Escalated, chờ PM xử lý.")


def lock_job(project, job_id):
    """Khoá dòng Job bằng select_for_update(of=("self",)) để an toàn trên PostgreSQL."""
    job = (
        Job.objects.select_for_update(of=("self",))
        .select_related("batch__dataset", "batch__team", "project", "annotator", "qc1_reviewer")
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
    update_fields = ["status", "updated_at"]
    if job.started_at is None:
        job.started_at = timezone.now()
        update_fields.append("started_at")
    job.save(update_fields=update_fields)
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
    # Thông báo "cần duyệt" tới người QC1 được giao (hoặc các QC1 trong dự án nếu job ở pool)
    review_targets = [job.qc1_reviewer] if job.qc1_reviewer_id else project_users_with_roles(project, Role.QC1)
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
    if "annotator" in after and after["annotator"] and after["annotator"] != before.get("annotator"):
        notify_assigned(project, job, job.annotator, role_label="Annotator", actor=actor)
    if "qc1_reviewer" in after and after["qc1_reviewer"] and after["qc1_reviewer"] != before.get("qc1_reviewer"):
        notify_assigned(project, job, job.qc1_reviewer, role_label="QC1", actor=actor)


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
        now = timezone.now()
        if p.get("status"):
            queryset = queryset.filter(status__in=p["status"].split(","))
        if p.get("stage") in STAGE_STATUSES:
            queryset = queryset.filter(status__in=STAGE_STATUSES[p["stage"]])
        if p.get("batch"):
            batch_ids = [int(x) for x in p["batch"].split(",") if x.strip().isdigit()]
            if batch_ids:
                queryset = queryset.filter(batch_id__in=batch_ids)
        if p.get("dataset"):
            dataset_ids = [int(x) for x in p["dataset"].split(",") if x.strip().isdigit()]
            if dataset_ids:
                queryset = queryset.filter(batch__dataset_id__in=dataset_ids)
        if p.get("assignee"):
            queryset = queryset.filter(Q(annotator_id=p["assignee"]) | Q(qc1_reviewer_id=p["assignee"]))
        if p.get("annotator") and p["annotator"].isdigit():
            queryset = queryset.filter(annotator_id=int(p["annotator"]))
        if p.get("qc1_reviewer") and p["qc1_reviewer"].isdigit():
            queryset = queryset.filter(qc1_reviewer_id=int(p["qc1_reviewer"]))
        if p.get("min_rework") and p["min_rework"].isdigit():
            queryset = queryset.filter(rework_round__gte=int(p["min_rework"]))
        if p.get("max_rework") and p["max_rework"].isdigit():
            queryset = queryset.filter(rework_round__lte=int(p["max_rework"]))
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
            queryset = queryset.filter(deadline__gte=now, deadline__lte=now + timedelta(hours=24), status__in=OPEN_STATUSES)
        if p.get("search"):
            term = p["search"].strip()
            cond = Q(name__icontains=term) | Q(batch__name__icontains=term)
            if term.isdigit():
                cond |= Q(cvat_job_id=int(term)) | Q(pk=int(term))
            queryset = queryset.filter(cond)
        ordering = p.get("ordering")
        if ordering in {"deadline", "-deadline", "rework_round", "-rework_round", "updated_at", "-updated_at"}:
            queryset = queryset.order_by(ordering, "id")
        else:
            queryset = queryset.order_by("deadline", "id")
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

    @action(detail=False, methods=["post"], url_path="bulk-move-batch")
    def bulk_move_batch(self, request, project_id):
        """Data Query: nhóm / chuyển hàng loạt job sang một batch đích trong cùng dự án."""
        serializer = BulkMoveBatchSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        target_batch = serializer.validated_data["batch"]
        note = serializer.validated_data["note"]
        jobs = list(self.get_queryset().filter(pk__in=serializer.validated_data["ids"]))
        if not jobs:
            raise ValidationError("Không tìm thấy job phù hợp để chuyển batch.")
        with transaction.atomic():
            for job in jobs:
                ensure_editable(job)
                if job.audit_samples.filter(audit__status=Audit.Status.IN_PROGRESS).exists():
                    raise ValidationError(f"Job {job} đang thuộc một đợt audit QC2 chưa chốt.")
                if job.batch_id == target_batch.id:
                    continue
                before_name = job.batch.name
                job.batch = target_batch
                job.save(update_fields=["batch", "updated_at"])
                ActivityLog.record(
                    project=self.project,
                    actor=request.user,
                    action="job.move_batch",
                    target=job,
                    job=job,
                    before={"batch": before_name},
                    after={"batch": target_batch.name, "batch_id": target_batch.id},
                    note=note,
                )
        return Response({"updated": len(jobs), "batch": target_batch.id, "batch_name": target_batch.name})


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
    "active": [JobStatus.REWORK, JobStatus.ANNOTATING, JobStatus.PENDING_ANNOTATION],
    "todo": [JobStatus.PENDING_ANNOTATION, JobStatus.ANNOTATING],
    "rework": [JobStatus.REWORK],
    "submitted": [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING, JobStatus.QC1_PASSED, JobStatus.PENDING_QC2],
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
        if self.action == "retrieve":
            return JobDetailSerializer
        if self.action == "list" and self.request.query_params.get("include_errors") == "1":
            return JobWithErrorsSerializer
        return JobSerializer

    def get_queryset(self):
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
            # Khoá dòng User để tuần tự hoá các request claim đồng thời của cùng một annotator (tránh vượt WIP limit).
            User.objects.select_for_update().get(pk=user.pk)
            active_count = Job.objects.filter(
                project=self.project, annotator=user, status__in=ACTIVE_ANNOTATOR_STATUSES
            ).count()
            if active_count >= wip_limit:
                raise ValidationError(
                    f"Bạn đang giữ {active_count}/{wip_limit} job (GV02). Hoàn tất bớt job trước khi nhận thêm."
                )

            pool = (
                Job.objects.select_for_update(skip_locked=True)
                .select_related("batch__dataset")
                .filter(
                    project=self.project,
                    annotator__isnull=True,
                    status=JobStatus.PENDING_ANNOTATION,
                    is_locked=False,
                    is_escalated=False,
                    batch__status=DataStatus.ACTIVE,
                    batch__dataset__status=DataStatus.ACTIVE,
                )
                .exclude(qc1_reviewer=user)
            )
            if team_ids:
                # Chặn chặt theo team: chỉ nhận job thuộc batch của team mình hoặc batch chung (chưa gán team).
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
                raise ValidationError("Hiện không còn job mới sẵn sàng để nhận trong dự án.")

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
                note="Tự nhận job từ hàng chờ (GV02)",
            )
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


def _find_request_handler(project, user, request_type):
    """Định tuyến yêu cầu trực tiếp tới PM phụ trách dự án."""
    pm_assignment = (
        RoleAssignment.objects.filter(project=project, role=Role.PROJECT_MANAGER)
        .select_related("user")
        .first()
    )
    pm = pm_assignment.user if pm_assignment else None
    return pm, "PM", AnnotatorRequest.Status.PENDING_PM


class AnnotatorRequestViewSet(
    ProjectScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Yêu cầu của Annotator (TD13): phản hồi lỗi QC1 & báo dữ liệu bị chặn."""

    serializer_class = AnnotatorRequestSerializer
    lookup_value_regex = r"\d+"
    required_capabilities = {
        "list": [Cap.ANNOTATE_JOBS, Cap.MANAGE_JOBS],
        "retrieve": [Cap.ANNOTATE_JOBS, Cap.MANAGE_JOBS],
        "create": Cap.ANNOTATE_JOBS,
        "resolve": Cap.MANAGE_JOBS,
    }

    def get_queryset(self):
        qs = AnnotatorRequest.objects.filter(project=self.project).select_related(
            "job__batch", "review_error__category", "created_by", "handler"
        )
        if not self.has_cap(Cap.MANAGE_JOBS):
            qs = qs.filter(created_by=self.request.user)

        p = self.request.query_params
        if p.get("request_type"):
            qs = qs.filter(request_type=p["request_type"])
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("job") and p["job"].isdigit():
            qs = qs.filter(job_id=int(p["job"]))
        return qs

    def create(self, request, project_id):
        serializer = AnnotatorRequestCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        job = data["job_obj"]
        review_error = data["review_error_obj"]
        req_type = data["request_type"]

        handler, handler_role, initial_status = _find_request_handler(self.project, request.user, req_type)
        default_progress = (
            "PM đang đối chiếu lỗi được phản hồi."
            if req_type == AnnotatorRequest.RequestType.ERROR_DISPUTE
            else "PM đang kiểm tra dữ liệu bị chặn và phương án thay thế."
        )

        with transaction.atomic():
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
            if handler and handler.id != request.user.id:
                UserNotification.objects.create(
                    recipient=handler,
                    project=self.project,
                    job=job,
                    category=UserNotification.Category.DISPUTE,
                    title=f"{req.get_request_type_display()} · {job.name}",
                    body=req.title,
                    action_url=f"/projects/{self.project.id}/annotator/requests",
                    is_pinned_pending=True,
                )

        fresh = self.get_queryset().get(pk=req.pk)
        return Response(AnnotatorRequestSerializer(fresh).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def resolve(self, request, project_id, pk=None):
        """PM cập nhật trạng thái hoặc kết luận yêu cầu."""
        req = self.get_object()
        if req.status in (AnnotatorRequest.Status.RESOLVED, AnnotatorRequest.Status.REJECTED):
            raise ValidationError("Yêu cầu này đã được kết luận.")
        serializer = AnnotatorRequestResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]
        with transaction.atomic():
            req.status = new_status
            if serializer.validated_data["progress_note"]:
                req.progress_note = serializer.validated_data["progress_note"]
            if serializer.validated_data["resolution_note"]:
                req.resolution_note = serializer.validated_data["resolution_note"]
            if new_status == AnnotatorRequest.Status.PENDING_PM:
                pm_assignment = (
                    RoleAssignment.objects.filter(project=self.project, role=Role.PROJECT_MANAGER)
                    .select_related("user")
                    .first()
                )
                req.handler = pm_assignment.user if pm_assignment else req.handler
                req.handler_role = "PM"
            else:
                req.handler = request.user
                req.handler_role = "PM"
                req.resolved_at = timezone.now()
            req.save()

            if new_status in (AnnotatorRequest.Status.RESOLVED, AnnotatorRequest.Status.REJECTED):
                UserNotification.objects.filter(
                    recipient=req.created_by,
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

        return Response(AnnotatorRequestSerializer(self.get_queryset().get(pk=req.pk)).data)


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
                cond |= Q(cvat_job_id=int(q)) | Q(pk=int(q))
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
