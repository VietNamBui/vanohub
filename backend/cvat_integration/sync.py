"""Đồng bộ cấu trúc, trạng thái và sản lượng từ CVAT về VanoHub.

Ánh xạ:
    CVAT Organization → Project (model)   — "Organization" trên giao diện
    CVAT Project      → Dataset (model)   — "Project"
    CVAT Task         → Batch (model)     — "Task"
    CVAT Job          → Job               (chỉ job loại "annotation"; bỏ Ground Truth / consensus)

Quy tắc biên dữ liệu & an toàn workflow:
- Toàn bộ HTTP I/O gọi CVAT thực hiện NGOÀI transaction.atomic() để không giữ khóa DB.
- Chỉ đồng bộ trạng thái một chiều trong `SYNCABLE_STATUSES` (KHÔNG gồm `QC1_PASSED`, `PENDING_QC2`,
  `APPROVED`, `DELIVERED`); không kéo lùi `PENDING_QC1` / `QC1_REVIEWING` / `REWORK` và không đẩy
  `REWORK` sang `PENDING_QC2`.
- Hybrid A2 gate: trạng thái post-QC1 (`validation/completed`, `acceptance/*`) bị chặn ở `QC1_PASSED`
  khi `batch.qc2_confirmed_at is None`; chỉ vào `PENDING_QC2` + `ensure_qc2_sample` khi batch đã xác nhận QC2.
- Tôn trọng khóa (`is_locked`, batch/dataset không `active`, `DELIVERED`) và `EscalationPolicy.BLOCK`
  (vẫn cho đồng bộ bình thường khi `EscalationPolicy.WARN_ONLY`).
- Nhật ký `ActivityLog` từ đồng bộ gán `actor=job.annotator` (làm/nộp), `actor=assignee/qc1_reviewer CVAT`
  (duyệt/trả QC1), hoặc `None` — KHÔNG bao giờ gán PM bấm đồng bộ làm actor để tránh làm nhiễm luật bốn mắt
  (lưu `synced_by` trong `after`).
- Sản lượng ngày (`DailyOutputRecord(CVAT_SYNC)`): ghi phần chênh lệch dương khi `object_count` tăng.
- Lỗi 404 (`CvatNotFoundError`) ở từng task/job được bắt cục bộ và đánh dấu `source_missing=True` mà
  không làm hỏng toàn bộ phiên đồng bộ organization.
"""

import logging
import math
import time
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError
from rest_framework.exceptions import ValidationError

from accounts.models import Role, RoleAssignment, User
from jobs.models import (
    ACTIVE_ANNOTATOR_STATUSES,
    DailyOutputRecord,
    FirstQc1Result,
    Job,
    JobStatus,
    record_daily_output,
)
from projects.models import ActivityLog, Batch, Dataset, DataStatus, EscalationPolicy, Project
from projects.notifications import notify_escalated
from quality.models import seed_default_error_categories
from quality.qc2 import ensure_qc2_sample

from .assignee import (
    _close_quietly,
    _release_advisory_lock,
    _try_advisory_lock,
    pending_samples_prefetch,
    push_assignees,
)
from .client import CvatClient, CvatError, CvatNotFoundError
from .models import CvatAccount
from .schemas import CvatImportResult, CvatJobPayload, CvatSyncResult, CvatTaskPayload

logger = logging.getLogger(__name__)

_SYNC_ORGS_LOCK_NS = 0x5648534F
_SYNC_ORG_LOCK_NS = 0x56485359
_DEFAULT_SYNC_TIMEOUT_SECONDS = 300.0

# Các trạng thái còn được phép nhận tiến độ một chiều từ CVAT.
# KHÔNG bao gồm QC1_PASSED / PENDING_QC2 / APPROVED / DELIVERED để không bao giờ kéo lùi sau QC1.
SYNCABLE_STATUSES: set[str] = {
    JobStatus.PENDING_ANNOTATION,
    JobStatus.ANNOTATING,
    JobStatus.REWORK,
    JobStatus.PENDING_QC1,
    JobStatus.QC1_REVIEWING,
}

POST_QC1_CVAT_STATES: set[tuple[str, str]] = {
    ("validation", "completed"),
    ("acceptance", "new"),
    ("acceptance", "in progress"),
    ("acceptance", "completed"),
}

