"""Đồng bộ cấu trúc và trạng thái từ CVAT về VanoHub.

ÁNH XẠ (chốt 2026-11-25) — xem thêm docstring của projects.models.Project:
    CVAT Organization → Project (model)   — "Organization" trên giao diện
    CVAT Project      → Dataset (model)   — "Project"
    CVAT Task         → Batch (model)     — "Task"
    CVAT Job          → Job               (chỉ job loại "annotation"; bỏ Ground Truth / consensus)
Project CVAT ngoài organization (Personal workspace) không đưa lên VanoHub.

Thành viên organization (đã liên kết VanoHub): Owner / Maintainer → PM; người khác → Annotator
(nếu chưa có vai trò nào). ĐỀ XUẤT: rời organization trên CVAT KHÔNG tự gỡ vai trò trên VanoHub.

Trạng thái job: VanoHub quản lý workflow riêng. Từ CVAT chỉ suy ra trạng thái cho các bước
TRƯỚC QC2 (annotate / QC1). Job vào Chờ QC2 → tạo lượt QC2 kiểm % frame (quality/qc2.py).
"""

from django.db import transaction
from django.utils import timezone

from accounts.models import Role, RoleAssignment
from jobs.models import STAGE_STATUSES, Job, JobStatus
from projects.models import ActivityLog, Batch, Dataset, Project
from quality.qc2 import ensure_qc2_sample

from .assignee import push_assignees
from .client import CvatClient, CvatError
from .models import CvatAccount

# (stage, state) của CVAT → trạng thái Vanohub đề xuất.
CVAT_STATUS_MAP = {
    ("annotation", "new"): JobStatus.PENDING_ANNOTATION,
    ("annotation", "in progress"): JobStatus.ANNOTATING,
    ("annotation", "completed"): JobStatus.PENDING_QC1,
    ("validation", "new"): JobStatus.PENDING_QC1,
    ("validation", "in progress"): JobStatus.QC1_REVIEWING,
    ("validation", "rejected"): JobStatus.REWORK,
    ("validation", "completed"): JobStatus.PENDING_QC2,
    ("acceptance", "new"): JobStatus.PENDING_QC2,
    ("acceptance", "in progress"): JobStatus.PENDING_QC2,
    ("acceptance", "completed"): JobStatus.PENDING_QC2,
}
SYNCABLE_STATUSES = set(STAGE_STATUSES["annotation"] + STAGE_STATUSES["qc1"])
PM_ORG_ROLES = {"owner", "maintainer"}


def _frame_count(cvat_job):
    if cvat_job.get("frame_count"):
        return cvat_job["frame_count"]
    start, stop = cvat_job.get("start_frame"), cvat_job.get("stop_frame")
    return (stop - start + 1) if start is not None and stop is not None else 0


def _user_id(obj):
    """ID user CVAT trong trường assignee/owner (CVAT trả object {"id", "username"} hoặc null)."""
    return (obj or {}).get("id")


def _cvat_assignee_id(cvat_job):
    return _user_id(cvat_job.get("assignee"))


def _linked_users():
    return {a.cvat_user_id: a.user for a in CvatAccount.objects.select_related("user")}


# ---------------------------------------------------------------- Organization

