"""Đồng bộ "ai đang giữ job" từ VanoHub sang assignee của CVAT job.

Quy tắc: CVAT job chỉ có MỘT assignee, nên assignee = người đang giữ job theo trạng thái trên VanoHub:
- Chờ annotate / Đang annotate / Rework → annotator
- Chờ QC1 / Đang QC1                   → người QC1
- Đạt QC1 (chờ PM xác nhận QC2)        → không động vào CVAT (_NOT_MANAGED)
- Chờ QC2 (job có mẫu QC2 pending)     → auditor QC2 của mẫu
- Các trạng thái khác (đã duyệt, đã bàn giao, chờ QC2 không lấy mẫu) → không động vào CVAT.

Người giữ job chưa liên kết CVAT → bỏ assignee bên CVAT (để người cũ không còn mở được job),
khi người đó liên kết xong thì đẩy lại. VanoHub là nơi phân công: nếu ai đó đổi assignee
trực tiếp trên CVAT, lần đồng bộ sau sẽ ghi đè.
"""

import logging
from collections.abc import Iterable
from typing import Any

from django.db import transaction
from django.db.models import Prefetch, Q, QuerySet

from jobs.models import STAGE_STATUSES, Job, JobStatus

from .client import CvatClient, CvatError

logger = logging.getLogger(__name__)

_NOT_MANAGED = object()
_ACTIVE_QC1_STATUSES: list[str] = [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING]


def pending_samples_prefetch() -> Prefetch:
    """Prefetch lượt QC2 đang chờ (in_progress + pending) kèm tài khoản CVAT để tránh N+1."""
    from quality.models import AuditSample

    return Prefetch(
        "audit_samples",
        queryset=AuditSample.objects.filter(audit__status="in_progress", result="pending")
        .select_related("auditor__cvat_account")
        .order_by("-id"),
        to_attr="_pending_samples",
    )


def current_holder(job: Job) -> Any:
    """User đang giữ job, None nếu chưa giao, _NOT_MANAGED nếu trạng thái này không đồng bộ."""
    if job.status == JobStatus.QC1_PASSED:
        return _NOT_MANAGED
    if job.status in STAGE_STATUSES["annotation"]:
        return job.annotator
    if job.status in _ACTIVE_QC1_STATUSES:
        return job.qc1_reviewer
    if job.status == JobStatus.PENDING_QC2:
        prefetched = getattr(job, "_pending_samples", None)
        if prefetched is not None:
            sample = prefetched[0] if prefetched else None
        else:
            sample = (
                job.audit_samples.filter(audit__status="in_progress", result="pending")
                .select_related("auditor__cvat_account")
                .order_by("-id")
                .first()
            )
        return sample.auditor if sample else _NOT_MANAGED
    return _NOT_MANAGED


def _cvat_user_id(user: Any) -> int | None:
    account = getattr(user, "cvat_account", None) if user else None
    return account.cvat_user_id if account else None


class _OrgMembers:
    """Bảo đảm người được giao job là thành viên CVAT organization của job (nếu không, họ không thấy job).

    Chưa là thành viên → mời bằng email với vai trò worker; CVAT tự chấp nhận khi
    ORG_INVITATION_CONFIRM = "No" (mặc định) và email thuộc một tài khoản có sẵn.
    Nhớ danh sách thành viên theo organization trong một lượt đẩy để không gọi CVAT lặp lại.
    """

    def __init__(self, client: Any) -> None:
        self.client = client
        self.members: dict[int, dict[int | None, bool]] = {}  # org_id → {cvat_user_id: is_active}

    def ensure(self, project: Any, cvat_user_id: int) -> str | None:
        """Trả về None nếu ổn, hoặc câu cảnh báo nếu không tự thêm được."""
        if not project.cvat_org_id or not project.cvat_org_slug:
            return None
        members = self.members.get(project.cvat_org_id)
        if members is None:
            members = {
                (m.get("user") or {}).get("id"): bool(m.get("is_active", True))
                for m in self.client.list_memberships(project.cvat_org_id)
            }
            self.members[project.cvat_org_id] = members
        if members.get(cvat_user_id):
            return None
        user = self.client.get_user(cvat_user_id)
        name = user.get("username", f"#{cvat_user_id}")
        if cvat_user_id in members:
            return f"{name} có lời mời vào organization {project.cvat_org_slug} nhưng chưa chấp nhận."
        if not user.get("email"):
            return (
                f"Tài khoản CVAT {name} chưa có email nên không tự mời vào organization "
                f"{project.cvat_org_slug} được — thêm tay trên CVAT."
            )
        self.client.invite_to_org(project.cvat_org_slug, user["email"], role="worker")
        members[cvat_user_id] = True
        return None


