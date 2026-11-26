"""Nhập và đồng bộ Job từ cvat-base gốc vào VanoHub.

Quy tắc biên dữ liệu:
- 1 Batch VanoHub  ↔ 1 CVAT Task (duy nhất qua Partial UniqueConstraint)
- 1 Job VanoHub    ↔ 1 CVAT annotation Job (bỏ qua ground_truth và consensus replica)
- Toàn bộ HTTP I/O gọi CVAT thực hiện NGOÀI transaction.atomic() để không giữ khóa DB.
- Trạng thái: chỉ đồng bộ cho các bước TRƯỚC QC2 (SYNCABLE_STATUSES), không bao giờ bỏ qua
  bước PM `confirm-qc2` (L3), tôn trọng khóa (`is_locked`) và `escalation_policy=block`.
- Sản lượng ngày: khi `count_objects=True` thấy số cuboid/object-frame tăng thêm trên job đang
  ở giai đoạn annotate/rework, ghi ngay phần chênh lệch dương vào `DailyOutputRecord` cho ngày
  làm việc đó (tính cả khi chưa QC và không cộng đúp khi nộp/QC sau này).
"""

from django.db import transaction
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError

from accounts.models import User
from jobs.models import (
    ACTIVE_ANNOTATOR_STATUSES,
    STAGE_STATUSES,
    DailyOutputRecord,
    FirstQc1Result,
    Job,
    JobStatus,
    record_daily_output,
)
from projects.models import ActivityLog, Batch, DataStatus, EscalationPolicy
from projects.notifications import notify_escalated

from .client import CvatClient, CvatError, CvatNotFoundError
from .schemas import CvatImportResult, CvatJobPayload, CvatSyncResult, CvatTaskPayload

# (stage, state) của cvat-base gốc → trạng thái VanoHub.
# Lưu ý (L3): acceptance ở CVAT tối đa về QC1_PASSED, không bao giờ tự nhảy sang PENDING_QC2.
CVAT_STATUS_MAP = {
    ("annotation", "new"): JobStatus.PENDING_ANNOTATION,
    ("annotation", "in progress"): JobStatus.ANNOTATING,
    ("annotation", "rejected"): JobStatus.REWORK,
    ("annotation", "completed"): JobStatus.PENDING_QC1,
    ("validation", "new"): JobStatus.PENDING_QC1,
    ("validation", "in progress"): JobStatus.QC1_REVIEWING,
    ("validation", "rejected"): JobStatus.REWORK,
    ("validation", "completed"): JobStatus.QC1_PASSED,
    ("acceptance", "new"): JobStatus.QC1_PASSED,
    ("acceptance", "in progress"): JobStatus.QC1_PASSED,
    ("acceptance", "completed"): JobStatus.QC1_PASSED,
}
SYNCABLE_STATUSES = set(STAGE_STATUSES["annotation"] + STAGE_STATUSES["qc1"])


def _parse_task(raw) -> CvatTaskPayload:
    try:
        return CvatTaskPayload.model_validate(raw)
    except PydanticValidationError as exc:
        raise CvatError(f"Dữ liệu CVAT task không hợp lệ: {exc}") from exc


def _parse_job(raw) -> CvatJobPayload:
    try:
        return CvatJobPayload.model_validate(raw)
    except PydanticValidationError as exc:
        raise CvatError(f"Dữ liệu CVAT job không hợp lệ: {exc}") from exc


def _is_annotation_job(cvat_job: CvatJobPayload) -> bool:
    return cvat_job.type in ("", "annotation")


def _user_lookup():
    """Ánh xạ assignee CVAT → user VanoHub: ưu tiên cvat_username đã liên kết, sau đó tới username."""
    all_users = list(User.objects.all())
    lookup = {u.username: u for u in all_users}
    for u in all_users:
        if u.cvat_username:
            lookup[u.cvat_username] = u
    return lookup


def _can_mutate_status(job: Job) -> bool:
    if job.is_locked or job.status not in SYNCABLE_STATUSES:
        return False
    return not (job.is_escalated and job.project.escalation_policy == EscalationPolicy.BLOCK)


