"""Đồng bộ "ai đang giữ job" từ VanoHub sang assignee của CVAT job qua outbox bền vững.

Quy tắc: CVAT job chỉ có MỘT assignee, nên assignee = người đang giữ job theo trạng thái trên VanoHub:
- Chờ annotate / Đang annotate / Rework → annotator
- Chờ QC1 / Đang QC1                   → người QC1
- Chờ QC2 (job có mẫu QC2 pending)     → auditor QC2 của mẫu
- Đạt QC1 / Đã duyệt / Đã bàn giao     → bỏ assignee trên CVAT (None) để người kiểm cũ không còn giữ job.

Người giữ job chưa liên kết CVAT → bỏ assignee bên CVAT (None), khi người đó liên kết xong thì đẩy lại.
"""

import logging
from collections.abc import Iterable
from contextlib import suppress
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

from jobs.models import STAGE_STATUSES, Job, JobStatus
from projects.models import ActivityLog

from .client import CvatClient, CvatError
from .models import CvatAssigneeOutbox

logger = logging.getLogger(__name__)

_ACTIVE_QC1_STATUSES: list[str] = [JobStatus.PENDING_QC1, JobStatus.QC1_REVIEWING]
_OUTBOX_ADVISORY_NS = 0x56484F42
_OUTBOX_ADVISORY_KEY = 1
_STALE_PROCESSING_MINUTES = 5
_DEFAULT_MAX_ATTEMPTS = 10


def _try_advisory_lock(namespace: int, key: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [namespace, key & 0x7FFFFFFF])
        row = cursor.fetchone()
    return bool(row and row[0])


def _release_advisory_lock(namespace: int, key: int) -> None:
    if connection.needs_rollback:
        return
    with suppress(DatabaseError), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [namespace, key & 0x7FFFFFFF])


def _close_quietly(client: Any) -> None:
    close_fn = getattr(client, "close", None)
    if callable(close_fn):
        close_fn()


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
    """User đang giữ job, hoặc None nếu chưa giao / đã rời stage cần giữ job trên CVAT."""
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
        return sample.auditor if sample else None
    return None


def _cvat_user_id(user: Any) -> int | None:
    account = getattr(user, "cvat_account", None) if user else None
    return account.cvat_user_id if account else None


class _OrgMembers:
    """Bảo đảm người được giao job là thành viên CVAT organization của job (nếu không, họ không thấy job).

    Chưa là thành viên → mời bằng email với vai trò worker; nhớ danh sách thành viên và các lời mời
    đã gửi theo organization để callers ghi ActivityLog trong transaction sau khi gọi HTTP.
    """

    def __init__(self, client: Any) -> None:
        self.client = client
        self.members: dict[int, dict[int | None, bool]] = {}  # org_id → {cvat_user_id: is_active}
        self._invite_events: list[tuple[Any, int, str]] = []

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
        self._invite_events.append((project, cvat_user_id, str(user["email"])))
        return None

    def pop_invite_events(self, project_id: int) -> list[tuple[Any, int, str]]:
        matched = [ev for ev in self._invite_events if ev[0].pk == project_id]
        if matched:
            self._invite_events = [ev for ev in self._invite_events if ev[0].pk != project_id]
        return matched


def _jobs(job_ids: Any) -> QuerySet[Job]:
    return (
        Job.objects.filter(pk__in=job_ids, cvat_job_id__isnull=False)
        .select_related("project", "annotator__cvat_account", "qc1_reviewer__cvat_account")
        .prefetch_related(pending_samples_prefetch())
    )