def sync_organizations(actor=None, client=None):
    """Tạo / cập nhật "Organization" VanoHub từ CVAT organization + gán vai trò theo thành viên.

    Chỉ tạo khi organization có ít nhất một Owner / Maintainer đã liên kết VanoHub (để có PM).
    """
    client = client or CvatClient()
    linked = _linked_users()
    created, updated, pm_added, members_added, waiting = [], [], [], [], []
    for org in client.list_organizations():
        memberships = [m for m in client.list_memberships(org["id"]) if m.get("is_active", True)]
        pms = [linked[_user_id(m.get("user"))] for m in memberships
               if m.get("role") in PM_ORG_ROLES and _user_id(m.get("user")) in linked]
        project = Project.objects.filter(cvat_org_id=org["id"]).first()
        name = org.get("name") or org.get("slug")
        if project is None and not pms:
            waiting.append({"cvat_org_id": org["id"], "name": name,
                            "reason": "Chưa có Owner / Maintainer nào liên kết VanoHub"})
            continue
        with transaction.atomic():
            if project is None:
                project = Project.objects.create(name=name, cvat_org_id=org["id"], cvat_org_slug=org.get("slug", ""),
                                                 created_by=actor)
                created.append(name)
            elif project.name != name or project.cvat_org_slug != org.get("slug", ""):
                project.name, project.cvat_org_slug = name, org.get("slug", "")
                project.save(update_fields=["name", "cvat_org_slug", "updated_at"])
                updated.append(name)
            for membership in memberships:
                user = linked.get(_user_id(membership.get("user")))
                if user is None:
                    continue
                if membership.get("role") in PM_ORG_ROLES:
                    _, added = RoleAssignment.objects.get_or_create(
                        user=user, role=Role.PROJECT_MANAGER, project=project, defaults={"granted_by": actor})
                    if added:
                        pm_added.append({"organization": name, "user": user.username})
                        ActivityLog.record(project=project, actor=actor, action="project.assign_pm", target=user,
                                           note=f"Theo vai trò {membership['role']} trong CVAT organization")
                elif not RoleAssignment.objects.filter(user=user, project=project).exists():
                    RoleAssignment.objects.create(user=user, role=Role.ANNOTATOR, project=project, granted_by=actor)
                    members_added.append({"organization": name, "user": user.username})
        if project.cvat_synced_at is None:
            # Organization mới → kéo luôn project / task / job, PM không phải bấm thêm.
            try:
                sync_organization(project, actor, client=client)
            except CvatError:
                pass  # PM bấm "Đồng bộ CVAT" để thử lại
    return {"created": created, "updated": updated, "pm_added": pm_added,
            "members_added": members_added, "waiting": waiting}


def sync_organizations_quietly(actor=None):
    """Như sync_organizations nhưng không ném lỗi (dùng sau khi liên kết CVAT)."""
    try:
        return sync_organizations(actor)
    except CvatError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------- Project / Task / Job

def _apply_cvat_state(job, cvat_job, actor):
    """Cập nhật một Job từ dữ liệu CVAT. Trả về True nếu có thay đổi."""
    stage, state = cvat_job.get("stage", ""), cvat_job.get("state", "")
    assignee = _cvat_assignee_id(cvat_job)
    changed = job.cvat_stage != stage or job.cvat_state != state or job.cvat_assignee_id != assignee
    job.cvat_stage, job.cvat_state, job.cvat_assignee_id = stage, state, assignee
    job.frame_count = _frame_count(cvat_job)
    job.cvat_start_frame = cvat_job.get("start_frame") or 0

    new_status = CVAT_STATUS_MAP.get((stage, state))
    if new_status and job.status in SYNCABLE_STATUSES and new_status != job.status:
        before = job.status
        if new_status == JobStatus.REWORK:
            job.rework_round += 1
            if job.rework_round > job.project.max_rework_rounds:
                job.is_escalated = True
        job.status = new_status
        changed = True
        job.save()
        ActivityLog.record(
            project=job.project, actor=actor, action="job.status", target=job, job=job,
            before={"status": before}, after={"status": new_status}, note="Đồng bộ từ CVAT",
        )
    return changed


def _new_job(project, dataset, task, cvat_job, linked):
    return Job(
        project=project, dataset=dataset, batch=task,
        name=f"{task.name} · job {cvat_job['id']}",
        cvat_job_id=cvat_job["id"], cvat_task_id=task.cvat_task_id,
        cvat_start_frame=cvat_job.get("start_frame") or 0,
        annotator=linked.get(_cvat_assignee_id(cvat_job)),
        deadline=task.deadline,
        cvat_stage=cvat_job.get("stage", ""), cvat_state=cvat_job.get("state", ""),
        cvat_assignee_id=_cvat_assignee_id(cvat_job),
        frame_count=_frame_count(cvat_job),
        status=CVAT_STATUS_MAP.get((cvat_job.get("stage"), cvat_job.get("state")), JobStatus.PENDING_ANNOTATION),
    )