def _apply_cvat_state(job: Job, cvat_job: CvatJobPayload, actor) -> tuple[bool, dict | None, bool]:
    """Cập nhật trạng thái in-memory của Job từ dữ liệu CVAT (caller chịu trách nhiệm job.save()).

    Trả về `(changed, status_log_kwargs_or_none, newly_escalated)`.
    """
    stage, state = cvat_job.stage, cvat_job.state
    resolved_frames = cvat_job.resolved_frame_count
    changed = (
        job.cvat_stage != stage
        or job.cvat_state != state
        or job.frame_count != resolved_frames
        or job.source_missing
    )
    job.cvat_stage = stage
    job.cvat_state = state
    job.frame_count = resolved_frames
    job.source_missing = False

    new_status = CVAT_STATUS_MAP.get((stage, state))
    if not (new_status and _can_mutate_status(job) and new_status != job.status):
        return changed, None, False

    before = job.status
    newly_escalated = False
    log_actor = actor
    after_payload: dict[str, object] = {"status": new_status}

    if new_status == JobStatus.REWORK:
        job.rework_round += 1
        job.total_rework_rounds = max(job.total_rework_rounds + 1, job.rework_round)
        job.round_credited_objects = 0
        job.last_counted_objects = max(job.last_counted_objects, job.object_count)
        if not job.first_qc1_result and stage == "validation":
            job.first_qc1_result = FirstQc1Result.REJECT
        if job.rework_round > job.project.max_rework_rounds and not job.is_escalated:
            job.is_escalated = True
            newly_escalated = True
        after_payload["rework_round"] = job.rework_round
        after_payload["escalated"] = job.is_escalated
    elif new_status == JobStatus.QC1_PASSED:
        if not job.first_qc1_result:
            job.first_qc1_result = FirstQc1Result.PASS
    elif new_status == JobStatus.PENDING_QC1:
        job.submitted_at = timezone.now()
        log_actor = job.annotator or actor
        is_rw = job.total_rework_rounds > 0 or job.rework_round > 0
        after_payload["event"] = "annotator.resubmit" if is_rw else "annotator.submit"
        after_payload["rework_round"] = job.rework_round
        after_payload["object_count"] = job.object_count
        if actor and log_actor and actor.pk != log_actor.pk:
            after_payload["synced_by"] = actor.pk

    job.status = new_status
    status_log = {
        "project": job.project,
        "actor": log_actor,
        "action": "job.status",
        "target": job,
        "job": job,
        "before": {"status": before},
        "after": after_payload,
        "note": "Đồng bộ từ CVAT",
    }
    return True, status_log, newly_escalated


