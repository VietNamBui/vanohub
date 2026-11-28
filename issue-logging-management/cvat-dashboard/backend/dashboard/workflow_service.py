"""
Transactional Django ORM workflow service backing the React dashboard (`frontend/`).
Mirrors every business rule in `frontend/src/mock/logic.ts` with ACID database persistence
and emits matching transactional `QcEvent` rows in the same `transaction.atomic()` block.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    Dimension,
    WorkflowAudit,
    WorkflowBatch,
    WorkflowBatchEvent,
    WorkflowBatchStatus,
    WorkflowDataset,
    WorkflowDataType,
    WorkflowJob,
    WorkflowJobEvent,
    WorkflowJobStage,
    WorkflowKpiDaily,
    WorkflowProject,
    WorkflowRole,
    WorkflowTeam,
    WorkflowUser,
)
from .qc_events import emit_workflow_qc_event

AUDIT_LEVELS = [100, 30, 10]
DISTRIBUTE_SEED = 7
ACTIVE_STAGES = {
    WorkflowJobStage.TEAM_POOL,
    WorkflowJobStage.ANNO_IN_PROGRESS,
    WorkflowJobStage.QC1_PENDING,
    WorkflowJobStage.QC1_IN_PROGRESS,
    WorkflowJobStage.QC2_PENDING,
    WorkflowJobStage.QC2_IN_PROGRESS,
    WorkflowJobStage.READY_TO_DELIVER,
}


class WorkflowError(ValueError):
    """Domain validation error surfaced as HTTP 400 with a Vietnamese message."""


class WorkflowValidationError(WorkflowError):
    """Input/schema validation error surfaced as HTTP 400."""


class WorkflowPermissionError(PermissionError):
    """Domain authorization error surfaced as HTTP 403 with a Vietnamese message."""


def is_supervisor_user(actor: WorkflowUser) -> bool:
    """Returns True if `actor` has admin, PM, Lead, or QC privileges."""
    return bool(actor.role in ("admin", "pm", "lead") or actor.is_qc)


def can_actor_qc(actor: WorkflowUser, job: WorkflowJob | None = None) -> bool:
    """Returns True if `actor` is allowed to perform QC1 / job assignment actions."""
    if actor.role in ("admin", "pm"):
        return True
    if job is not None:
        if job.team_id is None:
            return False
        in_team = (job.team is not None and job.team.lead_id == actor.id) or actor.teams.filter(id=job.team_id).exists()
        if not in_team:
            return False
        if actor.role == "lead" or actor.is_qc:
            return True
        return bool(job.team and job.team.can_qa)
    if actor.role == "lead" or actor.is_qc:
        return True
    return actor.teams.filter(can_qa=True).exists()


def can_actor_audit(actor: WorkflowUser) -> bool:
    """Returns True if `actor` is allowed to perform QC2 / Audit actions (`pm`, `admin`, or member/lead of a `can_qa` team)."""
    if actor.role in ("admin", "pm"):
        return True
    return actor.teams.filter(can_qa=True).exists() or actor.led_teams.filter(can_qa=True).exists()


def _require_pm_or_admin(actor: WorkflowUser, what: str) -> None:
    if actor.role not in ("admin", "pm"):
        raise WorkflowPermissionError(f"Bạn không có quyền {what} (chỉ PM hoặc Admin)")


def _require_lead_pm_or_admin(actor: WorkflowUser, what: str, team: WorkflowTeam | None = None) -> None:
    if actor.role in ("admin", "pm"):
        return
    if actor.role == "lead" and (
        team is None or team.lead_id == actor.id or actor.teams.filter(id=team.id).exists()
    ):
        return
    raise WorkflowPermissionError(f"Bạn không có quyền {what} (chỉ Team Lead, PM hoặc Admin)")


def _require_qc_permission(actor: WorkflowUser, job: WorkflowJob, what: str) -> None:
    if not can_actor_qc(actor, job):
        raise WorkflowPermissionError(f"Bạn không có quyền {what} (cần quyền QC / Team Lead / PM / Admin)")


def _require_audit_permission(actor: WorkflowUser, what: str) -> None:
    if not can_actor_audit(actor):
        raise WorkflowPermissionError(f"Bạn không có quyền {what} (cần quyền QC2 / Audit / PM / Admin)")


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: str | None) -> datetime | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise WorkflowError("Thời gian không hợp lệ")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkflowError("Thời gian không hợp lệ") from exc
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _mulberry32_shuffle(items: list[Any], seed: int) -> list[Any]:
    """Matches frontend `seededShuffle` (mulberry32 PRNG) so preview & commit are deterministic."""
    a = seed & 0xFFFFFFFF

    def _next_rand() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (a | 1)) & 0xFFFFFFFF
        t = (t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    out = list(items)
    for i in range(len(out) - 1, 0, -1):
        j = int(math.floor(_next_rand() * (i + 1)))
        out[i], out[j] = out[j], out[i]
    return out


def _next_code(model: Any, prefix: str, pad: int = 0) -> str:
    last = model.objects.order_by("-id").only("id").first()
    seq = (last.id if last else 0) + 1
    while True:
        code = f"{prefix}{seq:0{pad}d}" if pad else f"{prefix}{seq}"
        if not model.objects.filter(code=code).exists():
            return code
        seq += 1


def _create_with_code(model: Any, prefix: str, pad: int = 0, **kwargs: Any) -> Any:
    """Creates a model instance with a generated `code`, retrying on concurrent `IntegrityError`."""
    for attempt in range(5):
        code = _next_code(model, prefix, pad) if attempt == 0 else f"{prefix}_{uuid.uuid4().hex[:12]}"
        try:
            with transaction.atomic():
                return model.objects.create(code=code, **kwargs)
        except IntegrityError:
            if attempt == 4:
                raise
    raise RuntimeError("Unreachable")


def _is_batch_locked(batch: WorkflowBatch, now: datetime) -> bool:
    return batch.auto_lock_at is not None and batch.auto_lock_at < now


def _require_unlocked(job: WorkflowJob, now: datetime) -> None:
    if _is_batch_locked(job.batch, now):
        raise WorkflowError("Batch đã bị khoá")


def _require_stage(job: WorkflowJob, allowed: set[str], what: str) -> None:
    if job.stage not in allowed:
        raise WorkflowError(f'Không thể {what}: job {job.code} đang ở bước "{job.stage}"')


def _require_reason(reason: str, error_category: str) -> tuple[str, str]:
    r = str(reason or "").strip()
    cat = str(error_category or "").strip()
    if not r:
        raise WorkflowError("Bắt buộc nhập lý do trả về")
    if not cat:
        raise WorkflowError("Bắt buộc chọn loại lỗi")
    return r, cat


def _find_job(job_code: str, *, lock: bool = True) -> WorkflowJob:
    qs = WorkflowJob.objects.select_related("batch", "project", "team", "annotator", "qc1", "qc2")
    if lock:
        qs = qs.select_for_update()
    job = qs.filter(code=job_code).first()
    if job is None:
        raise WorkflowError(f"Không tìm thấy job {job_code}")
    return job


def _find_batch(batch_code: str, *, lock: bool = True) -> WorkflowBatch:
    qs = WorkflowBatch.objects.select_related("dataset", "project")
    if lock:
        qs = qs.select_for_update()
    batch = qs.filter(code=batch_code).first()
    if batch is None:
        raise WorkflowError(f"Không tìm thấy batch {batch_code}")
    return batch


def _find_team(team_code: str, *, lock: bool = True) -> WorkflowTeam:
    qs = WorkflowTeam.objects.select_related("lead")
    if lock:
        qs = qs.select_for_update()
    team = qs.filter(code=team_code).first()
    if team is None:
        raise WorkflowError(f"Không tìm thấy team {team_code}")
    return team


def _find_user(user_code: str) -> WorkflowUser:
    user = WorkflowUser.objects.filter(code=user_code).first()
    if user is None:
        raise WorkflowError(f"Không tìm thấy người dùng {user_code}")
    return user


def _find_audit(audit_code: str, *, lock: bool = True) -> WorkflowAudit:
    qs = WorkflowAudit.objects.select_related("project", "created_by")
    if lock:
        qs = qs.select_for_update()
    audit = qs.filter(code=audit_code).first()
    if audit is None:
        raise WorkflowError(f"Không tìm thấy audit {audit_code}")
    return audit


def _append_batch_event(batch: WorkflowBatch, actor: WorkflowUser, ev_type: str, detail: str, at: datetime) -> None:
    _create_with_code(
        WorkflowBatchEvent,
        "be",
        4,
        batch=batch,
        at=at,
        actor=actor,
        actor_code=actor.code,
        type=ev_type,
        detail=detail,
    )


def _append_job_event(
    job: WorkflowJob,
    actor: WorkflowUser,
    ev_type: str,
    from_stage: str | None,
    to_stage: str,
    at: datetime,
    *,
    reason: str = "",
    error_category: str = "",
    rework_against: list[str] | None = None,
) -> WorkflowJobEvent:
    return _create_with_code(
        WorkflowJobEvent,
        "ev",
        5,
        job=job,
        at=at,
        actor=actor,
        actor_code=actor.code,
        type=ev_type,
        from_stage=from_stage,
        to_stage=to_stage,
        reason=reason,
        error_category=error_category,
        rework_against=rework_against or [],
    )


def _next_audit_level_index(project: WorkflowProject) -> int:
    last = (
        WorkflowAudit.objects.filter(project=project)
        .exclude(status=WorkflowAudit.Status.OPEN)
        .order_by("created_at", "code")
        .last()
    )
    if last is None or last.status == WorkflowAudit.Status.FAILED:
        return 0
    return min(last.current_level_index + 1, len(AUDIT_LEVELS) - 1)


# ==============================================================================
# Serialization (Matches `frontend/src/mock/types.ts` DashboardState 1-to-1)
# ==============================================================================


_REDACTED_PARTNER: dict[str, str] = {"name": "", "contact": "", "email": "", "contractNote": ""}


def serialize_dashboard_state(current_user: WorkflowUser) -> dict[str, Any]:
    now = timezone.now()
    role = current_user.role
    is_global = role in (WorkflowRole.ADMIN, WorkflowRole.PM, "admin", "pm")
    is_lead = role in (WorkflowRole.LEAD, "lead")

    if is_global:
        teams_qs = list(WorkflowTeam.objects.select_related("lead", "pm").prefetch_related("members").all())
        users_qs = list(WorkflowUser.objects.all())
        projects_qs = list(WorkflowProject.objects.select_related("data_type").prefetch_related("pms", "teams").all())
        datasets_qs = list(WorkflowDataset.objects.select_related("data_type", "project").all())
        batches_qs = list(WorkflowBatch.objects.select_related("dataset", "project", "team").all())
        batch_events_qs = list(WorkflowBatchEvent.objects.select_related("batch", "actor").all())
        jobs_qs = list(WorkflowJob.objects.select_related("batch", "project", "team", "annotator", "qc1", "qc2").all())
        events_qs = list(WorkflowJobEvent.objects.select_related("job", "actor").all())
        audits_qs = list(WorkflowAudit.objects.select_related("created_by", "project").all())
        kpi_daily_qs = list(WorkflowKpiDaily.objects.select_related("user").all())
    elif is_lead:
        teams_qs = list(
            WorkflowTeam.objects.filter(Q(lead=current_user) | Q(members=current_user))
            .select_related("lead", "pm")
            .prefetch_related("members")
            .distinct()
        )
        my_team_ids = {t.id for t in teams_qs}
        jobs_qs = list(
            WorkflowJob.objects.select_related("batch", "project", "team", "annotator", "qc1", "qc2")
            .filter(
                Q(team_id__in=my_team_ids)
                | Q(annotator=current_user)
                | Q(qc1=current_user)
                | Q(qc2=current_user)
            )
            .distinct()
        )
        visible_job_ids = {j.id for j in jobs_qs}
        visible_batch_ids = {j.batch_id for j in jobs_qs}
        batches_qs = list(
            WorkflowBatch.objects.select_related("dataset", "project", "team")
            .filter(Q(id__in=visible_batch_ids) | Q(team_id__in=my_team_ids))
            .distinct()
        )
        visible_batch_ids = {b.id for b in batches_qs}
        visible_dataset_ids = {b.dataset_id for b in batches_qs}
        visible_project_ids = {b.project_id for b in batches_qs} | {j.project_id for j in jobs_qs}
        datasets_qs = list(
            WorkflowDataset.objects.select_related("data_type", "project").filter(id__in=visible_dataset_ids)
        )
        projects_qs = list(
            WorkflowProject.objects.select_related("data_type")
            .prefetch_related("pms", "teams")
            .filter(Q(id__in=visible_project_ids) | Q(teams__id__in=my_team_ids))
            .distinct()
        )
        team_member_ids = {m.id for t in teams_qs for m in t.members.all()} | {current_user.id}
        referenced_user_ids = set(team_member_ids)
        for t in teams_qs:
            if t.lead_id:
                referenced_user_ids.add(t.lead_id)
            if t.pm_id:
                referenced_user_ids.add(t.pm_id)
        for j in jobs_qs:
            for uid in (j.annotator_id, j.qc1_id, j.qc2_id):
                if uid:
                    referenced_user_ids.add(uid)
        users_qs = list(WorkflowUser.objects.filter(id__in=referenced_user_ids))
        events_qs = list(WorkflowJobEvent.objects.select_related("job", "actor").filter(job_id__in=visible_job_ids))
        batch_events_qs = list(
            WorkflowBatchEvent.objects.select_related("batch", "actor").filter(batch_id__in=visible_batch_ids)
        )
        audits_qs = (
            list(
                WorkflowAudit.objects.select_related("created_by", "project").filter(
                    project_id__in={p.id for p in projects_qs}
                )
            )
            if can_actor_audit(current_user)
            else []
        )
        kpi_daily_qs = list(WorkflowKpiDaily.objects.select_related("user").filter(user_id__in=team_member_ids))
    else:
        # Annotator (or any lower-privilege role): strictly scope to own jobs/data
        teams_qs = list(
            WorkflowTeam.objects.filter(members=current_user)
            .select_related("lead", "pm")
            .prefetch_related("members")
            .distinct()
        )
        my_team_ids = {t.id for t in teams_qs}
        can_qa_team_ids = {t.id for t in teams_qs if t.can_qa}
        job_q = Q(annotator=current_user)
        if current_user.is_qc:
            job_q |= Q(qc1=current_user)
        if can_qa_team_ids:
            job_q |= Q(qc2=current_user) | Q(team_id__in=can_qa_team_ids)
        jobs_qs = list(
            WorkflowJob.objects.select_related("batch", "project", "team", "annotator", "qc1", "qc2")
            .filter(job_q)
            .distinct()
        )
        visible_job_ids = {j.id for j in jobs_qs}
        visible_batch_ids = {j.batch_id for j in jobs_qs}
        batches_qs = list(
            WorkflowBatch.objects.select_related("dataset", "project", "team").filter(id__in=visible_batch_ids)
        )
        visible_dataset_ids = {b.dataset_id for b in batches_qs}
        visible_project_ids = {b.project_id for b in batches_qs} | {j.project_id for j in jobs_qs}
        datasets_qs = list(
            WorkflowDataset.objects.select_related("data_type", "project").filter(id__in=visible_dataset_ids)
        )
        projects_qs = list(
            WorkflowProject.objects.select_related("data_type")
            .prefetch_related("pms", "teams")
            .filter(Q(id__in=visible_project_ids) | Q(teams__id__in=my_team_ids))
            .distinct()
        )
        referenced_user_ids = {current_user.id}
        for j in jobs_qs:
            for uid in (j.annotator_id, j.qc1_id, j.qc2_id):
                if uid:
                    referenced_user_ids.add(uid)
        users_qs = list(WorkflowUser.objects.filter(id__in=referenced_user_ids))
        events_qs = list(WorkflowJobEvent.objects.select_related("job", "actor").filter(job_id__in=visible_job_ids))
        batch_events_qs = []
        audits_qs = (
            list(
                WorkflowAudit.objects.select_related("created_by", "project").filter(
                    project_id__in={p.id for p in projects_qs}
                )
            )
            if can_qa_team_ids
            else []
        )
        kpi_daily_qs = list(WorkflowKpiDaily.objects.select_related("user").filter(user=current_user))

    user_team_codes: dict[int, list[str]] = {}
    team_member_codes: dict[int, list[str]] = {}
    for t in teams_qs:
        if is_global or is_lead:
            m_codes = [m.code for m in t.members.all()]
        else:
            m_codes = [current_user.code] if any(m.id == current_user.id for m in t.members.all()) else []
        team_member_codes[t.id] = m_codes
        for m in t.members.all():
            if is_global or is_lead or m.id == current_user.id:
                user_team_codes.setdefault(m.id, []).append(t.code)

    favorites: dict[str, list[str]] = {}
    users_data = []
    for u in users_qs:
        if (is_global or u.id == current_user.id) and u.favorites:
            favorites[u.code] = list(u.favorites)
        if not is_global and not is_lead and u.id != current_user.id:
            users_data.append({
                "id": u.code,
                "name": u.name,
                "cvatUsername": "",
                "role": u.role,
                "teamIds": [],
                "isQc": u.is_qc,
                "employeeId": 0,
            })
        else:
            users_data.append({
                "id": u.code,
                "name": u.name,
                "cvatUsername": u.cvat_username,
                "role": u.role,
                "teamIds": sorted(user_team_codes.get(u.id, [])),
                "isQc": u.is_qc,
                "employeeId": u.employee_id,
            })

    teams_data = [
        {
            "id": t.code,
            "name": t.name,
            "leadId": t.lead.code if t.lead else "",
            "pmId": t.pm.code if t.pm else "",
            "memberIds": team_member_codes.get(t.id, []),
            "allowedSteps": list(t.allowed_steps or []),
            "canQa": t.can_qa,
        }
        for t in teams_qs
    ]

    data_types_data = [
        {
            "id": dt.code,
            "name": dt.name,
            "shapeType": dt.shape_type,
            "kpiPerDay": dt.kpi_per_day,
            "thresholdCm": dt.threshold_cm,
            "thresholdDeg": dt.threshold_deg,
            "errorCategories": list(dt.error_categories or []),
        }
        for dt in WorkflowDataType.objects.all()
    ]

    projects_data = []
    for p in projects_qs:
        pm_codes = list(p.pm_order) if p.pm_order else [u.code for u in p.pms.all()]
        projects_data.append({
            "id": p.code,
            "name": p.name,
            "dataTypeId": p.data_type.code,
            "pmIds": pm_codes if is_global else [],
            "teamIds": [t.code for t in p.teams.all() if is_global or any(mt.id == t.id for mt in teams_qs)],
            "code": p.display_code or f"PRJ-{p.code.upper()}",
            "partner": (
                (p.partner or dict(_REDACTED_PARTNER))
                if is_global
                else dict(_REDACTED_PARTNER)
            ),
            "assignedAt": _iso(p.assigned_at),
            "dueAt": _iso(p.due_at),
            "status": p.status,
        })

    datasets_data = [
        {
            "id": d.code,
            "name": d.name,
            "nasPath": d.nas_path if is_global else "",
            "dataTypeId": d.data_type.code,
            "projectId": d.project.code,
            "fileCount": d.file_count,
            "frameCount": d.frame_count,
            "status": d.status,
            "receivedAt": _iso(d.received_at),
            "lastDistributedAt": _iso(d.last_distributed_at),
            "dueAt": _iso(d.due_at),
            "preprocessedPct": d.preprocessed_pct,
            "onCvatPct": d.on_cvat_pct,
            "sceneCount": d.scene_count,
            "partnerNote": d.partner_note if is_global else "",
        }
        for d in datasets_qs
    ]

    batches_data = [
        {
            "id": b.code,
            "name": b.name,
            "datasetId": b.dataset.code,
            "projectId": b.project.code,
            "teamId": b.team.code if b.team else None,
            "cvatTaskId": b.cvat_task_id,
            "status": b.status,
            "stepPic": b.step_pic or {},
            "autoLockAt": _iso(b.auto_lock_at),
            "dueAt": _iso(b.due_at),
            "stepBufferDays": b.step_buffer_days or {"qc1": 1, "qc2": 1},
            "priority": b.priority,
        }
        for b in batches_qs
    ]

    batch_events_data = [
        {
            "id": be.code,
            "batchId": be.batch.code,
            "at": _iso(be.at),
            "actorId": be.actor.code if be.actor else be.actor_code,
            "type": be.type,
            "detail": be.detail,
        }
        for be in batch_events_qs
    ]

    jobs_data = []
    for j in jobs_qs:
        item: dict[str, Any] = {
            "id": j.code,
            "cvatJobId": j.cvat_job_id,
            "batchId": j.batch.code,
            "projectId": j.project.code,
            "teamId": j.team.code if j.team else None,
            "annotatorId": j.annotator.code if j.annotator else None,
            "qc1Id": j.qc1.code if j.qc1 else None,
            "qc2Id": j.qc2.code if j.qc2 else None,
            "stage": j.stage,
            "prelabelCuboids": j.prelabel_cuboids,
            "editedCuboids": j.edited_cuboids,
            "frames": j.frames,
            "reworkCount": j.rework_count,
            "firstSubmittedAt": _iso(j.first_submitted_at),
        }
        if j.cvat_drift:
            item["cvatDrift"] = j.cvat_drift
        if j.due:
            item["due"] = j.due
        jobs_data.append(item)

    events_data = []
    for ev in events_qs:
        row: dict[str, Any] = {
            "id": ev.code,
            "jobId": ev.job.code,
            "at": _iso(ev.at),
            "actorId": ev.actor.code if ev.actor else ev.actor_code,
            "type": ev.type,
            "fromStage": ev.from_stage,
            "toStage": ev.to_stage,
        }
        if ev.reason:
            row["reason"] = ev.reason
        if ev.error_category:
            row["errorCategory"] = ev.error_category
        if ev.rework_against:
            row["reworkAgainst"] = list(ev.rework_against)
        events_data.append(row)

    audits_data = [
        {
            "id": a.code,
            "createdAt": _iso(a.created_at),
            "createdBy": a.created_by.code if a.created_by else "",
            "projectId": a.project.code,
            "batchIds": list(a.batch_codes or []),
            "levels": list(a.levels or AUDIT_LEVELS),
            "currentLevelIndex": a.current_level_index,
            "percent": a.percent,
            "sampledJobIds": list(a.sampled_job_codes or []),
            "results": dict(a.results or {}),
            "status": a.status,
            "closedAt": _iso(a.closed_at),
        }
        for a in audits_qs
    ]

    kpi_daily_data = [
        {
            "userId": k.user.code,
            "date": k.date.isoformat(),
            "editedCuboids": k.edited_cuboids,
        }
        for k in kpi_daily_qs
    ]

    return {
        "schemaVersion": 2,
        "users": users_data,
        "teams": teams_data,
        "dataTypes": data_types_data,
        "projects": projects_data,
        "datasets": datasets_data,
        "batches": batches_data,
        "batchEvents": batch_events_data,
        "jobs": jobs_data,
        "events": events_data,
        "audits": audits_data,
        "kpiDaily": kpi_daily_data,
        "favorites": favorites,
        "currentUserId": current_user.code,
        "now": _iso(now),
        "datasetPreset": "default",
    }


# ==============================================================================
# Distribution Preview
# ==============================================================================


def preview_distribution(batch_code: str, team_codes: list[str], seed: int = DISTRIBUTE_SEED) -> list[dict[str, Any]]:
    rows = [{"teamId": tid, "jobIds": [], "jobCount": 0, "totalCuboids": 0} for tid in team_codes]
    if not rows:
        return rows
    pool = list(
        WorkflowJob.objects.filter(batch__code=batch_code, stage=WorkflowJobStage.UNASSIGNED_POOL).order_by("code")
    )
    shuffled = _mulberry32_shuffle(pool, seed)
    ordered = sorted(shuffled, key=lambda j: j.prelabel_cuboids, reverse=True)
    for job in ordered:
        min_count = min(r["jobCount"] for r in rows)
        candidates = [r for r in rows if r["jobCount"] == min_count]
        target = min(candidates, key=lambda r: r["totalCuboids"])
        target["jobIds"].append(job.code)
        target["jobCount"] += 1
        target["totalCuboids"] += job.prelabel_cuboids
    return rows


# ==============================================================================
# Transactional Job Actions
# ==============================================================================


@transaction.atomic
def assign_job(actor: WorkflowUser, job_code: str, annotator_code: str, qc1_code: str) -> None:
    now = timezone.now()
    job = _find_job(job_code)
    _require_qc_permission(actor, job, "giao job")
    _require_stage(job, {WorkflowJobStage.TEAM_POOL}, "giao job")
    ann = _find_user(annotator_code)
    qc1 = _find_user(qc1_code)
    old_stage = job.stage
    job.annotator = ann
    job.qc1 = qc1
    job.stage = WorkflowJobStage.ANNO_IN_PROGRESS
    job.save(update_fields=["annotator", "qc1", "stage"])
    _append_job_event(job, actor, "assign", old_stage, job.stage, now)
    emit_workflow_qc_event(
        job=job,
        event_type="job_assigned",
        actor=actor,
        params={"annotator": ann.cvat_username, "qc1": qc1.cvat_username},
        at=now,
    )


@transaction.atomic
def reassign_job(
    actor: WorkflowUser,
    job_code: str,
    *,
    annotator_code: str | None = None,
    qc1_code: str | None = None,
) -> None:
    now = timezone.now()
    if annotator_code is None and qc1_code is None:
        raise WorkflowError("Cần chọn annotator hoặc QC1 mới")
    job = _find_job(job_code)
    _require_qc_permission(actor, job, "đổi người phụ trách job")
    update_fields: list[str] = []
    if annotator_code is not None:
        job.annotator = _find_user(annotator_code) if annotator_code else None
        update_fields.append("annotator")
    if qc1_code is not None:
        job.qc1 = _find_user(qc1_code) if qc1_code else None
        update_fields.append("qc1")
    job.save(update_fields=update_fields)
    _append_job_event(job, actor, "reassign", job.stage, job.stage, now)
    emit_workflow_qc_event(
        job=job,
        event_type="job_reassigned",
        actor=actor,
        params={"annotator_id": annotator_code, "qc1_id": qc1_code},
        at=now,
    )


@transaction.atomic
def submit_job(actor: WorkflowUser, job_code: str, edited_cuboids: int | None = None) -> None:
    now = timezone.now()
    job = _find_job(job_code)
    if (
        actor.role == "annotator"
        and not actor.is_qc
        and job.annotator_id is not None
        and job.annotator_id != actor.id
    ):
        raise WorkflowPermissionError("Bạn chỉ có thể nộp job được giao cho mình")
    _require_unlocked(job, now)
    _require_stage(job, {WorkflowJobStage.ANNO_IN_PROGRESS}, "nộp job")
    old_stage = job.stage
    is_first = job.first_submitted_at is None
    job.stage = WorkflowJobStage.QC1_PENDING
    update_fields = ["stage"]
    if is_first:
        if edited_cuboids is not None:
            if isinstance(edited_cuboids, bool) or not isinstance(edited_cuboids, int) or edited_cuboids < 0:
                raise WorkflowValidationError("Số cuboid đã sửa phải là số nguyên không âm")
            job.edited_cuboids = edited_cuboids
        else:
            job.edited_cuboids = round(job.prelabel_cuboids * 0.4)
        job.first_submitted_at = now
        update_fields.extend(["edited_cuboids", "first_submitted_at"])
    job.save(update_fields=update_fields)

    _append_job_event(job, actor, "submit" if is_first else "resubmit", old_stage, job.stage, now)
    if is_first and job.annotator_id:
        kpi, _ = WorkflowKpiDaily.objects.select_for_update().get_or_create(
            user_id=job.annotator_id,
            date=now.date(),
            defaults={"edited_cuboids": 0},
        )
        kpi.edited_cuboids += job.edited_cuboids
        kpi.save(update_fields=["edited_cuboids"])

    emit_workflow_qc_event(
        job=job,
        event_type="job_submitted",
        actor=actor,
        actor_role="annotator",
        params={"first_submit": is_first, "edited_cuboids": job.edited_cuboids},
        at=now,
    )


@transaction.atomic
def start_qc1(actor: WorkflowUser, job_code: str) -> None:
    now = timezone.now()
    job = _find_job(job_code)
    _require_qc_permission(actor, job, "bắt đầu QC1")
    _require_unlocked(job, now)
    _require_stage(job, {WorkflowJobStage.QC1_PENDING}, "bắt đầu QC1")
    old_stage = job.stage
    job.stage = WorkflowJobStage.QC1_IN_PROGRESS
    job.save(update_fields=["stage"])
    _append_job_event(job, actor, "qc1_start", old_stage, job.stage, now)
    emit_workflow_qc_event(job=job, event_type="qc1_started", actor=actor, actor_role="l1_qc", at=now)


@transaction.atomic
def qc1_pass(actor: WorkflowUser, job_code: str) -> None:
    now = timezone.now()
    job = _find_job(job_code)
    _require_qc_permission(actor, job, "duyệt QC1")
    _require_unlocked(job, now)
    _require_stage(job, {WorkflowJobStage.QC1_PENDING, WorkflowJobStage.QC1_IN_PROGRESS}, "duyệt QC1")
    old_stage = job.stage
    job.stage = WorkflowJobStage.QC2_PENDING
    job.save(update_fields=["stage"])
    _append_job_event(job, actor, "qc1_pass", old_stage, job.stage, now)
    emit_workflow_qc_event(job=job, event_type="job_accepted_l1", actor=actor, actor_role="l1_qc", at=now)


@transaction.atomic
def qc1_return(actor: WorkflowUser, job_code: str, reason: str, error_category: str) -> None:
    now = timezone.now()
    job = _find_job(job_code)
    _require_qc_permission(actor, job, "trả về từ QC1")
    _require_unlocked(job, now)
    _require_stage(job, {WorkflowJobStage.QC1_PENDING, WorkflowJobStage.QC1_IN_PROGRESS}, "trả về từ QC1")
    clean_reason, clean_cat = _require_reason(reason, error_category)
    old_stage = job.stage
    job.stage = WorkflowJobStage.ANNO_IN_PROGRESS
    job.rework_count += 1
    job.save(update_fields=["stage", "rework_count"])
    against = [job.annotator.code] if job.annotator else []
    _append_job_event(
        job,
        actor,
        "qc1_return",
        old_stage,
        job.stage,
        now,
        reason=clean_reason,
        error_category=clean_cat,
        rework_against=against,
    )
    emit_workflow_qc_event(
        job=job,
        event_type="job_returned_for_rework",
        actor=actor,
        actor_role="l1_qc",
        defect_code=clean_cat,
        params={"from_step": "l1_qc", "to_step": "annotator", "reason": clean_reason, "error_category": clean_cat},
        at=now,
    )


@transaction.atomic
def start_qc2(actor: WorkflowUser, job_code: str) -> None:
    now = timezone.now()
    _require_audit_permission(actor, "bắt đầu QC2")
    job = _find_job(job_code)
    _require_unlocked(job, now)
    _require_stage(job, {WorkflowJobStage.QC2_PENDING}, "bắt đầu QC2")
    old_stage = job.stage
    job.qc2 = actor
    job.stage = WorkflowJobStage.QC2_IN_PROGRESS
    job.save(update_fields=["qc2", "stage"])
    _append_job_event(job, actor, "qc2_start", old_stage, job.stage, now)
    emit_workflow_qc_event(job=job, event_type="qc2_started", actor=actor, actor_role="l2_qc", at=now)


@transaction.atomic
def qc2_pass(actor: WorkflowUser, job_code: str) -> None:
    now = timezone.now()
    _require_audit_permission(actor, "duyệt QC2 / Audit")
    job = _find_job(job_code)
    _require_unlocked(job, now)
    _require_stage(job, {WorkflowJobStage.QC2_PENDING, WorkflowJobStage.QC2_IN_PROGRESS}, "Audit")
    old_stage = job.stage
    job.qc2 = actor
    job.stage = WorkflowJobStage.READY_TO_DELIVER
    job.save(update_fields=["qc2", "stage"])
    _append_job_event(job, actor, "qc2_pass", old_stage, job.stage, now)
    emit_workflow_qc_event(job=job, event_type="job_completed_l2", actor=actor, actor_role="l2_qc", at=now)


@transaction.atomic
def qc2_return_to_qc1(actor: WorkflowUser, job_code: str, reason: str, error_category: str) -> None:
    now = timezone.now()
    _require_audit_permission(actor, "trả về QC1 từ QC2")
    job = _find_job(job_code)
    _require_unlocked(job, now)
    _require_stage(job, {WorkflowJobStage.QC2_PENDING, WorkflowJobStage.QC2_IN_PROGRESS}, "trả về QC1")
    clean_reason, clean_cat = _require_reason(reason, error_category)
    old_stage = job.stage
    job.qc2 = actor
    job.stage = WorkflowJobStage.QC1_IN_PROGRESS
    job.rework_count += 1
    job.save(update_fields=["qc2", "stage", "rework_count"])
    against = [job.qc1.code] if job.qc1 else []
    _append_job_event(
        job,
        actor,
        "qc2_return_qc1",
        old_stage,
        job.stage,
        now,
        reason=clean_reason,
        error_category=clean_cat,
        rework_against=against,
    )
    emit_workflow_qc_event(
        job=job,
        event_type="job_returned_for_rework",
        actor=actor,
        actor_role="l2_qc",
        defect_code=clean_cat,
        params={"from_step": "l2_qc", "to_step": "l1_qc", "reason": clean_reason, "error_category": clean_cat},
        at=now,
    )


@transaction.atomic
def qc2_return_to_anno(actor: WorkflowUser, job_code: str, reason: str, error_category: str) -> None:
    now = timezone.now()
    _require_audit_permission(actor, "trả thẳng annotator từ QC2")
    job = _find_job(job_code)
    _require_unlocked(job, now)
    _require_stage(job, {WorkflowJobStage.QC2_PENDING, WorkflowJobStage.QC2_IN_PROGRESS}, "trả thẳng annotator")
    clean_reason, clean_cat = _require_reason(reason, error_category)
    old_stage = job.stage
    job.qc2 = actor
    job.stage = WorkflowJobStage.ANNO_IN_PROGRESS
    job.rework_count += 1
    job.save(update_fields=["qc2", "stage", "rework_count"])
    against = [u.code for u in (job.annotator, job.qc1) if u is not None]
    _append_job_event(
        job,
        actor,
        "qc2_return_anno",
        old_stage,
        job.stage,
        now,
        reason=clean_reason,
        error_category=clean_cat,
        rework_against=against,
    )
    emit_workflow_qc_event(
        job=job,
        event_type="job_returned_for_rework",
        actor=actor,
        actor_role="l2_qc",
        defect_code=clean_cat,
        params={"from_step": "l2_qc", "to_step": "annotator", "reason": clean_reason, "error_category": clean_cat},
        at=now,
    )


@transaction.atomic
def mark_delivered(actor: WorkflowUser, job_codes: list[str]) -> None:
    now = timezone.now()
    _require_pm_or_admin(actor, "đánh dấu đã giao job")
    jobs = [_find_job(code) for code in job_codes]
    for j in jobs:
        _require_stage(j, {WorkflowJobStage.READY_TO_DELIVER}, "đánh dấu đã giao")
    touched_batches: set[int] = set()
    for j in jobs:
        old_stage = j.stage
        j.stage = WorkflowJobStage.DELIVERED
        j.save(update_fields=["stage"])
        touched_batches.add(j.batch_id)
        _append_job_event(j, actor, "deliver", old_stage, j.stage, now)
        emit_workflow_qc_event(job=j, event_type="job_delivered", actor=actor, at=now)

    for b in WorkflowBatch.objects.select_for_update().filter(id__in=touched_batches):
        if b.status in (WorkflowBatchStatus.READY, WorkflowBatchStatus.IN_PROGRESS) and not b.jobs.exclude(
            stage=WorkflowJobStage.DELIVERED
        ).exists():
            b.status = WorkflowBatchStatus.DELIVERED
            b.save(update_fields=["status"])


@transaction.atomic
def set_job_due(actor: WorkflowUser, job_code: str, step: str, due_at: str | None) -> None:
    now = timezone.now()
    job = _find_job(job_code)
    actor_teams = set(actor.teams.values_list("code", flat=True))
    allowed = actor.role in ("pm", "admin") or (
        actor.role == "lead" and job.team is not None and job.team.code in actor_teams
    )
    if not allowed:
        raise WorkflowError("Bạn không có quyền đổi hạn của job này")
    if job.stage == WorkflowJobStage.DELIVERED:
        raise WorkflowError("Job đã giao, không thể đổi hạn")
    if step not in ("annotate", "qc1", "qc2"):
        raise WorkflowError("Bước không hợp lệ")
    parsed = _parse_iso(due_at)
    due = dict(job.due or {})
    prev = due.get(step)
    new_iso = _iso(parsed)
    if prev == new_iso:
        return
    if new_iso is None:
        due.pop(step, None)
        reason = f"Bỏ hạn riêng {step}"
    else:
        due[step] = new_iso
        reason = f"Hạn {step}: {new_iso}"
    job.due = due
    job.save(update_fields=["due"])
    _append_job_event(job, actor, "due_override", job.stage, job.stage, now, reason=reason)


# ==============================================================================
# Transactional Batch Actions
# ==============================================================================


@transaction.atomic
def distribute_jobs(actor: WorkflowUser, batch_code: str, team_codes: list[str]) -> None:
    now = timezone.now()
    _require_pm_or_admin(actor, "chia job của batch")
    batch = _find_batch(batch_code)
    if batch.status != WorkflowBatchStatus.PENDING:
        raise WorkflowError("Batch đã được chia")
    if not team_codes:
        raise WorkflowError("Cần chọn ít nhất một team")
    teams = {t.code: t for t in WorkflowTeam.objects.filter(code__in=team_codes)}
    for tc in team_codes:
        if tc not in teams:
            raise WorkflowError(f"Không tìm thấy team {tc}")

    rows = preview_distribution(batch.code, team_codes)
    team_of = {jid: r["teamId"] for r in rows for jid in r["jobIds"]}
    if not team_of:
        raise WorkflowError("Batch không có job chưa chia")

    jobs = list(WorkflowJob.objects.select_for_update().filter(code__in=list(team_of.keys())))
    for job in jobs:
        t = teams[team_of[job.code]]
        old_stage = job.stage
        job.team = t
        job.stage = WorkflowJobStage.TEAM_POOL
        job.save(update_fields=["team", "stage"])
        _append_job_event(job, actor, "distribute", old_stage, job.stage, now)
        emit_workflow_qc_event(job=job, event_type="job_distributed", actor=actor, params={"team": t.code}, at=now)

    batch.project.teams.add(*teams.values())
    batch.dataset.last_distributed_at = now
    batch.dataset.save(update_fields=["last_distributed_at"])
    step_pic = dict(batch.step_pic or {})
    step_pic["annotate"] = list(team_codes)
    batch.status = WorkflowBatchStatus.IN_PROGRESS
    batch.step_pic = step_pic
    batch.save(update_fields=["status", "step_pic"])
    team_names = ", ".join(teams[tc].name for tc in team_codes)
    _append_batch_event(batch, actor, "distribute", f"Chia {len(jobs)} job cho {team_names}", now)


@transaction.atomic
def reassign_batch(actor: WorkflowUser, batch_code: str, step: str, pic_code: str) -> None:
    now = timezone.now()
    _require_pm_or_admin(actor, "đổi người phụ trách batch")
    batch = _find_batch(batch_code)
    if batch.status in (WorkflowBatchStatus.RELEASED, WorkflowBatchStatus.PENDING):
        raise WorkflowError("Batch chưa chia hoặc đã release, không thể đổi người phụ trách")
    if step not in ("annotate", "qc1", "qc2"):
        raise WorkflowError("Bước không hợp lệ")

    step_pic = dict(batch.step_pic or {})
    if step == "annotate":
        team = _find_team(pic_code, lock=False)
        step_pic["annotate"] = [team.code]
        WorkflowJob.objects.filter(batch=batch, stage=WorkflowJobStage.TEAM_POOL).update(team=team)
        label = team.name
    elif step == "qc1":
        user = _find_user(pic_code)
        step_pic["qc1"] = user.code
        WorkflowJob.objects.filter(
            batch=batch,
            stage__in=[
                WorkflowJobStage.TEAM_POOL,
                WorkflowJobStage.ANNO_IN_PROGRESS,
                WorkflowJobStage.QC1_PENDING,
                WorkflowJobStage.QC1_IN_PROGRESS,
            ],
        ).update(qc1=user)
        label = user.name
    else:
        user = _find_user(pic_code)
        step_pic["qc2"] = user.code
        WorkflowJob.objects.filter(
            batch=batch,
            stage__in=[WorkflowJobStage.QC2_PENDING, WorkflowJobStage.QC2_IN_PROGRESS],
        ).update(qc2=user)
        label = user.name

    batch.step_pic = step_pic
    batch.save(update_fields=["step_pic"])
    _append_batch_event(batch, actor, "reassign", f"Đổi {step} → {label}", now)


@transaction.atomic
def release_batch(actor: WorkflowUser, batch_code: str) -> None:
    now = timezone.now()
    _require_pm_or_admin(actor, "release batch")
    batch = _find_batch(batch_code)
    if batch.status == WorkflowBatchStatus.RELEASED:
        raise WorkflowError("Batch đã được release")
    if batch.status == WorkflowBatchStatus.IN_AUDIT:
        raise WorkflowError("Batch đang audit, không thể release")
    if batch.status == WorkflowBatchStatus.DELIVERED:
        raise WorkflowError("Batch đã giao, không thể release")
    gone_count = batch.jobs.count()
    batch.jobs.all().delete()
    batch.status = WorkflowBatchStatus.RELEASED
    batch.auto_lock_at = None
    batch.save(update_fields=["status", "auto_lock_at"])
    _append_batch_event(
        batch,
        actor,
        "release",
        f"Release batch: xoá {gone_count} job và annotation, trả dữ liệu về kho",
        now,
    )


@transaction.atomic
def set_auto_lock(actor: WorkflowUser, batch_code: str, auto_lock_at: str | None) -> None:
    now = timezone.now()
    _require_pm_or_admin(actor, "đặt khoá tự động batch")
    batch = _find_batch(batch_code)
    if batch.status == WorkflowBatchStatus.RELEASED:
        raise WorkflowError("Batch đã release")
    parsed = _parse_iso(auto_lock_at)
    ev_type = "autolock_set" if batch.auto_lock_at is None and parsed is not None else "autolock_reset"
    batch.auto_lock_at = parsed
    batch.save(update_fields=["auto_lock_at"])
    detail = "Gỡ khoá tự động" if parsed is None else f"Đặt khoá tự động lúc {_iso(parsed)}"
    _append_batch_event(batch, actor, ev_type, detail, now)


@transaction.atomic
def set_batch_due(
    actor: WorkflowUser,
    batch_code: str,
    due_at: str | None,
    step_buffer_days: dict[str, Any] | None = None,
) -> None:
    now = timezone.now()
    batch = _find_batch(batch_code)
    if actor.role not in ("pm", "admin"):
        raise WorkflowError("Bạn không có quyền đặt hạn giao batch (chỉ PM hoặc Admin)")
    if batch.status in (WorkflowBatchStatus.RELEASED, WorkflowBatchStatus.DELIVERED):
        raise WorkflowError("Batch đã giao hoặc đã release, không thể đổi hạn")
    parsed = _parse_iso(due_at)
    buf = step_buffer_days if isinstance(step_buffer_days, dict) else (batch.step_buffer_days or {"qc1": 1, "qc2": 1})
    try:
        qc1_b = float(buf.get("qc1", 1))
        qc2_b = float(buf.get("qc2", 1))
    except (TypeError, ValueError) as exc:
        raise WorkflowError("Số ngày đệm mỗi bước phải là số không âm") from exc
    if qc1_b < 0 or qc2_b < 0 or not math.isfinite(qc1_b) or not math.isfinite(qc2_b):
        raise WorkflowError("Số ngày đệm mỗi bước phải là số không âm")

    if batch.due_at == parsed and (batch.step_buffer_days or {}) == {"qc1": qc1_b, "qc2": qc2_b}:
        return
    batch.due_at = parsed
    batch.step_buffer_days = {"qc1": qc1_b, "qc2": qc2_b}
    batch.save(update_fields=["due_at", "step_buffer_days"])
    if parsed is None:
        _append_batch_event(batch, actor, "due_clear", "Bỏ hạn giao", now)
    else:
        _append_batch_event(batch, actor, "due_set", f"Đặt hạn giao {_iso(parsed)}", now)


@transaction.atomic
def set_batch_priority(actor: WorkflowUser, batch_code: str, priority: int) -> None:
    now = timezone.now()
    batch = _find_batch(batch_code)
    is_pm = actor.role == "pm" and batch.project.pms.filter(id=actor.id).exists()
    if actor.role != "admin" and not is_pm:
        raise WorkflowError("Bạn không có quyền đổi ưu tiên batch (chỉ PM của dự án hoặc Admin)")
    if batch.status == WorkflowBatchStatus.RELEASED:
        raise WorkflowError("Batch đã release, không thể đổi ưu tiên")
    if priority not in (1, 2, 3, 4, 5):
        raise WorkflowError("Mức ưu tiên phải từ 1 đến 5")
    if batch.priority == priority:
        return
    old_p = batch.priority
    batch.priority = priority
    batch.save(update_fields=["priority"])
    _append_batch_event(batch, actor, "priority_set", f"Đổi ưu tiên ★{old_p} → ★{priority}", now)


# ==============================================================================
# Transactional Audit Actions
# ==============================================================================


@transaction.atomic
def create_audit(actor: WorkflowUser, batch_codes: list[str], percent: int | None = None) -> WorkflowAudit:
    now = timezone.now()
    _require_audit_permission(actor, "tạo đợt audit QC2")
    if not batch_codes:
        raise WorkflowError("Cần chọn ít nhất một batch")
    batches = [_find_batch(bc) for bc in batch_codes]
    project_ids = {b.project_id for b in batches}
    if len(project_ids) > 1:
        raise WorkflowError("Các batch của một audit phải cùng dự án")
    for b in batches:
        if b.status != WorkflowBatchStatus.IN_PROGRESS:
            raise WorkflowError(f"Batch {b.name} không ở trạng thái chờ audit")

    eligible = list(
        WorkflowJob.objects.filter(batch__in=batches, stage=WorkflowJobStage.QC2_PENDING)
        .order_by("code")
        .values_list("code", flat=True)
    )
    if not eligible:
        raise WorkflowError("Không có job nào đã qua QC1 để lấy mẫu")

    project = batches[0].project
    level_index = _next_audit_level_index(project)
    if percent is None:
        eff_pct = AUDIT_LEVELS[level_index]
    else:
        if isinstance(percent, bool):
            raise WorkflowValidationError("Tỷ lệ audit phải là số nguyên từ 1 đến 100%")
        try:
            eff_pct = int(percent)
        except (TypeError, ValueError) as exc:
            raise WorkflowValidationError("Tỷ lệ audit phải là số nguyên từ 1 đến 100%") from exc
    if eff_pct < 1 or eff_pct > 100:
        raise WorkflowValidationError("Tỷ lệ audit phải là số nguyên từ 1 đến 100%")

    size = math.ceil((eff_pct / 100.0) * len(eligible))
    audit_count = WorkflowAudit.objects.count()
    sampled = _mulberry32_shuffle(eligible, 31 + audit_count)[:size]

    audit = _create_with_code(
        WorkflowAudit,
        "au",
        created_at=now,
        created_by=actor,
        project=project,
        batch_codes=list(batch_codes),
        levels=list(AUDIT_LEVELS),
        current_level_index=level_index,
        percent=eff_pct,
        sampled_job_codes=sampled,
        results={},
        status=WorkflowAudit.Status.OPEN,
    )
    audit.batches.set(batches)

    for b in batches:
        b.status = WorkflowBatchStatus.IN_AUDIT
        b.save(update_fields=["status"])
        _append_batch_event(
            b,
            actor,
            "audit_create",
            f"Tạo audit {audit.code} (mức {eff_pct}%, {len(sampled)}/{len(eligible)} job mẫu)",
            now,
        )
    return audit


def _require_audit_job(audit: WorkflowAudit, job_code: str) -> WorkflowJob:
    if audit.status != WorkflowAudit.Status.OPEN:
        raise WorkflowError("Audit đã kết thúc")
    if job_code not in (audit.sampled_job_codes or []):
        raise WorkflowError(f"Job {job_code} không thuộc mẫu của audit {audit.code}")
    if job_code in (audit.results or {}):
        raise WorkflowError(f"Job {job_code} đã được chấm")
    return _find_job(job_code)


@transaction.atomic
def audit_job_pass(actor: WorkflowUser, audit_code: str, job_code: str) -> None:
    now = timezone.now()
    _require_audit_permission(actor, "chấm đạt job mẫu audit")
    audit = _find_audit(audit_code)
    job = _require_audit_job(audit, job_code)
    _require_unlocked(job, now)
    results = dict(audit.results or {})
    results[job.code] = "passed"
    audit.results = results
    audit.save(update_fields=["results"])
    _append_batch_event(job.batch, actor, "audit_job_pass", f"Audit {audit.code}: job {job.code} đạt", now)
    emit_workflow_qc_event(
        job=job,
        event_type="audit_job_passed",
        actor=actor,
        actor_role="l2_qc",
        params={"audit_id": audit.code},
        at=now,
    )


@transaction.atomic
def audit_job_return(
    actor: WorkflowUser,
    audit_code: str,
    job_code: str,
    target: str,
    reason: str,
    error_category: str,
) -> None:
    now = timezone.now()
    _require_audit_permission(actor, "trả job mẫu audit")
    audit = _find_audit(audit_code)
    job = _require_audit_job(audit, job_code)
    if target == "qc1":
        qc2_return_to_qc1(actor, job.code, reason, error_category)
    else:
        qc2_return_to_anno(actor, job.code, reason, error_category)
    results = dict(audit.results or {})
    results[job.code] = "returned"
    audit.results = results
    audit.save(update_fields=["results"])
    who = "QC1" if target == "qc1" else "annotator"
    _append_batch_event(
        job.batch,
        actor,
        "audit_job_return",
        f"Audit {audit.code}: job {job.code} trả {who} — {reason.strip()}",
        now,
    )


@transaction.atomic
def close_audit(actor: WorkflowUser, audit_code: str) -> None:
    now = timezone.now()
    _require_audit_permission(actor, "đóng đợt audit")
    audit = _find_audit(audit_code)
    if audit.status != WorkflowAudit.Status.OPEN:
        raise WorkflowError("Audit đã kết thúc")
    results = dict(audit.results or {})
    left = sum(1 for jid in (audit.sampled_job_codes or []) if jid not in results)
    if left > 0:
        raise WorkflowError(f"Còn {left} job mẫu chưa chấm")

    failed = "returned" in results.values()
    batches = list(WorkflowBatch.objects.select_for_update().filter(code__in=list(audit.batch_codes or [])))
    if not failed:
        jobs_to_pass = list(
            WorkflowJob.objects.select_for_update().filter(
                batch__in=batches,
                stage__in=[WorkflowJobStage.QC2_PENDING, WorkflowJobStage.QC2_IN_PROGRESS],
            )
        )
        for job in jobs_to_pass:
            old_stage = job.stage
            job.qc2 = actor
            job.stage = WorkflowJobStage.READY_TO_DELIVER
            job.save(update_fields=["qc2", "stage"])
            _append_job_event(job, actor, "qc2_pass", old_stage, job.stage, now)
            emit_workflow_qc_event(
                job=job,
                event_type="job_completed_l2",
                actor=actor,
                actor_role="l2_qc",
                params={"audit_id": audit.code},
                at=now,
            )

    audit.status = WorkflowAudit.Status.FAILED if failed else WorkflowAudit.Status.PASSED
    audit.closed_at = now
    audit.save(update_fields=["status", "closed_at"])

    for b in batches:
        all_done = not b.jobs.exclude(
            stage__in=[WorkflowJobStage.READY_TO_DELIVER, WorkflowJobStage.DELIVERED]
        ).exists()
        b.status = WorkflowBatchStatus.READY if (not failed and all_done) else WorkflowBatchStatus.IN_PROGRESS
        b.save(update_fields=["status"])
        _append_batch_event(
            b,
            actor,
            "audit_fail" if failed else "audit_pass",
            f"Audit {audit.code} trượt: có job bị trả về"
            if failed
            else f"Audit {audit.code} đạt mức {audit.percent}%",
            now,
        )


# ==============================================================================
# Teams, Users, Projects, DataTypes, Favorites
# ==============================================================================


_VALID_WORK_STEPS = frozenset({"annotate", "qc1", "qc2"})


def _validate_work_steps(raw_steps: Any) -> list[str]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowValidationError("Cần chọn ít nhất một bước được phép")
    steps: list[str] = []
    for item in raw_steps:
        step = str(item or "").strip()
        if step not in _VALID_WORK_STEPS:
            raise WorkflowValidationError(f"Bước không hợp lệ: {step}")
        if step not in steps:
            steps.append(step)
    return steps


def _parse_strict_int(raw: Any, label: str, *, min_value: int = 0) -> int:
    if isinstance(raw, bool):
        raise WorkflowValidationError(f"{label} phải là số nguyên >= {min_value}")
    if isinstance(raw, float) and (not math.isfinite(raw) or not raw.is_integer()):
        raise WorkflowValidationError(f"{label} phải là số nguyên >= {min_value}")
    try:
        val = int(raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowValidationError(f"{label} phải là số nguyên >= {min_value}") from exc
    if val < min_value:
        raise WorkflowValidationError(f"{label} phải là số nguyên >= {min_value}")
    return val


@transaction.atomic
def update_data_type(dt_code: str, payload: dict[str, Any], *, actor: WorkflowUser | None = None) -> WorkflowDataType:
    if actor is not None:
        _require_pm_or_admin(actor, "cập nhật cấu hình loại dữ liệu")
    dt = WorkflowDataType.objects.select_for_update().filter(code=dt_code).first()
    if dt is None:
        raise WorkflowError(f"Không tìm thấy loại dữ liệu {dt_code}")
    if "name" in payload:
        dt.name = str(payload["name"]).strip()[:150] or dt.name
    if "shapeType" in payload:
        st = str(payload["shapeType"]).strip()[:32]
        if not st:
            raise WorkflowValidationError("shapeType không hợp lệ")
        dt.shape_type = st
        dt.dimension = Dimension.DIM_3D if st == "cuboid" else Dimension.DIM_2D
    if "kpiPerDay" in payload:
        dt.kpi_per_day = _parse_strict_int(payload["kpiPerDay"], "kpiPerDay", min_value=1)
    if "thresholdCm" in payload:
        raw_cm = payload["thresholdCm"]
        if isinstance(raw_cm, bool):
            raise WorkflowValidationError("thresholdCm phải là số không âm")
        try:
            cm_val = float(raw_cm)
        except (TypeError, ValueError) as exc:
            raise WorkflowValidationError("thresholdCm phải là số không âm") from exc
        if not math.isfinite(cm_val) or cm_val < 0:
            raise WorkflowValidationError("thresholdCm phải là số không âm")
        dt.threshold_cm = cm_val
    if "thresholdDeg" in payload:
        raw_deg = payload["thresholdDeg"]
        if isinstance(raw_deg, bool):
            raise WorkflowValidationError("thresholdDeg phải là số không âm")
        try:
            deg_val = float(raw_deg)
        except (TypeError, ValueError) as exc:
            raise WorkflowValidationError("thresholdDeg phải là số không âm") from exc
        if not math.isfinite(deg_val) or deg_val < 0:
            raise WorkflowValidationError("thresholdDeg phải là số không âm")
        dt.threshold_deg = deg_val
    if "errorCategories" in payload and isinstance(payload["errorCategories"], list):
        dt.error_categories = [str(x).strip() for x in payload["errorCategories"] if str(x).strip()]
    dt.save()
    return dt


@transaction.atomic
def create_team(name: str, allowed_steps: list[str], can_qa: bool, *, actor: WorkflowUser | None = None) -> WorkflowTeam:
    if actor is not None:
        _require_pm_or_admin(actor, "tạo team mới")
    clean = str(name or "").strip()[:150]
    if not clean:
        raise WorkflowError("Cần nhập tên team")
    steps = _validate_work_steps(allowed_steps)
    if WorkflowTeam.objects.filter(name__iexact=clean).exists():
        raise WorkflowError("Tên team đã tồn tại")
    return _create_with_code(
        WorkflowTeam,
        "t",
        name=clean,
        allowed_steps=steps,
        can_qa=bool(can_qa),
    )


@transaction.atomic
def update_team(team_code: str, patch: dict[str, Any], *, actor: WorkflowUser | None = None) -> WorkflowTeam:
    team = _find_team(team_code)
    if actor is not None:
        _require_lead_pm_or_admin(actor, "cập nhật team", team=team)
    if "name" in patch:
        clean = str(patch["name"] or "").strip()[:150]
        if not clean:
            raise WorkflowError("Cần nhập tên team")
        team.name = clean
    if "allowedSteps" in patch:
        team.allowed_steps = _validate_work_steps(patch["allowedSteps"])
    if "canQa" in patch:
        team.can_qa = bool(patch["canQa"])
    team.save()
    return team


@transaction.atomic
def delete_team(team_code: str, *, actor: WorkflowUser | None = None) -> None:
    if actor is not None:
        _require_pm_or_admin(actor, "xoá team")
    team = _find_team(team_code)
    active = WorkflowJob.objects.filter(team=team, stage__in=ACTIVE_STAGES).count()
    if active > 0:
        raise WorkflowError(f'Không thể xoá team "{team.name}": còn {active} job đang xử lý')
    team.delete()


@transaction.atomic
def add_team_member(team_code: str, user_code: str, *, actor: WorkflowUser | None = None) -> None:
    team = _find_team(team_code)
    if actor is not None:
        _require_lead_pm_or_admin(actor, "thêm thành viên vào team", team=team)
    user = _find_user(user_code)
    if team.members.filter(id=user.id).exists():
        raise WorkflowError("Người dùng đã là thành viên team này")
    team.members.add(user)


@transaction.atomic
def remove_team_member(team_code: str, user_code: str, *, actor: WorkflowUser | None = None) -> None:
    team = _find_team(team_code)
    if actor is not None:
        _require_lead_pm_or_admin(actor, "xoá thành viên khỏi team", team=team)
    user = _find_user(user_code)
    if not team.members.filter(id=user.id).exists():
        raise WorkflowError("Người dùng không thuộc team này")
    if team.lead_id == user.id:
        raise WorkflowError("Không thể xoá trưởng nhóm khỏi team")
    team.members.remove(user)


@transaction.atomic
def update_user(user_code: str, patch: dict[str, Any], *, actor: WorkflowUser | None = None) -> WorkflowUser:
    user = WorkflowUser.objects.select_for_update().filter(code=user_code).first()
    if user is None:
        raise WorkflowError(f"Không tìm thấy người dùng {user_code}")

    if "role" in patch:
        requested_role = str(patch["role"] or "").strip()
        if requested_role not in WorkflowRole.values:
            raise WorkflowValidationError(f"Vai trò không hợp lệ: {requested_role}")
    else:
        requested_role = None

    if actor is not None:
        is_self = actor.id == user.id
        sensitive_fields = ("role", "isQc", "employeeId", "cvatUsername")
        changing_sensitive = any(k in patch for k in sensitive_fields)
        if actor.role == WorkflowRole.ANNOTATOR:
            if not is_self or changing_sensitive:
                raise WorkflowPermissionError("Bạn không có quyền chỉnh sửa quyền hạn nhân sự")
        elif actor.role == WorkflowRole.LEAD:
            if user.role in (WorkflowRole.ADMIN, WorkflowRole.PM):
                raise WorkflowPermissionError("Team Lead không thể chỉnh sửa tài khoản Admin hoặc PM")
            if not is_self and not WorkflowTeam.objects.filter(lead=actor, members=user).exists():
                raise WorkflowPermissionError("Team Lead chỉ có thể chỉnh sửa thành viên trong team mình phụ trách")
            if "cvatUsername" in patch or "employeeId" in patch:
                raise WorkflowPermissionError("Team Lead không có quyền sửa cvatUsername hoặc employeeId")
            if requested_role is not None and requested_role in (WorkflowRole.ADMIN, WorkflowRole.PM):
                raise WorkflowPermissionError("Team Lead không thể nâng quyền lên Admin hoặc PM")
        elif actor.role == WorkflowRole.PM:
            if user.role == WorkflowRole.ADMIN:
                raise WorkflowPermissionError("PM không thể chỉnh sửa tài khoản Admin")
            if "cvatUsername" in patch:
                raise WorkflowPermissionError("Chỉ Admin mới có quyền đổi cvatUsername")
            if requested_role == WorkflowRole.ADMIN:
                raise WorkflowPermissionError("PM không thể nâng quyền lên Admin")
        elif actor.role != WorkflowRole.ADMIN:
            raise WorkflowPermissionError("Bạn không có quyền chỉnh sửa nhân sự")

    if "name" in patch:
        clean = str(patch["name"] or "").strip()[:150]
        if not clean:
            raise WorkflowValidationError("Cần nhập tên")
        user.name = clean
    if requested_role is not None:
        user.role = requested_role
    if "isQc" in patch:
        user.is_qc = bool(patch["isQc"])
    if "cvatUsername" in patch:
        clean_cvat = str(patch["cvatUsername"] or "").strip()[:150]
        if not clean_cvat:
            raise WorkflowValidationError("cvatUsername không được để trống")
        user.cvat_username = clean_cvat
    if "employeeId" in patch:
        user.employee_id = _parse_strict_int(patch["employeeId"], "employeeId", min_value=0)

    try:
        with transaction.atomic():
            user.save()
    except IntegrityError as exc:
        raise WorkflowValidationError("Thông tin người dùng bị trùng lặp hoặc không hợp lệ") from exc
    return user


@transaction.atomic
def assign_project(actor: WorkflowUser, project_code: str, pm_codes: list[str]) -> None:
    now = timezone.now()
    if actor.role != "admin":
        raise WorkflowError("Chỉ Admin được giao dự án")
    project = WorkflowProject.objects.select_for_update().filter(code=project_code).first()
    if project is None:
        raise WorkflowError(f"Không tìm thấy dự án {project_code}")
    unique_pms = list(dict.fromkeys(pm_codes))
    if not unique_pms:
        raise WorkflowError("Dự án cần ít nhất một PM phụ trách")
    pm_objs = []
    for code in unique_pms:
        u = WorkflowUser.objects.filter(code=code).first()
        if u is None or u.role != "pm":
            raise WorkflowError(f"{code} không phải PM")
        pm_objs.append(u)
    project.pms.set(pm_objs)
    project.pm_order = unique_pms
    project.assigned_at = now
    project.save(update_fields=["pm_order", "assigned_at"])


@transaction.atomic
def toggle_favorite(actor: WorkflowUser, target_id: str) -> list[str]:
    u = WorkflowUser.objects.select_for_update().get(id=actor.id)
    favs = list(u.favorites or [])
    if target_id in favs:
        favs = [x for x in favs if x != target_id]
    else:
        favs.append(target_id)
    u.favorites = favs
    u.save(update_fields=["favorites"])
    return favs


@transaction.atomic
def assign_batch_team(actor: WorkflowUser, batch_code: str, team_code: str) -> None:
    """R3: Giao hoặc chuyển nguyên batch cho một team (`assignBatchTeam`)."""
    now = timezone.now()
    _require_pm_or_admin(actor, "giao hoặc chuyển team cho batch")
    batch = _find_batch(batch_code)
    team = _find_team(team_code)
    if batch.team_id == team.id:
        raise WorkflowError("Batch đã ở team này")
    if batch.status not in (WorkflowBatchStatus.PENDING, WorkflowBatchStatus.IN_PROGRESS):
        raise WorkflowError("Batch đang audit/đã xong, không đổi team được")
    if "annotate" not in (team.allowed_steps or []):
        raise WorkflowError(f"Team {team.name} không làm bước gán nhãn")

    eligible_stages = [
        WorkflowJobStage.UNASSIGNED_POOL,
        WorkflowJobStage.TEAM_POOL,
        WorkflowJobStage.ANNO_IN_PROGRESS,
        WorkflowJobStage.QC1_PENDING,
        WorkflowJobStage.QC1_IN_PROGRESS,
    ]
    jobs = list(
        WorkflowJob.objects.select_for_update().filter(batch=batch, stage__in=eligible_stages)
    )
    for job in jobs:
        old_stage = job.stage
        job.team = team
        job.annotator = None
        job.qc1 = None
        job.stage = WorkflowJobStage.TEAM_POOL
        job.save(update_fields=["team", "annotator", "qc1", "stage"])
        _append_job_event(job, actor, "distribute", old_stage, job.stage, now)
        emit_workflow_qc_event(
            job=job,
            event_type="job_distributed",
            actor=actor,
            params={"team": team.code},
            at=now,
        )

    had_team = batch.team_id is not None
    batch.team = team
    batch.status = WorkflowBatchStatus.IN_PROGRESS
    step_pic = dict(batch.step_pic or {})
    step_pic["annotate"] = [team.code]
    batch.step_pic = step_pic
    batch.save(update_fields=["team", "status", "step_pic"])
    batch.project.teams.add(team)
    batch.dataset.last_distributed_at = now
    batch.dataset.save(update_fields=["last_distributed_at"])
    _append_batch_event(
        batch,
        actor,
        "transfer" if had_team else "distribute",
        f"Giao {len(jobs)} job cho {team.name}",
        now,
    )


@transaction.atomic
def set_team_pm(actor: WorkflowUser, team_code: str, pm_code: str) -> None:
    """R6: Đổi PM sở hữu team (`setTeamPm`)."""
    if actor.role != "admin":
        raise WorkflowPermissionError("Chỉ sếp tổng được đổi PM của team")
    team = _find_team(team_code)
    pm = _find_user(pm_code)
    if pm.role != "pm":
        raise WorkflowError(f"{pm_code} không phải PM")
    running_project_ids = set(
        WorkflowBatch.objects.filter(
            team=team,
            status__in=[WorkflowBatchStatus.IN_PROGRESS, WorkflowBatchStatus.IN_AUDIT],
        ).values_list("project_id", flat=True)
    )
    if running_project_ids:
        missing = [
            p.name
            for p in WorkflowProject.objects.filter(id__in=running_project_ids)
            if not p.pms.filter(id=pm.id).exists()
        ]
        if missing:
            raise WorkflowError(f"PM {pm.name} chưa phụ trách dự án: {', '.join(missing)}")
    team.pm = pm
    team.save(update_fields=["pm"])


@transaction.atomic
def move_member(actor: WorkflowUser, user_code: str, to_team_code: str | None) -> None:
    """R7: Đổi team hoặc cho nghỉ (`to_team_code=None`), bàn giao job đang làm về kho team / lead cũ."""
    now = timezone.now()
    _require_pm_or_admin(actor, "chuyển team hoặc cho nghỉ thành viên")
    member = _find_user(user_code)
    if member.role not in ("lead", "annotator"):
        raise WorkflowError("Chỉ chuyển được lead hoặc annotator")
    from_team = member.teams.select_related("lead", "pm").first()
    if from_team is None:
        raise WorkflowError(f"{member.name} chưa thuộc team nào")
    to_team = _find_team(to_team_code) if to_team_code else None
    if to_team is not None and to_team.id == from_team.id:
        raise WorkflowError(f"{member.name} đã ở {from_team.name}")
    if from_team.lead_id == member.id:
        raise WorkflowError(f"{member.name} là lead duy nhất của {from_team.name}, phải đổi lead trước")
    if actor.role == "pm" and (from_team.pm_id != actor.id or (to_team is not None and to_team.pm_id != actor.id)):
        raise WorkflowPermissionError("Chỉ sếp tổng hoặc PM của cả team nguồn và team đích được chuyển người")

    jobs = list(WorkflowJob.objects.select_for_update().filter(team=from_team))
    for job in jobs:
        is_anno = job.annotator_id == member.id and job.stage == WorkflowJobStage.ANNO_IN_PROGRESS
        is_qc = job.qc1_id == member.id and job.stage in (
            WorkflowJobStage.ANNO_IN_PROGRESS,
            WorkflowJobStage.QC1_PENDING,
            WorkflowJobStage.QC1_IN_PROGRESS,
        )
        if not is_anno and not is_qc:
            continue
        old_stage = job.stage
        if is_anno:
            job.annotator = None
            job.stage = WorkflowJobStage.TEAM_POOL
        if is_qc:
            job.qc1 = None if (from_team.lead_id == job.annotator_id) else from_team.lead
        job.save(update_fields=["annotator", "qc1", "stage"])
        _append_job_event(job, actor, "handover", old_stage, job.stage, now)

    from_team.members.remove(member)
    if to_team is not None:
        to_team.members.add(member)
