"""Nhập và đồng bộ Job từ CVAT vào Vanohub.

ĐỀ XUẤT ÁNH XẠ (chưa chốt):
- 1 Batch Vanohub  ↔ 1 CVAT Task
- 1 Job Vanohub    ↔ 1 CVAT Job
- Annotator: gán theo assignee của CVAT nếu có user Vanohub trùng username.

Trạng thái: Vanohub quản lý workflow riêng. Từ CVAT chỉ suy ra trạng thái cho các
bước TRƯỚC QC2 (annotate / QC1). Job đã ở QC2 trở đi không bị CVAT ghi đè.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from jobs.models import STAGE_STATUSES, Job, JobStatus
from projects.models import ActivityLog, Batch
from projects.notifications import notify_escalated

from .client import CvatClient

# (stage, state) của CVAT → trạng thái Vanohub.
CVAT_STATUS_MAP = {
    ("annotation", "new"): JobStatus.PENDING_ANNOTATION,
    ("annotation", "in progress"): JobStatus.ANNOTATING,
    ("annotation", "completed"): JobStatus.PENDING_QC1,
    ("validation", "new"): JobStatus.PENDING_QC1,
    ("validation", "in progress"): JobStatus.QC1_REVIEWING,
    ("validation", "rejected"): JobStatus.REWORK,
    ("validation", "completed"): JobStatus.QC1_PASSED,
    ("acceptance", "new"): JobStatus.PENDING_QC2,
    ("acceptance", "in progress"): JobStatus.PENDING_QC2,
    ("acceptance", "completed"): JobStatus.PENDING_QC2,
}
SYNCABLE_STATUSES = set(STAGE_STATUSES["annotation"] + STAGE_STATUSES["qc1"])


def _user_lookup():
    """Ánh xạ assignee CVAT → user Vanohub: ưu tiên cvat_username đã liên kết, sau đó tới username."""
    all_users = list(get_user_model().objects.all())
    lookup = {u.username: u for u in all_users}
    for u in all_users:
        if u.cvat_username:
            lookup[u.cvat_username] = u
    return lookup


def _frame_count(cvat_job):
    if cvat_job.get("frame_count"):
        return cvat_job["frame_count"]
    start, stop = cvat_job.get("start_frame"), cvat_job.get("stop_frame")
    return (stop - start + 1) if start is not None and stop is not None else 0


def _apply_cvat_state(job, cvat_job, actor):
    """Cập nhật một Job từ dữ liệu CVAT. Trả về True nếu có thay đổi."""
    stage, state = cvat_job.get("stage", ""), cvat_job.get("state", "")
    changed = job.cvat_stage != stage or job.cvat_state != state
    job.cvat_stage, job.cvat_state = stage, state
    job.frame_count = _frame_count(cvat_job)

    new_status = CVAT_STATUS_MAP.get((stage, state))
    if new_status and job.status in SYNCABLE_STATUSES and new_status != job.status:
        before = job.status
        newly_escalated = False
        if new_status == JobStatus.REWORK:
            job.rework_round += 1
            if job.rework_round > job.project.max_rework_rounds and not job.is_escalated:
                job.is_escalated = True
                newly_escalated = True
        job.status = new_status
        changed = True
        job.save()
        ActivityLog.record(
            project=job.project, actor=actor, action="job.status", target=job, job=job,
            before={"status": before}, after={"status": new_status}, note="Đồng bộ từ CVAT",
        )
        if newly_escalated:
            notify_escalated(job.project, job, actor=actor)
    return changed


def import_task_jobs(batch, task_id, actor, client=None):
    """Tạo Job Vanohub cho mọi CVAT Job của một CVAT Task. Job đã có thì cập nhật."""
    client = client or CvatClient()
    task = client.get_task(task_id)
    cvat_jobs = client.list_task_jobs(task_id)
    users = _user_lookup()
    project = batch.dataset.project
    created = updated = 0

    with transaction.atomic():
        batch.cvat_task_id = task_id
        for cvat_job in cvat_jobs:
            job = Job.objects.filter(cvat_job_id=cvat_job["id"]).first()
            if job is None:
                assignee = (cvat_job.get("assignee") or {}).get("username")
                job = Job(
                    project=project,
                    batch=batch,
                    name=f"{task.get('name', 'task')} · job {cvat_job['id']}",
                    cvat_job_id=cvat_job["id"],
                    cvat_task_id=task_id,
                    annotator=users.get(assignee),
                    deadline=batch.deadline,
                    cvat_stage=cvat_job.get("stage", ""),
                    cvat_state=cvat_job.get("state", ""),
                    frame_count=_frame_count(cvat_job),
                    status=CVAT_STATUS_MAP.get(
                        (cvat_job.get("stage"), cvat_job.get("state")), JobStatus.PENDING_ANNOTATION
                    ),
                )
                job.save()
                ActivityLog.record(project=project, actor=actor, action="job.import", target=job, job=job,
                                   note=f"Nhập từ CVAT task {task_id}")
                created += 1
            elif job.batch_id != batch.id:
                continue  # job thuộc batch khác → không động vào
            else:
                if _apply_cvat_state(job, cvat_job, actor):
                    job.save()
                    updated += 1
        batch.last_synced_at = timezone.now()
        batch.last_sync_status = Batch.SyncStatus.OK
        batch.last_sync_error = ""
        batch.save(update_fields=["cvat_task_id", "last_synced_at", "last_sync_status", "last_sync_error"])
    return {"task_name": task.get("name"), "created": created, "updated": updated, "total": len(cvat_jobs)}


def sync_batch(batch, actor, client=None, count_objects=False):
    """Đồng bộ lại trạng thái (và tuỳ chọn: số object) của các job trong batch."""
    if not batch.cvat_task_id:
        return {"updated": 0, "total": 0}
    client = client or CvatClient()
    by_id = {j["id"]: j for j in client.list_task_jobs(batch.cvat_task_id)}
    updated = 0
    with transaction.atomic():
        for job in batch.jobs.select_related("project", "batch__team").filter(cvat_job_id__isnull=False):
            cvat_job = by_id.get(job.cvat_job_id)
            if not cvat_job:
                continue
            changed = _apply_cvat_state(job, cvat_job, actor)
            if count_objects:
                count = client.count_job_objects(job.cvat_job_id)
                changed |= count != job.object_count
                job.object_count = count
            if changed:
                job.save()
                updated += 1
        batch.last_synced_at = timezone.now()
        batch.last_sync_status = Batch.SyncStatus.OK
        batch.last_sync_error = ""
        batch.save(update_fields=["last_synced_at", "last_sync_status", "last_sync_error"])
    return {"updated": updated, "total": len(by_id)}