def import_task_jobs(batch, task_id, actor, client=None):
    """Tạo Job VanoHub cho mọi annotation job của một CVAT Task. Job đã có thì cập nhật."""
    if batch.status != DataStatus.ACTIVE or batch.dataset.status != DataStatus.ACTIVE:
        raise ValidationError("Batch hoặc Dataset đã khoá hoặc đã bàn giao.")
    if Batch.objects.filter(cvat_task_id=task_id).exclude(pk=batch.pk).exists():
        raise ValidationError({"cvat_task_id": f"CVAT task {task_id} đã được gắn với một batch khác."})

    client = client or CvatClient()
    task = _parse_task(client.get_task(task_id))
    project = batch.dataset.project
    if project.cvat_project_id and task.project_id is not None and task.project_id != project.cvat_project_id:
        raise ValidationError(
            {
                "cvat_task_id": (
                    f"CVAT task {task_id} thuộc CVAT project {task.project_id}, "
                    f"không khớp dự án hiện tại ({project.cvat_project_id})."
                )
            }
        )

    cvat_jobs = [j for j in (_parse_job(raw) for raw in client.list_task_jobs(task_id)) if _is_annotation_job(j)]
    users = _user_lookup()
    created = updated = 0

    with transaction.atomic():
        locked_batch = Batch.objects.select_for_update(of=("self",)).select_related("dataset__project").get(pk=batch.pk)
        if locked_batch.status != DataStatus.ACTIVE or locked_batch.dataset.status != DataStatus.ACTIVE:
            raise ValidationError("Batch hoặc Dataset đã khoá hoặc đã bàn giao.")
        if Batch.objects.filter(cvat_task_id=task_id).exclude(pk=locked_batch.pk).exists():
            raise ValidationError({"cvat_task_id": f"CVAT task {task_id} đã được gắn với một batch khác."})

        locked_batch.cvat_task_id = task_id
        locked_batch.source_missing = False
        for cvat_job in cvat_jobs:
            job = (
                Job.objects.select_for_update(of=("self",))
                .select_related("project", "batch__dataset", "annotator")
                .filter(cvat_job_id=cvat_job.id)
                .first()
            )
            if job is None:
                assignee = cvat_job.assignee.username if cvat_job.assignee else None
                initial_status = CVAT_STATUS_MAP.get(
                    (cvat_job.stage, cvat_job.state), JobStatus.PENDING_ANNOTATION
                )
                initial_rework = 1 if initial_status == JobStatus.REWORK else 0
                if initial_status == JobStatus.QC1_PASSED:
                    initial_first_qc1 = FirstQc1Result.PASS
                elif initial_status == JobStatus.REWORK and cvat_job.stage == "validation":
                    initial_first_qc1 = FirstQc1Result.REJECT
                else:
                    initial_first_qc1 = ""
                job = Job(
                    project=project,
                    batch=locked_batch,
                    name=f"{task.name or 'task'} · job {cvat_job.id}",
                    cvat_job_id=cvat_job.id,
                    cvat_task_id=task_id,
                    annotator=users.get(assignee) if assignee else None,
                    deadline=locked_batch.deadline,
                    cvat_stage=cvat_job.stage,
                    cvat_state=cvat_job.state,
                    frame_count=cvat_job.resolved_frame_count,
                    status=initial_status,
                    rework_round=initial_rework,
                    total_rework_rounds=initial_rework,
                    first_qc1_result=initial_first_qc1,
                )
                job.save()
                ActivityLog.record(
                    project=project,
                    actor=actor,
                    action="job.import",
                    target=job,
                    job=job,
                    note=f"Nhập từ CVAT task {task_id}",
                )
                created += 1
            elif job.batch_id != locked_batch.id:
                continue  # job thuộc batch khác → không động vào
            else:
                changed, status_log, newly_escalated = _apply_cvat_state(job, cvat_job, actor)
                if changed:
                    job.save()
                    if status_log:
                        ActivityLog.record(**status_log)
                    if newly_escalated:
                        notify_escalated(job.project, job, actor=actor)
                    updated += 1
        locked_batch.last_synced_at = timezone.now()
        locked_batch.last_sync_status = Batch.SyncStatus.OK
        locked_batch.last_sync_error = ""
        locked_batch.save(
            update_fields=[
                "cvat_task_id",
                "source_missing",
                "last_synced_at",
                "last_sync_status",
                "last_sync_error",
            ]
        )
    batch.cvat_task_id = locked_batch.cvat_task_id
    batch.source_missing = locked_batch.source_missing
    batch.last_synced_at = locked_batch.last_synced_at
    batch.last_sync_status = locked_batch.last_sync_status
    batch.last_sync_error = locked_batch.last_sync_error
    return CvatImportResult(
        task_name=task.name or None,
        created=created,
        updated=updated,
        total=len(cvat_jobs),
    ).model_dump()