def _upsert_pending_outbox(job: Job, holder: Any, target: int | None, now: Any) -> None:
    if job.cvat_job_id is None:
        return
    existing = (
        CvatAssigneeOutbox.objects.select_for_update()
        .filter(job=job, status=CvatAssigneeOutbox.Status.PENDING)
        .first()
    )
    if existing is not None:
        existing.cvat_job_id = job.cvat_job_id
        existing.project_id = job.project_id
        existing.target_holder = holder
        existing.target_cvat_user_id = target
        existing.next_retry_at = now
        existing.last_error = ""
        existing.save(
            update_fields=[
                "cvat_job_id",
                "project",
                "target_holder",
                "target_cvat_user_id",
                "next_retry_at",
                "last_error",
                "updated_at",
            ]
        )
        return
    try:
        with transaction.atomic():
            CvatAssigneeOutbox.objects.create(
                project_id=job.project_id,
                job=job,
                cvat_job_id=job.cvat_job_id,
                target_holder=holder,
                target_cvat_user_id=target,
                status=CvatAssigneeOutbox.Status.PENDING,
                next_retry_at=now,
            )
    except IntegrityError:
        existing = (
            CvatAssigneeOutbox.objects.select_for_update()
            .filter(job=job, status=CvatAssigneeOutbox.Status.PENDING)
            .first()
        )
        if existing is not None:
            existing.cvat_job_id = job.cvat_job_id
            existing.target_holder = holder
            existing.target_cvat_user_id = target
            existing.next_retry_at = now
            existing.last_error = ""
            existing.save(
                update_fields=[
                    "cvat_job_id",
                    "target_holder",
                    "target_cvat_user_id",
                    "next_retry_at",
                    "last_error",
                    "updated_at",
                ]
            )


def enqueue_assignee_push(job_ids: Iterable[int]) -> int:
    """Ghi nhận hoặc cập nhật hàng đợi outbox đẩy assignee CVAT bên trong transaction hiện hành."""
    ids = sorted({jid for jid in job_ids if isinstance(jid, int) and not isinstance(jid, bool) and jid > 0})
    if not ids:
        return 0
    now = timezone.now()
    count = 0
    with transaction.atomic():
        jobs = list(_jobs(ids).order_by("id"))
        if not jobs:
            return 0
        pending_by_job = {
            row.job_id: row
            for row in CvatAssigneeOutbox.objects.select_for_update()
            .filter(job_id__in=[j.pk for j in jobs], status=CvatAssigneeOutbox.Status.PENDING)
        }
        for job in jobs:
            if job.cvat_job_id is None:
                continue
            holder = current_holder(job)
            target = _cvat_user_id(holder)
            existing = pending_by_job.get(job.pk)
            if job.cvat_assignee_id == target:
                if existing is not None:
                    existing.status = CvatAssigneeOutbox.Status.DONE
                    existing.target_holder = holder
                    existing.target_cvat_user_id = target
                    existing.last_error = ""
                    existing.save(
                        update_fields=[
                            "status",
                            "target_holder",
                            "target_cvat_user_id",
                            "last_error",
                            "updated_at",
                        ]
                    )
                continue
            _upsert_pending_outbox(job, holder, target, now)
            count += 1
    return count


def _record_invite_logs(orgs: _OrgMembers | None, project_id: int) -> None:
    if orgs is None:
        return
    for proj, uid, email in orgs.pop_invite_events(project_id):
        ActivityLog.record(
            project=proj,
            actor=None,
            action="cvat.org_invite",
            target=proj,
            after={"cvat_user_id": uid, "email": email, "role": "worker"},
        )


