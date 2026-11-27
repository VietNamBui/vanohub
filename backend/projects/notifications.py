"""Helper tạo thông báo trong app (UserNotification) cho các sự kiện vận hành cốt lõi:
1. Được giao việc (assigned)
2. Bị trả sửa (rework)
3. Cần duyệt (review_needed)
4. Escalated vượt giới hạn rework (escalated)
"""

from typing import Any

from accounts.datetime_utils import format_local_datetime
from accounts.models import Role, RoleAssignment, User
from jobs.models import JobStatus
from teams.models import TeamMember

from .models import DataStatus, UserNotification

BLOCKING_QC2_STATUSES = [
    JobStatus.PENDING_ANNOTATION,
    JobStatus.ANNOTATING,
    JobStatus.REWORK,
    JobStatus.PENDING_QC1,
    JobStatus.QC1_REVIEWING,
]


def project_users_with_roles(project: Any, *roles: Any) -> list[User]:
    user_ids = (
        RoleAssignment.objects.filter(project=project, role__in=[str(r) for r in roles])
        .values_list("user_id", flat=True)
        .distinct()
    )
    return list(User.objects.filter(pk__in=user_ids, is_active=True))


def notify_assigned(
    project: Any,
    job: Any,
    recipient: Any,
    *,
    role_label: str,
    actor: Any = None,
) -> UserNotification | None:
    if not recipient or (actor and recipient.pk == actor.pk):
        return None
    if role_label == "Annotator":
        action_url = f"/projects/{project.id}/annotator/jobs/{job.id}"
    elif role_label == "QC1":
        action_url = f"/projects/{project.id}/qc1/work"
    else:
        action_url = f"/projects/{project.id}/qc2/work"
    deadline_txt = f" Hạn {format_local_datetime(job.deadline)}." if job.deadline else ""
    return UserNotification.objects.create(
        recipient=recipient,
        project=project,
        job=job,
        category=UserNotification.Category.ASSIGNED,
        title=f"Bạn được giao {job.name} ({role_label})",
        body=f"Task {job.batch.name}.{deadline_txt}",
        action_url=action_url,
    )


def notify_review_needed(
    project: Any,
    recipients: Any,
    *,
    title: str,
    body: str,
    action_url: str,
    job: Any = None,
    actor: Any = None,
) -> list[UserNotification]:
    seen: set[int] = set()
    created: list[UserNotification] = []
    for recipient in recipients:
        if not recipient or recipient.pk in seen:
            continue
        if actor and recipient.pk == actor.pk:
            continue
        seen.add(recipient.pk)
        created.append(
            UserNotification.objects.create(
                recipient=recipient,
                project=project,
                job=job,
                category=UserNotification.Category.REVIEW_NEEDED,
                title=title[:200],
                body=body,
                action_url=action_url,
                is_pinned_pending=True,
            )
        )
    return created


def notify_rework(
    project: Any,
    job: Any,
    *,
    error_count: int = 0,
    stage_label: str = "QC1",
    reason: str = "",
    actor: Any = None,
    include_qc1: bool = False,
) -> None:
    deadline_txt = f" Hạn sửa {format_local_datetime(job.deadline)}." if job.deadline else ""
    detail = f"{stage_label} ghi {error_count} lỗi." if error_count else f"{stage_label} trả sửa."
    if reason:
        detail = f"{detail} Lý do: {reason}"
    if job.annotator and job.annotator.notify_rework and (not actor or job.annotator_id != actor.pk):
        UserNotification.objects.create(
            recipient=job.annotator,
            project=project,
            job=job,
            category=UserNotification.Category.REWORK,
            title=f"{job.name} bị trả sửa (vòng {job.rework_round})",
            body=f"{detail}{deadline_txt}",
            action_url=f"/projects/{project.id}/annotator/jobs/{job.id}",
            is_pinned_pending=True,
        )
    if (
        include_qc1
        and job.qc1_reviewer
        and job.qc1_reviewer_id != job.annotator_id
        and (not actor or job.qc1_reviewer_id != actor.pk)
    ):
        UserNotification.objects.create(
            recipient=job.qc1_reviewer,
            project=project,
            job=job,
            category=UserNotification.Category.REWORK,
            title=f"{job.name} bị {stage_label} trả về Rework",
            body=detail,
            action_url=f"/projects/{project.id}/qc1/work",
        )


def notify_escalated(project: Any, job: Any, *, actor: Any = None) -> list[UserNotification]:
    """Thông báo cho PM của organization khi job vượt giới hạn số vòng rework."""
    pms = project_users_with_roles(project, Role.PROJECT_MANAGER)
    url = f"/projects/{project.id}/jobs?escalated=1"
    created: list[UserNotification] = []
    for recipient in pms:
        if actor and recipient.pk == actor.pk:
            continue
        created.append(
            UserNotification.objects.create(
                recipient=recipient,
                project=project,
                job=job,
                category=UserNotification.Category.ESCALATED,
                title=f"Escalated: {job.name} vượt giới hạn rework ({job.rework_round}/{project.max_rework_rounds})",
                body=f"Task {job.batch.name} cần PM xem xét xử lý.",
                action_url=url,
                is_pinned_pending=True,
            )
        )
    return created


def notify_batch_ready_for_qc2(project: Any, batch: Any, *, actor: Any = None) -> list[UserNotification]:
    """Nếu 100% job trong task đã qua QC1 và có job chờ xác nhận, gửi thông báo cần duyệt cho PM."""
    if batch.status != DataStatus.ACTIVE or batch.dataset.status != DataStatus.ACTIVE:
        return []
    jobs_qs = batch.jobs.all()
    if not jobs_qs.exists():
        return []
    if jobs_qs.filter(is_locked=True).exists():
        return []
    if jobs_qs.filter(status__in=BLOCKING_QC2_STATUSES).exists():
        return []
    passed_count = jobs_qs.filter(status=JobStatus.QC1_PASSED).count()
    if passed_count == 0:
        return []

    pms = project_users_with_roles(project, Role.PROJECT_MANAGER)
    return notify_review_needed(
        project,
        pms,
        title=f"Task {batch.name} sẵn sàng xác nhận chuyển QC2",
        body=f"{passed_count} job đã đạt QC1 (100% task) — cần PM xác nhận chuyển lên QC2.",
        action_url=f"/projects/{project.id}/batches",
        actor=actor,
    )


def user_team_ids(project: Any, user: Any) -> list[int]:
    return list(TeamMember.objects.filter(user=user, team__project=project).values_list("team_id", flat=True))
