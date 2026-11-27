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

from contextlib import suppress

from accounts.models import Role, RoleAssignment
from django.db import transaction
from django.utils import timezone
from jobs.models import Job, JobStatus
from projects.models import ActivityLog, Batch, Dataset, DataStatus, Project
from quality.models import seed_default_error_categories
from quality.qc2 import ensure_qc2_sample

from .assignee import pending_samples_prefetch, push_assignees
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
            seed_default_error_categories(project)
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
            # PM bấm "Đồng bộ CVAT" để thử lại nếu CVAT lỗi tạm thời.
            with suppress(CvatError):
                sync_organization(project, actor, client=client)
    return {"created": created, "updated": updated, "pm_added": pm_added,
            "members_added": members_added, "waiting": waiting}


def sync_organizations_quietly(actor=None):
    """Như sync_organizations nhưng không ném lỗi (dùng sau khi liên kết CVAT)."""
    try:
        return sync_organizations(actor)
    except CvatError as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------- Project / Task / Job

def _is_workflow_frozen(job):
    return (
        job.is_locked
        or job.is_escalated
        or job.batch.status != DataStatus.ACTIVE
        or job.dataset.status != DataStatus.ACTIVE
    )


def _next_cvat_status(job, stage, state, prev_stage, prev_state):
    """Chỉ cho phép CVAT đẩy tiến độ ban đầu một chiều, không ghi đè workflow VanoHub."""
    if _is_workflow_frozen(job):
        return None
    mapped = CVAT_STATUS_MAP.get((stage, state))
    if not mapped or mapped == job.status:
        return None
    if job.status == JobStatus.PENDING_ANNOTATION:
        if mapped == JobStatus.ANNOTATING:
            return JobStatus.ANNOTATING
        if job.rework_round == 0 and mapped == JobStatus.PENDING_QC1:
            return JobStatus.PENDING_QC1
        return None
    if job.status == JobStatus.ANNOTATING:
        if job.rework_round == 0 and mapped == JobStatus.PENDING_QC1:
            return JobStatus.PENDING_QC1
        return None
    if (
        job.status == JobStatus.QC1_REVIEWING
        and (stage, state) == ("validation", "rejected")
        and (prev_stage, prev_state) != ("validation", "rejected")
    ):
        return JobStatus.REWORK
    return None


def _apply_cvat_state(job, cvat_job, actor, object_count=None):
    """Cập nhật một Job từ dữ liệu CVAT. Trả về True nếu có thay đổi."""
    stage, state = cvat_job.get("stage", ""), cvat_job.get("state", "")
    assignee = _cvat_assignee_id(cvat_job)
    frame_count = _frame_count(cvat_job)
    start_frame = cvat_job.get("start_frame") or 0
    prev_stage, prev_state = job.cvat_stage, job.cvat_state

    changed = (
        prev_stage != stage
        or prev_state != state
        or job.cvat_assignee_id != assignee
        or job.frame_count != frame_count
        or job.cvat_start_frame != start_frame
    )
    job.cvat_stage, job.cvat_state, job.cvat_assignee_id = stage, state, assignee
    job.frame_count = frame_count
    job.cvat_start_frame = start_frame

    if object_count is not None and object_count != job.object_count:
        job.object_count = object_count
        changed = True

    new_status = _next_cvat_status(job, stage, state, prev_stage, prev_state)
    if new_status:
        before = job.status
        if new_status == JobStatus.REWORK:
            job.rework_round += 1
            job.total_rework_rounds += 1
            if job.rework_round > job.project.max_rework_rounds:
                job.is_escalated = True
        job.status = new_status
        changed = True
        job.save()
        ActivityLog.record(
            project=job.project,
            actor=actor,
            action="job.status",
            target=job,
            job=job,
            before={"status": before},
            after={"status": new_status},
            note="Đồng bộ từ CVAT",
        )
    elif changed:
        job.save()
    return changed


def _new_job(project, dataset, task, cvat_job, linked, annotator_ids, object_count=None):
    assignee_id = _cvat_assignee_id(cvat_job)
    candidate = linked.get(assignee_id)
    annotator = candidate if candidate and candidate.pk in annotator_ids else None
    return Job(
        project=project,
        dataset=dataset,
        batch=task,
        name=f"{task.name} · job {cvat_job['id']}",
        cvat_job_id=cvat_job["id"],
        cvat_task_id=task.cvat_task_id,
        cvat_start_frame=cvat_job.get("start_frame") or 0,
        annotator=annotator,
        deadline=task.deadline,
        cvat_stage=cvat_job.get("stage", ""),
        cvat_state=cvat_job.get("state", ""),
        cvat_assignee_id=assignee_id,
        frame_count=_frame_count(cvat_job),
        object_count=object_count or 0,
        status=CVAT_STATUS_MAP.get((cvat_job.get("stage"), cvat_job.get("state")), JobStatus.PENDING_ANNOTATION),
    )