def _persist_push_success(
    job_id: int,
    pushed_target: int | None,
    *,
    orgs: _OrgMembers | None = None,
    outbox_id: int | None = None,
) -> tuple[bool, bool]:
    """Khoá Job, kiểm tra chống ghi đè stale-write, cập nhật cvat_assignee_id và ghi ActivityLog.

    Trả về (updated_job, superseded).
    """
    with transaction.atomic():
        fresh_job = (
            Job.objects.select_for_update(of=("self",))
            .select_related("project", "annotator__cvat_account", "qc1_reviewer__cvat_account")
            .prefetch_related(pending_samples_prefetch())
            .filter(pk=job_id)
            .first()
        )
        outbox_row = (
            CvatAssigneeOutbox.objects.select_for_update().filter(pk=outbox_id).first()
            if outbox_id is not None
            else None
        )
        if fresh_job is not None:
            _record_invite_logs(orgs, fresh_job.project_id)

        if fresh_job is None or fresh_job.cvat_job_id is None:
            if outbox_row is not None:
                outbox_row.status = CvatAssigneeOutbox.Status.DONE
                outbox_row.last_error = ""
                outbox_row.save(update_fields=["status", "last_error", "updated_at"])
            return False, False

        fresh_holder = current_holder(fresh_job)
        fresh_target = _cvat_user_id(fresh_holder)
        if fresh_target != pushed_target:
            # Trong lúc gọi HTTP, VanoHub đã đổi người giữ job → không ghi đè state mới; xếp lại lượt mới.
            if outbox_row is not None:
                outbox_row.status = CvatAssigneeOutbox.Status.DONE
                outbox_row.last_error = "Superseded by newer assignment during HTTP push"
                outbox_row.save(update_fields=["status", "last_error", "updated_at"])
            _upsert_pending_outbox(fresh_job, fresh_holder, fresh_target, timezone.now())
            return False, True

        prev_assignee = fresh_job.cvat_assignee_id
        if prev_assignee != fresh_target:
            fresh_job.cvat_assignee_id = fresh_target
            fresh_job.save(update_fields=["cvat_assignee_id", "updated_at"])
            ActivityLog.record(
                project=fresh_job.project,
                actor=None,
                action="cvat.assignee_push",
                target=fresh_job,
                job=fresh_job,
                before={"cvat_assignee_id": prev_assignee},
                after={"cvat_assignee_id": fresh_target, "cvat_job_id": fresh_job.cvat_job_id},
            )
        if outbox_row is not None:
            outbox_row.status = CvatAssigneeOutbox.Status.DONE
            outbox_row.last_error = ""
            outbox_row.save(update_fields=["status", "last_error", "updated_at"])
        return True, False


def _mark_outbox_failed(outbox_id: int, exc: Exception, *, max_attempts: int) -> str:
    now = timezone.now()
    with transaction.atomic():
        row = CvatAssigneeOutbox.objects.select_for_update().filter(pk=outbox_id).first()
        if row is None:
            return CvatAssigneeOutbox.Status.DONE
        row.attempts += 1
        row.last_error = str(exc)[:2000]
        if row.attempts >= max_attempts:
            row.status = CvatAssigneeOutbox.Status.DEAD
        else:
            delay_seconds = min(3600, 30 * (2 ** min(row.attempts - 1, 7)))
            row.status = CvatAssigneeOutbox.Status.PENDING
            row.next_retry_at = now + timedelta(seconds=delay_seconds)
        row.save(update_fields=["attempts", "status", "next_retry_at", "last_error", "updated_at"])
        return row.status


def _reclaim_stale_processing(now: Any) -> None:
    stale_cutoff = now - timedelta(minutes=_STALE_PROCESSING_MINUTES)
    with transaction.atomic():
        stale_rows = list(
            CvatAssigneeOutbox.objects.select_for_update(skip_locked=True)
            .filter(status=CvatAssigneeOutbox.Status.PROCESSING, updated_at__lt=stale_cutoff)
            .order_by("id")
        )
        if not stale_rows:
            return
        pending_job_ids = set(
            CvatAssigneeOutbox.objects.filter(
                job_id__in=[r.job_id for r in stale_rows],
                status=CvatAssigneeOutbox.Status.PENDING,
            ).values_list("job_id", flat=True)
        )
        for row in stale_rows:
            if row.job_id in pending_job_ids:
                row.status = CvatAssigneeOutbox.Status.DONE
                row.last_error = "Superseded stale processing row"
            else:
                row.status = CvatAssigneeOutbox.Status.PENDING
                row.next_retry_at = now
                pending_job_ids.add(row.job_id)
            row.save(update_fields=["status", "next_retry_at", "last_error", "updated_at"])