def push_assignees(jobs: Iterable[Job], client: Any = None) -> dict[str, Any]:
    """Đặt assignee CVAT cho các job (chỉ gọi CVAT khi khác giá trị đang có).
    Trước khi giao, tự thêm người nhận vào CVAT organization của job nếu họ chưa là thành viên.

    Trả về {"pushed": số job đã cập nhật, "waiting": số job mà người giữ chưa liên kết CVAT,
            "warnings": cảnh báo không tự thêm được vào organization}.
    Lỗi CVAT khi đặt assignee được ném ra (CvatError) để nơi gọi quyết định hiển thị hay chỉ ghi log.
    """
    pushed = waiting = 0
    warnings: list[str] = []
    orgs: _OrgMembers | None = None
    for job in jobs:
        if not job.cvat_job_id:
            continue
        holder = current_holder(job)
        if holder is _NOT_MANAGED:
            continue
        target = _cvat_user_id(holder)
        if holder is not None and target is None:
            waiting += 1
        if job.cvat_assignee_id == target:
            continue
        client = client or CvatClient()
        if target is not None:
            orgs = orgs or _OrgMembers(client)
            try:
                warning = orgs.ensure(job.project, target)
            except CvatError as exc:  # không mời được vẫn giao job; chỉ cảnh báo
                warning = f"Không tự thêm được vào organization: {exc}"
            if warning and warning not in warnings:
                warnings.append(warning)
        client.set_job_assignee(job.cvat_job_id, target)
        job.cvat_assignee_id = target
        job.save(update_fields=["cvat_assignee_id"])
        pushed += 1
    return {"pushed": pushed, "waiting": waiting, "warnings": warnings}


def _jobs(job_ids: Any) -> QuerySet[Job]:
    return (
        Job.objects.filter(pk__in=job_ids, cvat_job_id__isnull=False)
        .select_related("project", "annotator__cvat_account", "qc1_reviewer__cvat_account")
        .prefetch_related(pending_samples_prefetch())
    )


def push_assignees_quietly(job_ids: Iterable[int]) -> None:
    ids = list(job_ids)
    try:
        result = push_assignees(_jobs(ids))
    except CvatError as exc:
        # Việc giao trên VanoHub vẫn giữ nguyên; lần đồng bộ / liên kết sau sẽ thử lại.
        logger.warning("Không đẩy được assignee sang CVAT cho job %s: %s", ids, exc)
        return
    for warning in result["warnings"]:
        logger.warning("Job %s: %s", ids, warning)


def schedule_assignee_push(job_ids: Iterable[int]) -> None:
    """Gọi sau khi đổi người giữ job. Chạy khi transaction commit xong (không giữ khoá DB lúc gọi HTTP)."""
    ids = list(job_ids)
    if ids:
        transaction.on_commit(lambda: push_assignees_quietly(ids))


def jobs_held_by(user: Any) -> QuerySet[Job]:
    """Các job có CVAT mà user đang (hoặc có thể đang) giữ — dùng khi user liên kết / huỷ liên kết."""
    return _jobs(
        Job.objects.filter(
            Q(annotator=user, status__in=STAGE_STATUSES["annotation"])
            | Q(qc1_reviewer=user, status__in=_ACTIVE_QC1_STATUSES)
            | Q(
                status=JobStatus.PENDING_QC2,
                audit_samples__auditor=user,
                audit_samples__audit__status="in_progress",
                audit_samples__result="pending",
            )
        ).values("pk")
    ).distinct()