def _fetch_remote_org_tree(project, client, count_objects=False):
    """Kéo toàn bộ dữ liệu project/task/job (+ object_count) từ CVAT NGOÀI transaction DB."""
    cvat_projects = client.list_org_projects(project.cvat_org_id)
    foreign_project_ids = set(
        Dataset.objects.filter(cvat_project_id__in=[p["id"] for p in cvat_projects])
        .exclude(project=project)
        .values_list("cvat_project_id", flat=True)
    )
    remote_projects = []
    for cvat_project in cvat_projects:
        if cvat_project["id"] in foreign_project_ids:
            remote_projects.append((cvat_project, None))
            continue
        cvat_tasks = client.list_project_tasks(cvat_project["id"])
        foreign_task_ids = set(
            Batch.objects.filter(cvat_task_id__in=[t["id"] for t in cvat_tasks])
            .exclude(project=project)
            .values_list("cvat_task_id", flat=True)
        )
        remote_tasks = []
        for cvat_task in cvat_tasks:
            if cvat_task["id"] in foreign_task_ids:
                remote_tasks.append((cvat_task, None))
                continue
            remote_jobs = []
            for cvat_job in client.list_task_jobs(cvat_task["id"]):
                if cvat_job.get("type", "annotation") != "annotation":
                    continue  # bỏ Ground Truth / consensus job
                obj_count = client.count_job_objects(cvat_job["id"]) if count_objects else None
                remote_jobs.append((cvat_job, obj_count))
            remote_tasks.append((cvat_task, remote_jobs))
        remote_projects.append((cvat_project, remote_tasks))
    return remote_projects


def sync_organization(project, actor, client=None, count_objects=False):
    """Đồng bộ một organization: CVAT project → Dataset, task → Batch, job → Job."""
    if not project.cvat_org_id:
        raise CvatError("Organization này chưa gắn với CVAT organization.")
    client = client or CvatClient()
    remote_projects = _fetch_remote_org_tree(project, client, count_objects=count_objects)
    linked = _linked_users()
    annotator_ids = set(
        RoleAssignment.objects.filter(project=project, role=Role.ANNOTATOR).values_list("user_id", flat=True)
    )
    now = timezone.now()
    summary = {"projects": 0, "projects_created": 0, "tasks": 0, "tasks_created": 0,
               "jobs_created": 0, "jobs_updated": 0}

    with transaction.atomic():
        for cvat_project, remote_tasks in remote_projects:
            summary["projects"] += 1
            if remote_tasks is None:
                continue  # project đã thuộc organization khác trên VanoHub → không động vào
            dataset = Dataset.objects.filter(cvat_project_id=cvat_project["id"]).first()
            name = cvat_project.get("name") or f"Project {cvat_project['id']}"
            if dataset is None:
                dataset = Dataset.objects.create(
                    project=project, name=name, cvat_project_id=cvat_project["id"], created_by=actor
                )
                summary["projects_created"] += 1
            elif dataset.project_id != project.id:
                continue
            dataset.name = name

            for cvat_task, remote_jobs in remote_tasks:
                summary["tasks"] += 1
                if remote_jobs is None:
                    continue
                task = Batch.objects.filter(cvat_task_id=cvat_task["id"]).first()
                task_name = cvat_task.get("name") or f"Task {cvat_task['id']}"
                if task is None:
                    task = Batch.objects.create(
                        project=project,
                        dataset=dataset,
                        name=task_name,
                        cvat_task_id=cvat_task["id"],
                        created_by=actor,
                    )
                    summary["tasks_created"] += 1
                elif task.project_id != project.id:
                    continue
                task.name, task.dataset, task.last_synced_at = task_name, dataset, now
                task.save()

                for cvat_job, obj_count in remote_jobs:
                    job = (
                        Job.objects.select_for_update(of=("self",))
                        .select_related("project", "batch", "dataset")
                        .filter(cvat_job_id=cvat_job["id"])
                        .first()
                    )
                    if job is None:
                        job = _new_job(
                            project, dataset, task, cvat_job, linked, annotator_ids, object_count=obj_count
                        )
                        job.save()
                        summary["jobs_created"] += 1
                    elif job.batch_id == task.id and _apply_cvat_state(
                        job, cvat_job, actor, object_count=obj_count
                    ):
                        summary["jobs_updated"] += 1
                    if not _is_workflow_frozen(job):
                        ensure_qc2_sample(job)
            dataset.last_synced_at = now
            dataset.save()
        project.cvat_synced_at = now
        project.save(update_fields=["cvat_synced_at", "updated_at"])

    jobs = (
        project.jobs.filter(cvat_job_id__isnull=False)
        .select_related("project", "annotator__cvat_account", "qc1_reviewer__cvat_account")
        .prefetch_related(pending_samples_prefetch())
    )
    try:
        pushed = push_assignees(jobs, client)
        summary.update(
            assignees_pushed=pushed["pushed"], waiting_link=pushed["waiting"], membership_warnings=pushed["warnings"]
        )
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