def drain_cvat_outbox(
    *,
    batch_limit: int = 50,
    job_ids: Iterable[int] | None = None,
    client: Any = None,
    timeout: int | None = None,
    force: bool = False,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
) -> dict[str, Any]:
    """Xử lý hàng đợi CvatAssigneeOutbox ngoài DB transaction; lỗi từng job không làm dừng cả lô."""
    stats: dict[str, Any] = {"claimed": 0, "pushed": 0, "failed": 0, "dead": 0, "skipped": 0, "locked": False}
    use_advisory_lock = job_ids is None
    if use_advisory_lock and not _try_advisory_lock(_OUTBOX_ADVISORY_NS, _OUTBOX_ADVISORY_KEY):
        stats["locked"] = True
        return stats

    owned_client: Any = None
    try:
        now = timezone.now()
        _reclaim_stale_processing(now)
        with transaction.atomic():
            due_qs = CvatAssigneeOutbox.objects.select_for_update(skip_locked=True).filter(
                status=CvatAssigneeOutbox.Status.PENDING
            )
            if job_ids is not None:
                due_qs = due_qs.filter(job_id__in=list(job_ids))
            if not force:
                due_qs = due_qs.filter(next_retry_at__lte=now)
            claimed_rows = list(due_qs.order_by("next_retry_at", "id")[:batch_limit])
            if not claimed_rows:
                return stats
            CvatAssigneeOutbox.objects.filter(pk__in=[r.pk for r in claimed_rows]).update(
                status=CvatAssigneeOutbox.Status.PROCESSING,
                updated_at=now,
            )

        stats["claimed"] = len(claimed_rows)
        orgs: _OrgMembers | None = None

        for row in claimed_rows:
            job = _jobs([row.job_id]).first()
            if job is None or job.cvat_job_id is None:
                with transaction.atomic():
                    CvatAssigneeOutbox.objects.filter(pk=row.pk).update(
                        status=CvatAssigneeOutbox.Status.DONE,
                        last_error="",
                        updated_at=timezone.now(),
                    )
                stats["skipped"] += 1
                continue

            holder = current_holder(job)
            target = _cvat_user_id(holder)
            if job.cvat_assignee_id == target:
                with transaction.atomic():
                    CvatAssigneeOutbox.objects.filter(pk=row.pk).update(
                        status=CvatAssigneeOutbox.Status.DONE,
                        last_error="",
                        updated_at=timezone.now(),
                    )
                stats["skipped"] += 1
                continue

            try:
                if client is None:
                    owned_client = CvatClient() if timeout is None else CvatClient(timeout=timeout)
                    client = owned_client
                if target is not None:
                    orgs = orgs or _OrgMembers(client)
                    try:
                        warning = orgs.ensure(job.project, target)
                        if warning:
                            logger.warning("Job %s: %s", job.pk, warning)
                    except CvatError as exc:
                        logger.warning("Không tự thêm được vào organization cho job %s: %s", job.pk, exc)
                client.set_job_assignee(job.cvat_job_id, target)
            except CvatError as exc:
                if orgs is not None:
                    with transaction.atomic():
                        _record_invite_logs(orgs, job.project_id)
                new_status = _mark_outbox_failed(row.pk, exc, max_attempts=max_attempts)
                if new_status == CvatAssigneeOutbox.Status.DEAD:
                    stats["dead"] += 1
                else:
                    stats["failed"] += 1
                logger.warning("Outbox #%s (job=%s) lỗi khi đẩy assignee CVAT: %s", row.pk, job.pk, exc)
                continue

            updated, superseded = _persist_push_success(job.pk, target, orgs=orgs, outbox_id=row.pk)
            if updated:
                stats["pushed"] += 1
            elif superseded:
                stats["skipped"] += 1
            else:
                stats["skipped"] += 1
        return stats
    finally:
        if owned_client is not None:
            _close_quietly(owned_client)
        if use_advisory_lock:
            _release_advisory_lock(_OUTBOX_ADVISORY_NS, _OUTBOX_ADVISORY_KEY)