def sync_batch(batch, actor, client=None, count_objects=False):
    """Đồng bộ lại trạng thái (và tùy chọn: số cuboid/object-frame) của các job trong batch."""
    if not batch.cvat_task_id:
        return CvatSyncResult(updated=0, total=0).model_dump()
    if batch.status != DataStatus.ACTIVE or batch.dataset.status != DataStatus.ACTIVE:
        raise ValidationError("Batch hoặc Dataset đã khoá hoặc đã bàn giao.")

    client = client or CvatClient()
    try:
        parsed_jobs = [
            j for j in (_parse_job(raw) for raw in client.list_task_jobs(batch.cvat_task_id)) if _is_annotation_job(j)
        ]
    except CvatNotFoundError as exc:
        Batch.objects.filter(pk=batch.pk).update(
            source_missing=True,
            last_sync_status=Batch.SyncStatus.ERROR,
            last_sync_error=str(exc),
            last_synced_at=timezone.now(),
        )
        raise

    by_id = {j.id: j for j in parsed_jobs}

    # Thực hiện toàn bộ HTTP I/O đếm object NGOÀI transaction.atomic()
    fetched_counts: dict[int, int] = {}
    if count_objects:
        existing_cvat_ids = list(
            batch.jobs.filter(cvat_job_id__isnull=False).values_list("cvat_job_id", flat=True)
        )
        for cjid in existing_cvat_ids:
            if cjid not in by_id:
                continue
            cvat_job_meta = by_id[cjid]
            if isinstance(client, CvatClient):
                count = client.count_job_objects(
                    cjid,
                    start_frame=cvat_job_meta.start_frame,
                    stop_frame=cvat_job_meta.stop_frame,
                )
            else:
                count = client.count_job_objects(cjid)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise CvatError(f"Số object trả về từ CVAT không hợp lệ: {count!r}")
            fetched_counts[cjid] = count

    updated = 0
    with transaction.atomic():
        locked_batch = Batch.objects.select_for_update(of=("self",)).select_related("dataset__project").get(pk=batch.pk)
        if locked_batch.status != DataStatus.ACTIVE or locked_batch.dataset.status != DataStatus.ACTIVE:
            raise ValidationError("Batch hoặc Dataset đã khoá hoặc đã bàn giao.")

        jobs = (
            locked_batch.jobs.select_for_update(of=("self",))
            .select_related("project", "batch__dataset", "batch__team", "annotator")
            .filter(cvat_job_id__isnull=False)
        )
        for job in jobs:
            assert job.cvat_job_id is not None
            cvat_job = by_id.get(job.cvat_job_id)
            if not cvat_job:
                if not job.source_missing:
                    job.source_missing = True
                    job.save(update_fields=["source_missing", "updated_at"])
                    updated += 1
                continue

            changed = False
            if count_objects and job.cvat_job_id in fetched_counts and not job.is_locked and job.status != JobStatus.DELIVERED:
                new_count = fetched_counts[job.cvat_job_id]
                if new_count != job.object_count:
                    job.object_count = new_count
                    changed = True
                # Ghi sản lượng theo ngày NGAY CẢ KHI CHƯA QC (đang annotate/rework)
                # VÀ cả khi đã nộp/đã qua QC1 nhưng chưa từng đồng bộ object_count từ CVAT
                # (không phát sinh sản lượng giả trên job APPROVED cũ không có submitted_at).
                can_credit = (
                    job.status in ACTIVE_ANNOTATOR_STATUSES
                    or job.status in SYNCABLE_STATUSES
                    or job.submitted_at is not None
                )
                if job.annotator_id and can_credit and new_count > job.last_counted_objects:
                    delta = new_count - job.last_counted_objects
                    is_rework = job.total_rework_rounds > 0 or job.rework_round > 0
                    credit_at = (
                        timezone.now()
                        if job.status in ACTIVE_ANNOTATOR_STATUSES
                        else (job.submitted_at or timezone.now())
                    )
                    record_daily_output(
                        job=job,
                        user=job.annotator,
                        object_count=delta,
                        is_rework=is_rework,
                        rework_round=max(job.total_rework_rounds, job.rework_round),
                        source=DailyOutputRecord.Source.CVAT_SYNC,
                        at=credit_at,
                    )
                    job.last_counted_objects = new_count
                    job.round_credited_objects += delta
                    changed = True

            state_changed, status_log, newly_escalated = _apply_cvat_state(job, cvat_job, actor)
            changed |= state_changed

            if changed:
                job.save()
                if status_log:
                    ActivityLog.record(**status_log)
                if newly_escalated:
                    notify_escalated(job.project, job, actor=actor)
                updated += 1

        locked_batch.source_missing = False
        locked_batch.last_synced_at = timezone.now()
        locked_batch.last_sync_status = Batch.SyncStatus.OK
        locked_batch.last_sync_error = ""
        locked_batch.save(update_fields=["source_missing", "last_synced_at", "last_sync_status", "last_sync_error"])
    batch.source_missing = locked_batch.source_missing
    batch.last_synced_at = locked_batch.last_synced_at
    batch.last_sync_status = locked_batch.last_sync_status
    batch.last_sync_error = locked_batch.last_sync_error
    return CvatSyncResult(updated=updated, total=len(by_id)).model_dump()
