"""Helper tạo thông báo trong app (UserNotification) cho đủ 4 sự kiện cốt lõi MVP:
1. Được giao việc (assigned)
2. Bị trả sửa (rework)
3. Cần duyệt (review_needed)
4. Escalated vượt giới hạn rework (escalated)
"""

from django.utils import timezone

from accounts.models import Role, RoleAssignment, User
from jobs.models import JobStatus
from teams.models import TeamMember

from .models import UserNotification


def project_users_with_roles(project, *roles):
    user_ids = (
        RoleAssignment.objects.filter(project=project, role__in=roles)
        .values_list("user_id", flat=True)
        .distinct()
    )
    return list(User.objects.filter(pk__in=user_ids, is_active=True))


def notify_assigned(project, job, recipient, *, role_label, actor=None):
    if not recipient or (actor and recipient.pk == actor.pk):
        return None
    if role_label == "Annotator":
        action_url = f"/projects/{project.id}/annotator/jobs/{job.id}"
    elif role_label == "QC1":
        action_url = f"/projects/{project.id}/qc1/work"
    else:
        action_url = f"/projects/{project.id}/qc2/work"
    deadline_txt = (
        f" Hạn {timezone.localtime(job.deadline).strftime('%d/%m %H:%M')}." if job.deadline else ""
    )
    return UserNotification.objects.create(
        recipient=recipient,
        project=project,
        job=job,
        category=UserNotification.Category.ASSIGNED,
        title=f"Bạn được giao {job.name} ({role_label})",
        body=f"Batch {job.batch.name}.{deadline_txt}",
        action_url=action_url,
    )


def notify_review_needed(project, recipients, *, title, body, action_url, job=None, actor=None):
    seen = set()
    created = []
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


def notify_rework(project, job, *, error_count=0, stage_label="QC1", reason="", actor=None, include_qc1=False):
    deadline_txt = (
        f" Hạn sửa {timezone.localtime(job.deadline).strftime('%d/%m %H:%M')}." if job.deadline else ""
    )
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


def notify_escalated(project, job, *, actor=None):
    """Thông báo cho PM dự án khi job vượt giới hạn số vòng rework."""
    pms = project_users_with_roles(project, Role.PROJECT_MANAGER)
    url = f"/projects/{project.id}/jobs?escalated=1"
    created = []
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
                body=f"Batch {job.batch.name} cần PM xem xét xử lý.",
                action_url=url,
                is_pinned_pending=True,
            )
        )
    return created


def notify_batch_ready_for_qc2(project, batch, *, actor=None):
    """Nếu 100% job trong batch đã qua QC1 và có job chờ xác nhận, gửi thông báo cần duyệt cho PM."""
    blocking = [
        JobStatus.PENDING_ANNOTATION,
        JobStatus.ANNOTATING,
        JobStatus.REWORK,
        JobStatus.PENDING_QC1,
        JobStatus.QC1_REVIEWING,
    ]
    jobs_qs = batch.jobs.all()
    if not jobs_qs.exists():
        return []
    if jobs_qs.filter(status__in=blocking).exists():
        return []
    passed_count = jobs_qs.filter(status=JobStatus.QC1_PASSED).count()
    if passed_count == 0:
        return []

    pms = project_users_with_roles(project, Role.PROJECT_MANAGER)
    return notify_review_needed(
        project,
        pms,
        title=f"Batch {batch.name} sẵn sàng xác nhận chuyển QC2",
        body=f"{passed_count} job đã đạt QC1 (100% batch) — cần PM xác nhận chuyển lên QC2.",
        action_url=f"/projects/{project.id}/batches",
        actor=actor,
    )


def user_team_ids(project, user):
    return list(TeamMember.objects.filter(user=user, team__project=project).values_list("team_id", flat=True))