# (stage, state) của CVAT → trạng thái mặc định VanoHub (post-QC1 được Hybrid A2 xét theo batch.qc2_confirmed_at).
CVAT_STATUS_MAP: dict[tuple[str, str], str] = {
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

PM_ORG_ROLES: set[str] = {"owner", "maintainer"}


@dataclass
class _RemoteJobEntry:
    payload: CvatJobPayload
    object_count: int | None = None
    missing: bool = False


@dataclass
class _RemoteTaskEntry:
    raw: dict[str, Any]
    skipped_foreign: bool = False
    missing_error: str | None = None
    jobs: list[_RemoteJobEntry] = field(default_factory=list)


@dataclass
class _RemoteProjectEntry:
    raw: dict[str, Any]
    skipped_foreign: bool = False
    missing: bool = False
    tasks: list[_RemoteTaskEntry] = field(default_factory=list)


def _parse_task(raw: Any) -> CvatTaskPayload:
    try:
        return CvatTaskPayload.model_validate(raw)
    except PydanticValidationError as exc:
        logger.warning("CVAT task payload invalid: %s", exc.errors(include_url=False, include_input=False))
        raise CvatError("Dữ liệu CVAT task không hợp lệ.") from exc


def _parse_job(raw: Any) -> CvatJobPayload:
    try:
        return CvatJobPayload.model_validate(raw)
    except PydanticValidationError as exc:
        logger.warning("CVAT job payload invalid: %s", exc.errors(include_url=False, include_input=False))
        raise CvatError("Dữ liệu CVAT job không hợp lệ.") from exc


def _is_annotation_job(cvat_job: CvatJobPayload) -> bool:
    return cvat_job.type in ("", "annotation")


def _user_id(obj: Any) -> int | None:
    """ID user CVAT trong trường assignee/owner (CVAT trả object {"id", "username"} hoặc null)."""
    if isinstance(obj, dict):
        uid = obj.get("id")
        return uid if isinstance(uid, int) and not isinstance(uid, bool) else None
    return None


def _linked_users() -> dict[int, User]:
    return {a.cvat_user_id: a.user for a in CvatAccount.objects.select_related("user")}


def _map_cvat_status(stage: str, state: str, *, batch: Batch) -> str | None:
    """Ánh xạ (stage, state) CVAT sang JobStatus theo Hybrid A2 gate."""
    if (stage, state) in POST_QC1_CVAT_STATES:
        return JobStatus.PENDING_QC2 if batch.qc2_confirmed_at is not None else JobStatus.QC1_PASSED
    return CVAT_STATUS_MAP.get((stage, state))


def _is_workflow_frozen(job: Job) -> bool:
    """Job không được phép tự chuyển trạng thái khi bị khoá, escalated theo BLOCK, hoặc batch/dataset đóng."""
    escalated_blocked = job.is_escalated and job.project.escalation_policy == EscalationPolicy.BLOCK
    return (
        job.is_locked
        or escalated_blocked
        or job.status == JobStatus.DELIVERED
        or job.batch.status != DataStatus.ACTIVE
        or job.dataset.status != DataStatus.ACTIVE
    )


def _next_cvat_status(
    job: Job,
    stage: str,
    state: str,
    prev_stage: str,
    prev_state: str,
) -> str | None:
    """Chỉ cho phép CVAT đẩy tiến độ một chiều trong SYNCABLE_STATUSES, không ghi đè workflow VanoHub."""
    if _is_workflow_frozen(job) or job.status not in SYNCABLE_STATUSES:
        return None
    mapped = _map_cvat_status(stage, state, batch=job.batch)
    if not mapped or mapped == job.status:
        return None
    if job.status == JobStatus.PENDING_ANNOTATION:
        if mapped == JobStatus.ANNOTATING:
            return JobStatus.ANNOTATING
        if job.rework_round == 0 and job.total_rework_rounds == 0 and mapped == JobStatus.PENDING_QC1:
            return JobStatus.PENDING_QC1
        return None
    if job.status == JobStatus.ANNOTATING:
        if job.rework_round == 0 and job.total_rework_rounds == 0 and mapped == JobStatus.PENDING_QC1:
            return JobStatus.PENDING_QC1
        if (stage, state) == ("annotation", "rejected") and (prev_stage, prev_state) != ("annotation", "rejected"):
            return JobStatus.REWORK
        return None
    if job.status == JobStatus.QC1_REVIEWING:
        if (stage, state) == ("validation", "rejected") and (prev_stage, prev_state) != ("validation", "rejected"):
            return JobStatus.REWORK
        if (stage, state) in POST_QC1_CVAT_STATES and (prev_stage, prev_state) not in POST_QC1_CVAT_STATES:
            return mapped
        return None
    return None


def _count_job_objects_safe(client: Any, cvat_job: CvatJobPayload) -> int:
    if isinstance(client, CvatClient):
        count = client.count_job_objects(
            cvat_job.id,
            start_frame=cvat_job.start_frame,
            stop_frame=cvat_job.stop_frame,
        )
    else:
        count = client.count_job_objects(cvat_job.id)
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise CvatError(f"Số object trả về từ CVAT không hợp lệ: {count!r}")
    return count


def _apply_object_count(job: Job, new_count: int | None) -> bool:
    """Cập nhật object_count và ghi phần chênh lệch dương vào sổ DailyOutputRecord (CVAT_SYNC).

    Không bao giờ sửa object_count hoặc cộng sản lượng ngoài SYNCABLE_STATUSES (kể cả khi đã có submitted_at),
    hoặc khi job bị khoá / batch hoặc dataset không còn active.
    """
    if (
        new_count is None
        or job.is_locked
        or job.batch.status != DataStatus.ACTIVE
        or job.dataset.status != DataStatus.ACTIVE
        or job.status not in SYNCABLE_STATUSES
    ):
        return False
    changed = False
    if new_count != job.object_count:
        job.object_count = new_count
        changed = True
    if job.annotator_id and new_count > job.last_counted_objects:
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
    return changed


def _apply_cvat_state(
    job: Job,
    cvat_job: CvatJobPayload,
    actor: Any,
    *,
    object_count: int | None = None,
    linked: dict[int, User] | None = None,
) -> bool:
    """Cập nhật một Job từ dữ liệu CVAT (tự save, ghi ActivityLog an toàn 4-eyes và notify escalation)."""
    if (
        job.is_locked
        or job.status == JobStatus.DELIVERED
        or job.batch.status != DataStatus.ACTIVE
        or job.dataset.status != DataStatus.ACTIVE
    ):
        return False

    stage, state = cvat_job.stage, cvat_job.state
    assignee_id = cvat_job.assignee.id if cvat_job.assignee else None
    frame_count = cvat_job.resolved_frame_count
    start_frame = cvat_job.start_frame or 0
    prev_stage, prev_state = job.cvat_stage, job.cvat_state

    update_fields: list[str] = []
    if prev_stage != stage:
        job.cvat_stage = stage
        update_fields.append("cvat_stage")
    if prev_state != state:
        job.cvat_state = state
        update_fields.append("cvat_state")
    if job.cvat_assignee_id != assignee_id:
        job.cvat_assignee_id = assignee_id
        update_fields.append("cvat_assignee_id")
    if job.frame_count != frame_count:
        job.frame_count = frame_count
        update_fields.append("frame_count")
    if job.cvat_start_frame != start_frame:
        job.cvat_start_frame = start_frame
        update_fields.append("cvat_start_frame")
    if job.source_missing:
        job.source_missing = False
        update_fields.append("source_missing")

    if _apply_object_count(job, object_count):
        update_fields.extend(["object_count", "last_counted_objects", "round_credited_objects"])

    new_status = _next_cvat_status(job, stage, state, prev_stage, prev_state)
    if new_status is None:
        if update_fields:
            update_fields.append("updated_at")
            job.save(update_fields=list(dict.fromkeys(update_fields)))
            return True
        return False

    before = job.status
    newly_escalated = False
    after_payload: dict[str, Any] = {"status": new_status}

    # Tránh nhiễm luật 4-eyes: KHÔNG BAO GIỜ gán PM bấm đồng bộ làm actor cho job.status.
    log_actor: User | None = None
    if new_status == JobStatus.REWORK:
        job.rework_round += 1
        job.total_rework_rounds = max(job.total_rework_rounds + 1, job.rework_round)
        job.round_credited_objects = 0
        job.last_counted_objects = max(job.last_counted_objects, job.object_count)
        update_fields.extend(["rework_round", "total_rework_rounds", "round_credited_objects", "last_counted_objects"])
        if not job.first_qc1_result and stage == "validation":
            job.first_qc1_result = FirstQc1Result.REJECT
            update_fields.append("first_qc1_result")
        if job.rework_round > job.project.max_rework_rounds and not job.is_escalated:
            job.is_escalated = True
            newly_escalated = True
            update_fields.append("is_escalated")
        after_payload["rework_round"] = job.rework_round
        after_payload["escalated"] = job.is_escalated
    elif new_status in (JobStatus.QC1_PASSED, JobStatus.PENDING_QC2):
        if not job.first_qc1_result:
            job.first_qc1_result = FirstQc1Result.PASS
            update_fields.append("first_qc1_result")
    elif new_status == JobStatus.PENDING_QC1:
        job.submitted_at = timezone.now()
        update_fields.append("submitted_at")
        log_actor = job.annotator
        is_rw = job.total_rework_rounds > 0 or job.rework_round > 0
        after_payload["event"] = "annotator.resubmit" if is_rw else "annotator.submit"
        after_payload["rework_round"] = job.rework_round
        after_payload["object_count"] = job.object_count
    elif new_status == JobStatus.ANNOTATING:
        log_actor = job.annotator

    if before == JobStatus.QC1_REVIEWING and new_status in (
        JobStatus.REWORK,
        JobStatus.QC1_PASSED,
        JobStatus.PENDING_QC2,
    ):
        reviewer = ((linked or {}).get(assignee_id) if assignee_id else None) or job.qc1_reviewer
        log_actor = reviewer
        after_payload["event"] = "qc1.reject" if new_status == JobStatus.REWORK else "qc1.pass"
        if reviewer is not None and job.qc1_reviewer_id is None and reviewer.pk != job.annotator_id:
            job.qc1_reviewer = reviewer
            update_fields.append("qc1_reviewer")

    if actor is not None and getattr(actor, "is_authenticated", False):
        after_payload["synced_by"] = actor.pk

    job.status = new_status
    update_fields.extend(["status", "updated_at"])
    job.save(update_fields=list(dict.fromkeys(update_fields)))
    ActivityLog.record(
        project=job.project,
        actor=log_actor,
        action="job.status",
        target=job,
        job=job,
        before={"status": before},
        after=after_payload,
        note="Đồng bộ từ CVAT",
    )
    if newly_escalated:
        notify_escalated(job.project, job, actor=actor)
    return True


def _new_job(
    project: Project,
    dataset: Dataset,
    batch: Batch,
    cvat_job: CvatJobPayload,
    linked: dict[int, User],
    annotator_ids: set[int],
) -> Job:
    assignee_id = cvat_job.assignee.id if cvat_job.assignee else None
    candidate = linked.get(assignee_id) if assignee_id is not None else None
    annotator = candidate if candidate and candidate.pk in annotator_ids else None
    initial_status = _map_cvat_status(cvat_job.stage, cvat_job.state, batch=batch) or JobStatus.PENDING_ANNOTATION
    initial_rework = 1 if initial_status == JobStatus.REWORK else 0
    if initial_status in (JobStatus.QC1_PASSED, JobStatus.PENDING_QC2):
        initial_first_qc1 = FirstQc1Result.PASS
    elif initial_status == JobStatus.REWORK and cvat_job.stage == "validation":
        initial_first_qc1 = FirstQc1Result.REJECT
    else:
        initial_first_qc1 = ""
    return Job(
        project=project,
        dataset=dataset,
        batch=batch,
        name=f"{batch.name} · job {cvat_job.id}",
        cvat_job_id=cvat_job.id,
        cvat_task_id=batch.cvat_task_id,
        cvat_start_frame=cvat_job.start_frame or 0,
        annotator=annotator,
        deadline=batch.deadline,
        cvat_stage=cvat_job.stage,
        cvat_state=cvat_job.state,
        cvat_assignee_id=assignee_id,
        frame_count=cvat_job.resolved_frame_count,
        object_count=0,
        status=initial_status,
        rework_round=initial_rework,
        total_rework_rounds=initial_rework,
        first_qc1_result=initial_first_qc1,
    )


# ---------------------------------------------------------------- Organization


def _mark_batch_source_missing(batch: Batch, *, now: Any, error_msg: str) -> int:
    """Đánh dấu Batch mất nguồn trên CVAT và lan truyền source_missing=True xuống các Job mở/chưa khoá."""
    if batch.status == DataStatus.DELIVERED:
        return 0
    batch.source_missing = True
    batch.last_synced_at = now
    batch.last_sync_status = Batch.SyncStatus.ERROR
    batch.last_sync_error = error_msg
    batch.save(update_fields=["source_missing", "last_synced_at", "last_sync_status", "last_sync_error"])
    if batch.status != DataStatus.ACTIVE or batch.dataset.status != DataStatus.ACTIVE:
        return 0
    child_jobs = list(
        Job.objects.select_for_update(of=("self",))
        .filter(batch=batch, cvat_job_id__isnull=False, source_missing=False, is_locked=False)
        .exclude(status=JobStatus.DELIVERED)
        .order_by("id")
    )
    if child_jobs:
        Job.objects.filter(pk__in=[j.pk for j in child_jobs]).update(source_missing=True, updated_at=now)
    return len(child_jobs)


def sync_organizations(
    actor: Any = None,
    client: Any = None,
    *,
    only_cvat_user_id: int | None = None,
) -> dict[str, Any]:
    """Tạo / cập nhật "Organization" VanoHub từ CVAT organization + gán vai trò theo thành viên.

    Chỉ tạo khi organization có ít nhất một Owner / Maintainer đã liên kết VanoHub (để có PM).
    """
    lock_key = only_cvat_user_id or 0
    if not _try_advisory_lock(_SYNC_ORGS_LOCK_NS, lock_key):
        raise ValidationError({"detail": "Đang đồng bộ danh sách organization từ CVAT, vui lòng đợi giây lát."})

    owned_client: Any = None
    try:
        if client is None:
            owned_client = CvatClient()
            client = owned_client
        linked = _linked_users()
        auth_actor = actor if actor and getattr(actor, "is_authenticated", False) else None
        created: list[str] = []
        created_ids: list[int] = []
        updated: list[str] = []
        updated_ids: list[int] = []
        pm_added: list[dict[str, Any]] = []
        members_added: list[dict[str, Any]] = []
        waiting: list[dict[str, Any]] = []

        for org in client.list_organizations():
            memberships = [m for m in client.list_memberships(org["id"]) if m.get("is_active", True)]
            if only_cvat_user_id is not None and not any(
                _user_id(m.get("user")) == only_cvat_user_id for m in memberships
            ):
                continue
            pms = [
                linked[uid]
                for m in memberships
                if m.get("role") in PM_ORG_ROLES and (uid := _user_id(m.get("user"))) is not None and uid in linked
            ]
            name = org.get("name") or org.get("slug") or f"Org #{org['id']}"
            slug = org.get("slug", "")
            with transaction.atomic():
                project = Project.objects.select_for_update().filter(cvat_org_id=org["id"]).first()
                if project is None and not pms:
                    waiting.append(
                        {
                            "cvat_org_id": org["id"],
                            "name": name,
                            "reason": "Chưa có Owner / Maintainer nào liên kết VanoHub",
                        }
                    )
                    continue
                if project is None:
                    try:
                        with transaction.atomic():
                            project = Project.objects.create(
                                name=name,
                                cvat_org_id=org["id"],
                                cvat_org_slug=slug,
                                created_by=auth_actor,
                            )
                            created.append(name)
                            created_ids.append(project.pk)
                    except IntegrityError:
                        project = Project.objects.select_for_update().get(cvat_org_id=org["id"])
                if project.pk not in created_ids and (project.name != name or project.cvat_org_slug != slug):
                    project.name = name
                    project.cvat_org_slug = slug
                    project.save(update_fields=["name", "cvat_org_slug", "updated_at"])
                    updated.append(name)
                    updated_ids.append(project.pk)
                seed_default_error_categories(project)
                for membership in memberships:
                    uid = _user_id(membership.get("user"))
                    user = linked.get(uid) if uid is not None else None
                    if user is None:
                        continue
                    if membership.get("role") in PM_ORG_ROLES:
                        try:
                            with transaction.atomic():
                                _, added = RoleAssignment.objects.get_or_create(
                                    user=user,
                                    role=Role.PROJECT_MANAGER,
                                    project=project,
                                    defaults={"granted_by": auth_actor},
                                )
                        except IntegrityError:
                            added = False
                        if added:
                            pm_added.append(
                                {"organization": name, "organization_id": project.pk, "user": user.username}
                            )
                            ActivityLog.record(
                                project=project,
                                actor=auth_actor,
                                action="project.assign_pm",
                                target=user,
                                note=f"Theo vai trò {membership['role']} trong CVAT organization",
                            )
                    elif not RoleAssignment.objects.filter(user=user, project=project).exists():
                        try:
                            with transaction.atomic():
                                _, added = RoleAssignment.objects.get_or_create(
                                    user=user,
                                    role=Role.ANNOTATOR,
                                    project=project,
                                    defaults={"granted_by": auth_actor},
                                )
                        except IntegrityError:
                            added = False
                        if added:
                            members_added.append(
                                {"organization": name, "organization_id": project.pk, "user": user.username}
                            )
            if project.cvat_synced_at is None:
                # Organization mới → kéo luôn project / task / job, PM không phải bấm thêm.
                with suppress(CvatError, ValidationError):
                    sync_organization(project, actor, client=client, cooldown_seconds=0)
        return {
            "created": created,
            "created_ids": created_ids,
            "updated": updated,
            "updated_ids": updated_ids,
            "pm_added": pm_added,
            "members_added": members_added,
            "waiting": waiting,
        }
    finally:
        if owned_client is not None:
            _close_quietly(owned_client)
        _release_advisory_lock(_SYNC_ORGS_LOCK_NS, lock_key)


def sync_organizations_quietly(actor: Any = None, *, only_cvat_user_id: int | None = None) -> dict[str, Any]:
    """Như sync_organizations nhưng không ném lỗi (dùng sau khi liên kết CVAT)."""
    try:
        return sync_organizations(actor, only_cvat_user_id=only_cvat_user_id)
    except (CvatError, ValidationError) as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------- Project / Task / Job


def _fetch_remote_org_tree(
    project: Project,
    client: Any,
    *,
    count_objects: bool = False,
) -> list[_RemoteProjectEntry]:
    """Kéo toàn bộ dữ liệu project/task/job (+ object_count) từ CVAT NGOÀI transaction DB.

    Lỗi 404 (`CvatNotFoundError`) ở từng project/task/job được ghi nhận cục bộ để đánh dấu
    `source_missing=True` mà không làm gián đoạn phần còn lại của organization.
    """
    sync_deadline = float(getattr(settings, "CVAT_SYNC_TIMEOUT_SECONDS", _DEFAULT_SYNC_TIMEOUT_SECONDS))
    started = time.monotonic()

    def _check_deadline() -> None:
        if sync_deadline > 0 and (time.monotonic() - started) >= sync_deadline:
            raise CvatError("Quá thời gian đồng bộ dữ liệu từ CVAT — thử lại sau hoặc tắt đếm object.")

    _check_deadline()
    cvat_projects = client.list_org_projects(project.cvat_org_id)
    foreign_project_ids = set(
        Dataset.objects.filter(cvat_project_id__in=[p["id"] for p in cvat_projects])
        .exclude(project=project)
        .values_list("cvat_project_id", flat=True)
    )
    remote_projects: list[_RemoteProjectEntry] = []
    for cvat_project in cvat_projects:
        _check_deadline()
        if cvat_project["id"] in foreign_project_ids:
            remote_projects.append(_RemoteProjectEntry(raw=cvat_project, skipped_foreign=True))
            continue
        try:
            cvat_tasks = client.list_project_tasks(cvat_project["id"])
        except CvatNotFoundError:
            remote_projects.append(_RemoteProjectEntry(raw=cvat_project, missing=True))
            continue
        foreign_task_ids = set(
            Batch.objects.filter(cvat_task_id__in=[t["id"] for t in cvat_tasks])
            .exclude(project=project)
            .values_list("cvat_task_id", flat=True)
        )
        remote_tasks: list[_RemoteTaskEntry] = []
        for cvat_task in cvat_tasks:
            _check_deadline()
            if cvat_task["id"] in foreign_task_ids:
                remote_tasks.append(_RemoteTaskEntry(raw=cvat_task, skipped_foreign=True))
                continue
            try:
                raw_jobs = client.list_task_jobs(cvat_task["id"])
            except CvatNotFoundError as exc:
                remote_tasks.append(_RemoteTaskEntry(raw=cvat_task, missing_error=str(exc)))
                continue
            remote_jobs: list[_RemoteJobEntry] = []
            for raw_job in raw_jobs:
                cvat_job = _parse_job(raw_job)
                if not _is_annotation_job(cvat_job):
                    continue  # bỏ Ground Truth / consensus job
                if not count_objects:
                    remote_jobs.append(_RemoteJobEntry(payload=cvat_job))
                    continue
                _check_deadline()
                try:
                    obj_count = _count_job_objects_safe(client, cvat_job)
                except CvatNotFoundError:
                    remote_jobs.append(_RemoteJobEntry(payload=cvat_job, missing=True))
                    continue
                remote_jobs.append(_RemoteJobEntry(payload=cvat_job, object_count=obj_count))
            remote_tasks.append(_RemoteTaskEntry(raw=cvat_task, jobs=remote_jobs))
        remote_projects.append(_RemoteProjectEntry(raw=cvat_project, tasks=remote_tasks))
    return remote_projects


def sync_organization(
    project: Project,
    actor: Any,
    client: Any = None,
    count_objects: bool = False,
    *,
    cooldown_seconds: int | None = None,
) -> dict[str, Any]:
    """Đồng bộ một organization: CVAT project → Dataset, task → Batch, job → Job."""
    if not project.cvat_org_id:
        raise CvatError("Organization này chưa gắn với CVAT organization.")
    if not _try_advisory_lock(_SYNC_ORG_LOCK_NS, project.pk):
        raise ValidationError({"detail": "Organization này đang được đồng bộ từ CVAT, vui lòng đợi giây lát."})

    owned_client: Any = None
    try:
        cooldown = (
            int(getattr(settings, "CVAT_SYNC_COOLDOWN_SECONDS", 10))
            if cooldown_seconds is None
            else cooldown_seconds
        )
        if cooldown > 0:
            last_synced = Project.objects.filter(pk=project.pk).values_list("cvat_synced_at", flat=True).first()
            if last_synced is not None:
                elapsed = (timezone.now() - last_synced).total_seconds()
                if elapsed < cooldown:
                    wait_secs = max(1, math.ceil(cooldown - elapsed))
                    raise ValidationError(
                        {"detail": f"Vui lòng đợi {wait_secs} giây trước khi đồng bộ lại organization này."}
                    )

        if client is None:
            owned_client = CvatClient(organization=project.cvat_org_slug or None)
            client = owned_client
        remote_projects = _fetch_remote_org_tree(project, client, count_objects=count_objects)
        linked = _linked_users()
        annotator_ids = set(
            RoleAssignment.objects.filter(project=project, role=Role.ANNOTATOR).values_list("user_id", flat=True)
        )
        auth_actor = actor if actor and getattr(actor, "is_authenticated", False) else None
        now = timezone.now()
        summary: dict[str, Any] = {
            "projects": 0,
            "projects_created": 0,
            "tasks": 0,
            "tasks_created": 0,
            "jobs_created": 0,
            "jobs_updated": 0,
        }
        seen_task_ids: set[int] = set()
        handled_missing_task_ids: set[int] = set()

        with transaction.atomic():
            for remote_project in sorted(remote_projects, key=lambda p: p.raw["id"]):
                summary["projects"] += 1
                if remote_project.skipped_foreign or remote_project.missing:
                    continue
                cvat_project = remote_project.raw
                dataset = (
                    Dataset.objects.select_for_update(of=("self",))
                    .filter(cvat_project_id=cvat_project["id"])
                    .first()
                )
                name = cvat_project.get("name") or f"Project {cvat_project['id']}"
                if dataset is None:
                    try:
                        with transaction.atomic():
                            dataset = Dataset.objects.create(
                                project=project,
                                name=name,
                                cvat_project_id=cvat_project["id"],
                                created_by=auth_actor,
                            )
                            summary["projects_created"] += 1
                    except IntegrityError:
                        dataset = (
                            Dataset.objects.select_for_update(of=("self",))
                            .filter(cvat_project_id=cvat_project["id"])
                            .first()
                        )
                        if dataset is None or dataset.project_id != project.id:
                            continue
                elif dataset.project_id != project.id:
                    continue

                dataset_active = dataset.status == DataStatus.ACTIVE
                if dataset_active:
                    dataset.name = name

                for remote_task in sorted(remote_project.tasks, key=lambda t: t.raw["id"]):
                    summary["tasks"] += 1
                    if remote_task.skipped_foreign:
                        continue
                    cvat_task = remote_task.raw
                    cvat_task_id = cvat_task["id"]
                    if remote_task.missing_error is not None:
                        handled_missing_task_ids.add(cvat_task_id)
                        missing_batch = (
                            Batch.objects.select_for_update(of=("self",))
                            .select_related("dataset")
                            .filter(project=project, cvat_task_id=cvat_task_id)
                            .first()
                        )
                        if missing_batch is not None:
                            summary["jobs_updated"] += _mark_batch_source_missing(
                                missing_batch, now=now, error_msg=remote_task.missing_error
                            )
                        continue

                    seen_task_ids.add(cvat_task_id)
                    task = (
                        Batch.objects.select_for_update(of=("self",))
                        .select_related("dataset")
                        .filter(cvat_task_id=cvat_task_id)
                        .first()
                    )
                    task_name = cvat_task.get("name") or f"Task {cvat_task_id}"
                    if task is None:
                        if not dataset_active:
                            continue
                        try:
                            with transaction.atomic():
                                task = Batch.objects.create(
                                    project=project,
                                    dataset=dataset,
                                    name=task_name,
                                    cvat_task_id=cvat_task_id,
                                    created_by=auth_actor,
                                )
                                summary["tasks_created"] += 1
                        except IntegrityError:
                            task = (
                                Batch.objects.select_for_update(of=("self",))
                                .select_related("dataset")
                                .filter(cvat_task_id=cvat_task_id)
                                .first()
                            )
                            if task is None or task.project_id != project.id:
                                continue
                    elif task.project_id != project.id:
                        continue

                    batch_frozen = (
                        task.status != DataStatus.ACTIVE
                        or not dataset_active
                        or task.dataset.status != DataStatus.ACTIVE
                    )
                    if not batch_frozen:
                        prev_dataset_id = task.dataset_id
                        task.name = task_name
                        task.dataset = dataset
                        task.source_missing = False
                        task.last_synced_at = now
                        task.last_sync_status = Batch.SyncStatus.OK
                        task.last_sync_error = ""
                        task.save(
                            update_fields=[
                                "name",
                                "dataset",
                                "source_missing",
                                "last_synced_at",
                                "last_sync_status",
                                "last_sync_error",
                            ]
                        )
                        if prev_dataset_id != dataset.id:
                            Job.objects.filter(batch=task).exclude(dataset=dataset).update(dataset=dataset)

                    locked_jobs = {
                        j.cvat_job_id: j
                        for j in Job.objects.select_for_update(of=("self",))
                        .select_related("project", "batch", "dataset", "annotator", "qc1_reviewer")
                        .filter(cvat_job_id__in=[rj.payload.id for rj in remote_task.jobs])
                        .order_by("id")
                    }

                    seen_job_ids: set[int] = set()
                    for remote_job in remote_task.jobs:
                        cvat_job = remote_job.payload
                        if remote_job.missing:
                            missing_job = locked_jobs.get(cvat_job.id)
                            if (
                                missing_job is not None
                                and missing_job.batch_id == task.id
                                and not missing_job.source_missing
                                and not missing_job.is_locked
                                and missing_job.status != JobStatus.DELIVERED
                                and not batch_frozen
                            ):
                                missing_job.source_missing = True
                                missing_job.save(update_fields=["source_missing", "updated_at"])
                                summary["jobs_updated"] += 1
                            continue

                        seen_job_ids.add(cvat_job.id)
                        job = locked_jobs.get(cvat_job.id)
                        if job is None:
                            if batch_frozen:
                                continue
                            job = _new_job(project, dataset, task, cvat_job, linked, annotator_ids)
                            created_here = False
                            try:
                                with transaction.atomic():
                                    job.save()
                                    created_here = True
                            except IntegrityError:
                                job = (
                                    Job.objects.select_for_update(of=("self",))
                                    .select_related("project", "batch", "dataset", "annotator", "qc1_reviewer")
                                    .filter(cvat_job_id=cvat_job.id)
                                    .first()
                                )
                            if job is None:
                                continue
                            if created_here:
                                if _apply_object_count(job, remote_job.object_count):
                                    job.save(
                                        update_fields=[
                                            "object_count",
                                            "last_counted_objects",
                                            "round_credited_objects",
                                            "updated_at",
                                        ]
                                    )
                                ActivityLog.record(
                                    project=project,
                                    actor=None,
                                    action="job.import",
                                    target=job,
                                    job=job,
                                    after={"status": job.status, "annotator": job.annotator_id},
                                    note="Nhập từ CVAT (đồng bộ organization)",
                                )
                                summary["jobs_created"] += 1
                            elif job.batch_id == task.id and _apply_cvat_state(
                                job, cvat_job, actor, object_count=remote_job.object_count, linked=linked
                            ):
                                summary["jobs_updated"] += 1
                        elif job.batch_id == task.id and _apply_cvat_state(
                            job, cvat_job, actor, object_count=remote_job.object_count, linked=linked
                        ):
                            summary["jobs_updated"] += 1

                        # Hybrid A2 gate: chỉ tạo lượt QC2 khi job đã thật sự ở PENDING_QC2 (không tạo cho QC1_PASSED).
                        if not _is_workflow_frozen(job) and job.status == JobStatus.PENDING_QC2:
                            ensure_qc2_sample(job)

                    if not batch_frozen:
                        # Các job của task này không còn xuất hiện trên CVAT → đánh dấu source_missing=True.
                        absent_jobs = (
                            task.jobs.select_for_update(of=("self",))
                            .filter(cvat_job_id__isnull=False, source_missing=False, is_locked=False)
                            .exclude(status=JobStatus.DELIVERED)
                            .exclude(cvat_job_id__in=seen_job_ids)
                            .order_by("id")
                        )
                        for absent_job in absent_jobs:
                            absent_job.source_missing = True
                            absent_job.save(update_fields=["source_missing", "updated_at"])
                            summary["jobs_updated"] += 1

                if dataset_active:
                    dataset.last_synced_at = now
                    dataset.save(update_fields=["name", "last_synced_at"])

            # Các task đã gắn CVAT của organization này nhưng không còn tồn tại trên CVAT → đánh dấu source_missing=True.
            absent_batches = (
                project.batches.select_for_update(of=("self",))
                .select_related("dataset")
                .filter(cvat_task_id__isnull=False)
                .exclude(status=DataStatus.DELIVERED)
                .exclude(cvat_task_id__in=seen_task_ids | handled_missing_task_ids)
                .order_by("id")
            )
            for absent_batch in absent_batches:
                summary["jobs_updated"] += _mark_batch_source_missing(
                    absent_batch,
                    now=now,
                    error_msg="CVAT task không còn tồn tại ở lần đồng bộ gần nhất.",
                )

            project.cvat_synced_at = now
            project.save(update_fields=["cvat_synced_at", "updated_at"])

        jobs = (
            project.jobs.filter(cvat_job_id__isnull=False)
            .select_related("project", "annotator__cvat_account", "qc1_reviewer__cvat_account")
            .prefetch_related(pending_samples_prefetch())
        )
        pushed = push_assignees(jobs, client, raise_on_error=False)
        summary.update(
            assignees_pushed=pushed["pushed"],
            waiting_link=pushed["waiting"],
            membership_warnings=pushed["warnings"],
        )
        if pushed.get("errors"):
            summary["assignee_error"] = "; ".join(pushed["errors"])
        return summary
    finally:
        if owned_client is not None:
            _close_quietly(owned_client)
        _release_advisory_lock(_SYNC_ORG_LOCK_NS, project.pk)


def import_task_jobs(batch: Batch, task_id: int, actor: Any, client: Any = None) -> dict[str, Any]:
    """Tạo Job VanoHub cho mọi annotation job của một CVAT Task. Job đã có thì cập nhật."""
    if batch.status != DataStatus.ACTIVE or batch.dataset.status != DataStatus.ACTIVE:
        raise ValidationError("Batch hoặc Dataset đã khoá hoặc đã bàn giao.")
    if Batch.objects.filter(cvat_task_id=task_id).exclude(pk=batch.pk).exists():
        raise ValidationError({"cvat_task_id": f"CVAT task {task_id} đã được gắn với một batch khác."})

    project = batch.dataset.project
    owned_client: Any = None
    try:
        if client is None:
            owned_client = CvatClient(organization=project.cvat_org_slug or None)
            client = owned_client
        task = _parse_task(client.get_task(task_id))
        if (
            batch.dataset.cvat_project_id
            and task.project_id is not None
            and task.project_id != batch.dataset.cvat_project_id
        ):
            raise ValidationError(
                {
                    "cvat_task_id": (
                        f"CVAT task {task_id} thuộc CVAT project {task.project_id}, "
                        f"không khớp dự án hiện tại ({batch.dataset.cvat_project_id})."
                    )
                }
            )

        cvat_jobs = [j for j in (_parse_job(raw) for raw in client.list_task_jobs(task_id)) if _is_annotation_job(j)]
        linked = _linked_users()
        annotator_ids = set(
            RoleAssignment.objects.filter(project=project, role=Role.ANNOTATOR).values_list("user_id", flat=True)
        )
        created = updated = 0

        with transaction.atomic():
            locked_batch = (
                Batch.objects.select_for_update(of=("self",))
                .select_related("dataset__project")
                .get(pk=batch.pk)
            )
            if locked_batch.status != DataStatus.ACTIVE or locked_batch.dataset.status != DataStatus.ACTIVE:
                raise ValidationError("Batch hoặc Dataset đã khoá hoặc đã bàn giao.")
            if Batch.objects.filter(cvat_task_id=task_id).exclude(pk=locked_batch.pk).exists():
                raise ValidationError({"cvat_task_id": f"CVAT task {task_id} đã được gắn với một batch khác."})

            locked_batch.cvat_task_id = task_id
            locked_batch.source_missing = False
            locked_batch.last_synced_at = timezone.now()
            locked_batch.last_sync_status = Batch.SyncStatus.OK
            locked_batch.last_sync_error = ""
            try:
                with transaction.atomic():
                    locked_batch.save(
                        update_fields=[
                            "cvat_task_id",
                            "source_missing",
                            "last_synced_at",
                            "last_sync_status",
                            "last_sync_error",
                        ]
                    )
            except IntegrityError as exc:
                raise ValidationError({"cvat_task_id": f"CVAT task {task_id} đã được gắn với một batch khác."}) from exc

            locked_jobs = {
                j.cvat_job_id: j
                for j in Job.objects.select_for_update(of=("self",))
                .select_related("project", "batch", "dataset", "annotator", "qc1_reviewer")
                .filter(cvat_job_id__in=[cj.id for cj in cvat_jobs])
                .order_by("id")
            }
            for cvat_job in cvat_jobs:
                job = locked_jobs.get(cvat_job.id)
                if job is None:
                    job = _new_job(project, locked_batch.dataset, locked_batch, cvat_job, linked, annotator_ids)
                    job.name = f"{task.name or 'task'} · job {cvat_job.id}"
                    created_here = False
                    try:
                        with transaction.atomic():
                            job.save()
                            created_here = True
                    except IntegrityError:
                        job = (
                            Job.objects.select_for_update(of=("self",))
                            .select_related("project", "batch", "dataset", "annotator", "qc1_reviewer")
                            .filter(cvat_job_id=cvat_job.id)
                            .first()
                        )
                    if job is None:
                        continue
                    if created_here:
                        ActivityLog.record(
                            project=project,
                            actor=actor,
                            action="job.import",
                            target=job,
                            job=job,
                            after={"status": job.status, "annotator": job.annotator_id},
                            note=f"Nhập từ CVAT task {task_id}",
                        )
                        created += 1
                    elif job.batch_id != locked_batch.id:
                        continue
                    elif _apply_cvat_state(job, cvat_job, actor, linked=linked):
                        updated += 1
                elif job.batch_id != locked_batch.id:
                    continue  # job thuộc batch khác → không động vào
                elif _apply_cvat_state(job, cvat_job, actor, linked=linked):
                    updated += 1

                if not _is_workflow_frozen(job) and job.status == JobStatus.PENDING_QC2:
                    ensure_qc2_sample(job)

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
    finally:
        if owned_client is not None:
            _close_quietly(owned_client)


def sync_batch(
    batch: Batch,
    actor: Any,
    client: Any = None,
    count_objects: bool = False,
) -> dict[str, Any]:
    """Đồng bộ lại trạng thái (và tùy chọn: số cuboid/object-frame) của các job trong một batch."""
    if not batch.cvat_task_id:
        return CvatSyncResult(updated=0, total=0).model_dump()
    if batch.status != DataStatus.ACTIVE or batch.dataset.status != DataStatus.ACTIVE:
        raise ValidationError("Batch hoặc Dataset đã khoá hoặc đã bàn giao.")

    project = batch.dataset.project
    owned_client: Any = None
    try:
        if client is None:
            owned_client = CvatClient(organization=project.cvat_org_slug or None)
            client = owned_client
        try:
            parsed_jobs = [
                j
                for j in (_parse_job(raw) for raw in client.list_task_jobs(batch.cvat_task_id))
                if _is_annotation_job(j)
            ]
        except CvatNotFoundError as exc:
            now = timezone.now()
            with transaction.atomic():
                locked_batch = (
                    Batch.objects.select_for_update(of=("self",))
                    .select_related("dataset")
                    .get(pk=batch.pk)
                )
                _mark_batch_source_missing(locked_batch, now=now, error_msg=str(exc))
            raise

        by_id = {j.id: j for j in parsed_jobs}
        linked = _linked_users()

        # Thực hiện toàn bộ HTTP I/O đếm object NGOÀI transaction.atomic(); 404 theo từng job không làm vỡ cả batch.
        fetched_counts: dict[int, int] = {}
        missing_job_ids: set[int] = set()
        if count_objects:
            existing_cvat_ids = list(
                batch.jobs.filter(cvat_job_id__isnull=False).values_list("cvat_job_id", flat=True)
            )
            for cjid in existing_cvat_ids:
                if cjid not in by_id:
                    continue
                try:
                    fetched_counts[cjid] = _count_job_objects_safe(client, by_id[cjid])
                except CvatNotFoundError:
                    missing_job_ids.add(cjid)

        updated = 0
        with transaction.atomic():
            locked_batch = (
                Batch.objects.select_for_update(of=("self",))
                .select_related("dataset__project")
                .get(pk=batch.pk)
            )
            if locked_batch.status != DataStatus.ACTIVE or locked_batch.dataset.status != DataStatus.ACTIVE:
                raise ValidationError("Batch hoặc Dataset đã khoá hoặc đã bàn giao.")

            jobs = (
                locked_batch.jobs.select_for_update(of=("self",))
                .select_related("project", "batch", "dataset", "annotator", "qc1_reviewer")
                .filter(cvat_job_id__isnull=False)
                .order_by("id")
            )
            for job in jobs:
                assert job.cvat_job_id is not None
                cvat_job = by_id.get(job.cvat_job_id)
                if cvat_job is None or job.cvat_job_id in missing_job_ids:
                    if not job.source_missing and not job.is_locked and job.status != JobStatus.DELIVERED:
                        job.source_missing = True
                        job.save(update_fields=["source_missing", "updated_at"])
                        updated += 1
                    continue

                obj_count = fetched_counts.get(job.cvat_job_id) if count_objects else None
                if _apply_cvat_state(job, cvat_job, actor, object_count=obj_count, linked=linked):
                    updated += 1

                if not _is_workflow_frozen(job) and job.status == JobStatus.PENDING_QC2:
                    ensure_qc2_sample(job)

            locked_batch.source_missing = False
            locked_batch.last_synced_at = timezone.now()
            locked_batch.last_sync_status = Batch.SyncStatus.OK
            locked_batch.last_sync_error = ""
            locked_batch.save(
                update_fields=["source_missing", "last_synced_at", "last_sync_status", "last_sync_error"]
            )

        batch.source_missing = locked_batch.source_missing
        batch.last_synced_at = locked_batch.last_synced_at
        batch.last_sync_status = locked_batch.last_sync_status
        batch.last_sync_error = locked_batch.last_sync_error
        return CvatSyncResult(updated=updated, total=len(by_id)).model_dump()
    finally:
        if owned_client is not None:
            _close_quietly(owned_client)


def dataset_labels(dataset: Dataset, client: Any = None) -> list[dict[str, Any]]:
    """Bộ nhãn của một CVAT project (Dataset) — chỉ đọc."""
    if not dataset.cvat_project_id:
        return []
    owned_client: Any = None
    try:
        if client is None:
            owned_client = CvatClient(organization=dataset.project.cvat_org_slug or None)
            client = owned_client
        return [
            {"id": label["id"], "name": label["name"], "color": label.get("color"), "type": label.get("type")}
            for label in client.list_project_labels(dataset.cvat_project_id)
        ]
    finally:
        if owned_client is not None:
            _close_quietly(owned_client)