def sync_organization(project, actor, client=None, count_objects=False):
    """Đồng bộ một organization: CVAT project → Dataset, task → Batch, job → Job."""
    if not project.cvat_org_id:
        raise CvatError("Organization này chưa gắn với CVAT organization.")
    client = client or CvatClient()
    linked = _linked_users()
    now = timezone.now()
    summary = {"projects": 0, "projects_created": 0, "tasks": 0, "tasks_created": 0,
               "jobs_created": 0, "jobs_updated": 0}

    with transaction.atomic():
        for cvat_project in client.list_org_projects(project.cvat_org_id):
            summary["projects"] += 1
            dataset = Dataset.objects.filter(cvat_project_id=cvat_project["id"]).first()
            name = cvat_project.get("name") or f"Project {cvat_project['id']}"
            if dataset is None:
                dataset = Dataset.objects.create(project=project, name=name, cvat_project_id=cvat_project["id"],
                                                 created_by=actor)
                summary["projects_created"] += 1
            elif dataset.project_id != project.id:
                continue  # project đã thuộc organization khác trên VanoHub → không động vào
            dataset.name = name

            for cvat_task in client.list_project_tasks(cvat_project["id"]):
                summary["tasks"] += 1
                task = Batch.objects.filter(cvat_task_id=cvat_task["id"]).first()
                task_name = cvat_task.get("name") or f"Task {cvat_task['id']}"
                if task is None:
                    task = Batch.objects.create(project=project, dataset=dataset, name=task_name,
                                                cvat_task_id=cvat_task["id"], created_by=actor)
                    summary["tasks_created"] += 1
                elif task.project_id != project.id:
                    continue
                task.name, task.dataset, task.last_synced_at = task_name, dataset, now
                task.save()

                for cvat_job in client.list_task_jobs(cvat_task["id"]):
                    if cvat_job.get("type", "annotation") != "annotation":
                        continue  # bỏ Ground Truth / consensus job
                    job = Job.objects.filter(cvat_job_id=cvat_job["id"]).select_related("project").first()
                    if job is None:
                        job = _new_job(project, dataset, task, cvat_job, linked)
                        job.save()
                        summary["jobs_created"] += 1
                    elif job.batch_id == task.id:
                        changed = _apply_cvat_state(job, cvat_job, actor)
                        if count_objects:
                            count = client.count_job_objects(job.cvat_job_id)
                            changed |= count != job.object_count
                            job.object_count = count
                        if changed:
                            job.save()
                            summary["jobs_updated"] += 1
                    ensure_qc2_sample(job)
            dataset.last_synced_at = now
            dataset.save()
        project.cvat_synced_at = now
        project.save(update_fields=["cvat_synced_at", "updated_at"])

    jobs = project.jobs.filter(cvat_job_id__isnull=False).select_related(
        "project", "annotator__cvat_account", "qc1_reviewer__cvat_account"
    )
    try:
        pushed = push_assignees(jobs, client)
        summary.update(assignees_pushed=pushed["pushed"], waiting_link=pushed["waiting"],
                       membership_warnings=pushed["warnings"])
    except CvatError as exc:  # đẩy assignee lỗi không làm hỏng kết quả đồng bộ
        summary.update(assignees_pushed=0, waiting_link=0, assignee_error=str(exc))
    return summary


def dataset_labels(dataset, client=None):
    """Bộ nhãn của một CVAT project (Dataset) — chỉ đọc."""
    client = client or CvatClient()
    return [
        {"id": label["id"], "name": label["name"], "color": label.get("color"), "type": label.get("type")}
        for label in client.list_project_labels(dataset.cvat_project_id)
    ]