def drain_cvat_outbox_quietly(
    *,
    job_ids: Iterable[int] | None = None,
    batch_limit: int = 20,
    timeout: int | None = None,
) -> None:
    try:
        drain_cvat_outbox(job_ids=job_ids, batch_limit=batch_limit, timeout=timeout)
    except Exception:
        logger.exception("Lỗi không mong muốn khi đẩy hàng đợi assignee CVAT cho job %s", list(job_ids or ()))


def push_assignees(
    jobs: Iterable[Job],
    client: Any = None,
    *,
    raise_on_error: bool = True,
) -> dict[str, Any]:
    """Đặt assignee CVAT cho các job (chỉ gọi CVAT khi khác giá trị đang có).

    Không dừng cả lô khi một job gặp CvatError: ghi lại lỗi từng job, xếp hàng đợi retry vào
    CvatAssigneeOutbox, khoá Job khi lưu cvat_assignee_id và ghi ActivityLog cho mỗi lần đẩy/mời.
    """
    pushed = waiting = 0
    warnings: list[str] = []
    errors: list[str] = []
    orgs: _OrgMembers | None = None
    owned_client: Any = None
    try:
        for job in jobs:
            if not job.cvat_job_id:
                continue
            holder = current_holder(job)
            target = _cvat_user_id(holder)
            if holder is not None and target is None:
                waiting += 1
            if job.cvat_assignee_id == target:
                continue
            try:
                if client is None:
                    owned_client = CvatClient()
                    client = owned_client
                if target is not None:
                    orgs = orgs or _OrgMembers(client)
                    try:
                        warning = orgs.ensure(job.project, target)
                    except CvatError as exc:  # không mời được vẫn giao job; chỉ cảnh báo
                        warning = f"Không tự thêm được vào organization: {exc}"
                    if warning and warning not in warnings:
                        warnings.append(warning)
                client.set_job_assignee(job.cvat_job_id, target)
            except CvatError as exc:
                if orgs is not None:
                    with transaction.atomic():
                        _record_invite_logs(orgs, job.project_id)
                errors.append(str(exc))
                with transaction.atomic():
                    _upsert_pending_outbox(job, holder, target, timezone.now())
                logger.warning("Không đẩy được assignee sang CVAT cho job %s: %s", job.pk, exc)
                continue

            updated, _ = _persist_push_success(job.pk, target, orgs=orgs)
            if updated:
                job.cvat_assignee_id = target
                pushed += 1
    finally:
        if owned_client is not None:
            _close_quietly(owned_client)

    if errors:
        if raise_on_error:
            raise CvatError("; ".join(errors))
        return {"pushed": pushed, "waiting": waiting, "warnings": warnings, "errors": errors}
    return {"pushed": pushed, "waiting": waiting, "warnings": warnings}


def push_assignees_quietly(job_ids: Iterable[int]) -> None:
    ids = list(job_ids)
    try:
        result = push_assignees(_jobs(ids))
    except CvatError as exc:
        logger.warning("Không đẩy được assignee sang CVAT cho job %s: %s", ids, exc)
        return
    for warning in result["warnings"]:
        logger.warning("Job %s: %s", ids, warning)


def schedule_assignee_push(job_ids: Iterable[int]) -> None:
    """Gọi bên trong transaction khi đổi người giữ job: lưu outbox ngay và đẩy best-effort sau commit."""
    ids = sorted({jid for jid in job_ids if isinstance(jid, int) and not isinstance(jid, bool) and jid > 0})
    if not ids:
        return
    enqueue_assignee_push(ids)
    limit = int(getattr(settings, "CVAT_OUTBOX_ON_COMMIT_LIMIT", 20))
    if limit > 0:
        on_commit_ids = ids[:limit]
        timeout = int(getattr(settings, "CVAT_OUTBOX_ON_COMMIT_TIMEOUT", 5))
        transaction.on_commit(
            lambda: drain_cvat_outbox_quietly(job_ids=on_commit_ids, batch_limit=limit, timeout=timeout)
        )


def jobs_held_by(user: Any) -> QuerySet[Job]:
    """Các job có CVAT mà user đang giữ — dùng khi user liên kết / huỷ liên kết."""
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
