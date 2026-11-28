"""
Transactional QC custom event engine ported from `cvat-di-ext/backend/cvat_ext/qc_event_log.py`
and `qc_analytics.py`.

Key upgrades over `cvat-di-ext`'s fire-and-forget JSONL + Vector/ClickHouse pipeline:
1. Full ACID persistence inside `django.db.transaction.atomic()` with `select_for_update()`.
2. Idempotent ingestion via `idempotency_key` (safe retries, safe JSONL backfill replays).
3. Atomic workflow/defect/snapshot/KPI side effects: either the `QcEvent` AND all resulting
   state mutations commit together, or the entire transaction rolls back cleanly.
4. Handles all `cvat-di-ext` custom events (`qc:*` scope prefix and `*_qc` / `qc_*` event types).
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q, QuerySet, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from .models import (
    DefectRecord,
    DeliverStatus,
    JobQualitySnapshot,
    PipelineStep,
    QcEvent,
    StageTransition,
    SyncedJob,
    WorkflowJob,
    WorkflowJobEvent,
    WorkflowJobStage,
    WorkflowKpiDaily,
    WorkflowUser,
)

ANALYTICS_SCOPE_PREFIX = "qc:"
MAX_PARAMS_BYTES = 16 * 1024
MAX_FRAMES_SPAN = 2000
MAX_QC_EVENT_BATCH = 500

# Canonical event types ported from cvat-di-ext (`qc_event_log.py`, `apps.py`, `views.py`, `preqc.py`)
KNOWN_QC_EVENT_TYPES = frozenset({
    # Lifecycle & stage transitions
    "job_released_pre_qc",
    "job_submitted",
    "job_recalled_from_annotator",
    "job_accepted_l1",
    "job_escalated_to_l2",
    "job_accepted_l2",
    "job_completed_l2",
    "job_returned_for_rework",
    "job_stage_transition",
    # Workflow operational actions mirrored into transactional QcEvent stream
    "job_distributed",
    "job_assigned",
    "job_reassigned",
    "job_delivered",
    "qc1_started",
    "qc2_started",
    "audit_created",
    "audit_job_passed",
    "audit_job_returned",
    "audit_closed",
    # Issue & defect lifecycle
    "preqc_ingest",
    "auto_detect_sync",
    "issue_created",
    "qc_fixed",
    "issue_qc_fixed",
    "issue_addressed",
    "issue_resolved",
    "issue_reopened",
    "issue_disputed",
    "issue_dismissed_fp",
    "issue_escalated",
    "bulk_issue_resolved",
    "bulk_issue_addressed",
    "bulk_issue_reopened",
    "job_issues_cleared",
    "precedent_cited",
    # Inspection telemetry, roster & tools
    "qc_frame_dwell",
    "qc_roster_updated",
    "thresholds_updated",
    "custom_tool_queued",
    "custom_tool_executed",
    "custom_tool_failed",
    "custom_tool_configured",
    "webhook_dispatched",
})


class QcEventError(ValueError):
    """Raised when a transactional QC event payload or transition is invalid."""


def normalize_event_type_and_scope(raw_event_type: str | None, raw_scope: str | None = None) -> tuple[str, str]:
    """Normalizes `scope` (always `qc:<event_type>`) and stripped `event_type`."""
    candidate = str(raw_event_type or "").strip()
    scope_in = str(raw_scope or "").strip()

    if not candidate and scope_in:
        candidate = scope_in
    if candidate.startswith(ANALYTICS_SCOPE_PREFIX):
        event_type = candidate[len(ANALYTICS_SCOPE_PREFIX) :].strip()
    else:
        event_type = candidate

    if not event_type:
        event_type = "qc_event"
    event_type = event_type[:64]
    scope = f"{ANALYTICS_SCOPE_PREFIX}{event_type}"[:96]
    return event_type, scope


def _parse_int(val: Any) -> int | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, float):
        if not math.isfinite(val) or not val.is_integer():
            return None
        return int(val)
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _parse_optional_int(val: Any, field_name: str, *, min_value: int | None = None) -> int | None:
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    parsed = _parse_int(val)
    if parsed is None:
        raise QcEventError(f"Trường `{field_name}` phải là số nguyên hợp lệ.")
    if min_value is not None and parsed < min_value:
        raise QcEventError(f"Trường `{field_name}` phải >= {min_value}.")
    if parsed > 2**31 - 1 or parsed < -(2**31):
        raise QcEventError(f"Trường `{field_name}` vượt quá giới hạn số nguyên 32-bit.")
    return parsed


def _validate_json_size(obj: dict[str, Any], field_name: str) -> dict[str, Any]:
    encoded = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_PARAMS_BYTES:
        raise QcEventError(f"Trường `{field_name}` vượt quá giới hạn {MAX_PARAMS_BYTES} bytes.")
    return obj


def _parse_timestamp(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(float(raw)):
        return datetime.fromtimestamp(float(raw), tz=UTC)
    if isinstance(raw, str) and raw.strip():
        text = raw.strip()
        try:
            as_float = float(text)
            if math.isfinite(as_float):
                return datetime.fromtimestamp(as_float, tz=UTC)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    return timezone.now()


def _extract_dwell_ms(params: dict[str, Any], raw_duration: Any = None) -> int | None:
    candidate = params.get("dwell_ms") if isinstance(params, dict) else None  # pyright: ignore[reportUnnecessaryIsInstance]
    if candidate is None:
        candidate = raw_duration
    if candidate is None or (isinstance(candidate, str) and candidate.strip() == ""):
        return None
    if isinstance(candidate, bool):
        raise QcEventError("Trường `dwell_ms` phải là số không âm.")
    try:
        val = float(candidate)
    except (TypeError, ValueError) as exc:
        raise QcEventError("Trường `dwell_ms` phải là số không âm.") from exc
    if not math.isfinite(val) or val < 0:
        raise QcEventError("Trường `dwell_ms` phải là số không âm.")
    return min(int(val), 2**31 - 1)


def normalize_qc_event_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Accepts either:
      - `cvat-di-ext` `qc_events.jsonl` entry dict (`event_type`, `job_id`, `timestamp_utc`, ...)
      - `cvat-di-ext` ClickHouse/analytics envelope (`scope="qc:..."`, `payload="{...}"`)
    Returns normalized field dict ready for `QcEvent` creation.
    """
    if not isinstance(raw, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise QcEventError("Payload sự kiện QC phải là JSON object.")

    merged: dict[str, Any] = dict(raw)
    nested_payload: Any = merged.get("payload")
    if isinstance(nested_payload, str) and nested_payload.strip().startswith("{"):
        if len(nested_payload.encode("utf-8")) > MAX_PARAMS_BYTES * 2:
            raise QcEventError("Trường `payload` quá lớn.")
        try:
            decoded: Any = json.loads(nested_payload)
            if isinstance(decoded, dict):
                merged = {**decoded, **{k: v for k, v in merged.items() if k != "payload" and v is not None}}
        except ValueError as exc:
            raise QcEventError("Trường `payload` JSON không hợp lệ.") from exc
    elif isinstance(nested_payload, dict):
        merged = {**nested_payload, **{k: v for k, v in merged.items() if k != "payload" and v is not None}}

    job_id = _parse_int(merged.get("job_id"))
    if job_id is None or job_id <= 0:
        raise QcEventError("Thiếu hoặc sai `job_id` hợp lệ (> 0).")

    event_type, scope = normalize_event_type_and_scope(
        merged.get("event_type"), merged.get("scope")
    )

    if merged.get("params") is not None and not isinstance(merged.get("params"), dict):
        raise QcEventError("Trường `params` phải là JSON object.")
    if merged.get("metric_delta") is not None and not isinstance(merged.get("metric_delta"), dict):
        raise QcEventError("Trường `metric_delta` phải là JSON object.")
    if merged.get("extra") is not None and not isinstance(merged.get("extra"), dict):
        raise QcEventError("Trường `extra` phải là JSON object.")

    params = _validate_json_size(dict(merged["params"]) if isinstance(merged.get("params"), dict) else {}, "params")
    metric_delta = _validate_json_size(
        dict(merged["metric_delta"]) if isinstance(merged.get("metric_delta"), dict) else {},
        "metric_delta",
    )
    extra = _validate_json_size(dict(merged["extra"]) if isinstance(merged.get("extra"), dict) else {}, "extra")

    frames_raw: Any = merged.get("frames_span") if merged.get("frames_span") is not None else merged.get("frames")
    if frames_raw is None:
        frames_span: list[int] = []
    elif isinstance(frames_raw, list):
        frames_items: list[Any] = list(frames_raw)  # pyright: ignore[reportUnknownArgumentType]
        if len(frames_items) > MAX_FRAMES_SPAN:
            raise QcEventError(f"Trường `frames_span` vượt quá tối đa {MAX_FRAMES_SPAN} phần tử.")
        frames_span = [f for f in (_parse_int(x) for x in frames_items) if f is not None]
    else:
        raise QcEventError("Trường `frames_span` phải là danh sách số nguyên.")

    ts = _parse_timestamp(merged.get("timestamp_utc") or merged.get("timestamp"))
    raw_issue: Any = merged.get("issue_id") if merged.get("issue_id") is not None else merged.get("obj_id")
    issue_id = _parse_optional_int(raw_issue, "issue_id", min_value=0)
    defect_code = str(
        merged.get("defect_code") or merged.get("code") or merged.get("obj_name") or ""
    ).strip()[:64]
    actor_role = str(merged.get("actor_role") or merged.get("obj_val") or "").strip()[:32]
    username = str(merged.get("username") or merged.get("user_name") or merged.get("actor") or "").strip()[:150]

    idem = merged.get("idempotency_key") or merged.get("event_id")
    idempotency_key = str(idem).strip()[:128] if idem is not None and str(idem).strip() else None

    raw_frame = merged.get("frame_number") if merged.get("frame_number") is not None else merged.get("frame")

    return {
        "idempotency_key": idempotency_key,
        "scope": scope,
        "event_type": event_type,
        "timestamp_utc": ts,
        "job_id": job_id,
        "task_id": _parse_optional_int(merged.get("task_id"), "task_id", min_value=0),
        "project_id": _parse_optional_int(merged.get("project_id"), "project_id", min_value=0),
        "stage": str(merged.get("stage") or "").strip()[:32],
        "actor_role": actor_role,
        "user_id": _parse_optional_int(merged.get("user_id"), "user_id", min_value=0),
        "username": username,
        "issue_id": issue_id,
        "defect_code": defect_code,
        "severity": str(merged.get("severity") or "").strip()[:24],
        "status": str(merged.get("status") or "").strip()[:32],
        "frame_number": _parse_optional_int(raw_frame, "frame_number"),
        "frames_span": frames_span,
        "track_id": _parse_optional_int(merged.get("track_id"), "track_id"),
        "shape_id": _parse_optional_int(merged.get("shape_id"), "shape_id"),
        "label_class": str(merged.get("label_class") or merged.get("label") or "").strip()[:64],
        "dwell_ms": _extract_dwell_ms(params, merged.get("duration")),
        "params": params,
        "metric_delta": metric_delta,
        "extra": extra,
    }


def _compute_backfill_idempotency_key(norm: dict[str, Any]) -> str:
    """Deterministic key for JSONL backfill rows that lack an explicit event_id."""
    material = json.dumps(
        {
            "scope": norm["scope"],
            "ts": norm["timestamp_utc"].isoformat(),
            "job_id": norm["job_id"],
            "issue_id": norm["issue_id"],
            "defect_code": norm["defect_code"],
            "frame": norm["frame_number"],
            "username": norm["username"],
            "params": norm["params"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "bf_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def is_client_telemetry_event(event_type: str | None, scope: str | None = None) -> bool:
    """Returns True when an event originated from untrusted client telemetry (`client_*`)."""
    et = str(event_type or "").strip().lower()
    sc = str(scope or "").strip().lower()
    return et.startswith("client_") or sc.startswith("qc:client_") or sc.startswith("client_")


def _next_job_event_code() -> str:
    last = WorkflowJobEvent.objects.order_by("-id").only("id").first()
    seq = (last.id if last else 0) + 1
    while WorkflowJobEvent.objects.filter(code=f"ev{seq:05d}").exists():
        seq += 1
    return f"ev{seq:05d}"


def _create_job_event(**kwargs: Any) -> WorkflowJobEvent:
    """Creates a WorkflowJobEvent with collision-safe retry on concurrent `code` races."""
    for attempt in range(5):
        code = _next_job_event_code() if attempt == 0 else f"ev_{uuid.uuid4().hex[:12]}"
        try:
            with transaction.atomic():
                return WorkflowJobEvent.objects.create(code=code, **kwargs)
        except IntegrityError:
            if attempt == 4:
                raise
    raise RuntimeError("Unreachable")


def _resolve_workflow_actor(username: str) -> WorkflowUser | None:
    if not username:
        return None
    return WorkflowUser.objects.filter(cvat_username__iexact=username).first()


def _infer_primary_category(defect_code: str) -> str:
    c = defect_code.upper()
    if c.startswith(("E1", "E2", "E3", "E4", "E5", "E6")):
        return c[:2]
    if c.startswith(("GEO-", "BDD_BOX", "DMS_003", "DMS_004", "DMS_005", "DMS_007", "DMS_008", "DMS_010", "DMS_011", "DMS_012", "DMS_013", "DMS_015", "DMS_016")):
        return "E1"
    if c.startswith(("EXI-EXTRA", "EXI-DUP", "BDD_DUPLICATE")):
        return "E2"
    if c.startswith(("EXI-MISS", "BDD_MISSED")):
        return "E3"
    if c.startswith(("CLS-ATTR", "DMS_OCC")):
        return "E4"
    if c.startswith(("TRK-", "DMS_001", "DMS_002", "DMS_006")):
        return "E5"
    if c.startswith(("CLS-LABEL", "BDD_INVALID_TAXONOMY")):
        return "E6"
    return "E1"


def _apply_lifecycle_to_workflow_job(ev: QcEvent, wjob: WorkflowJob) -> bool:
    """
    Transactionally advances `WorkflowJob` + appends `WorkflowJobEvent` (and `WorkflowKpiDaily`
    on first submission) in response to a `cvat-di-ext` lifecycle `QcEvent`.
    Must be called inside `transaction.atomic()` with `wjob` locked via `select_for_update()`.
    Client-prefixed telemetry (`client_*`) is never allowed to trigger workflow stage transitions.
    """
    if is_client_telemetry_event(ev.event_type, ev.scope):
        return False

    etype = ev.event_type
    params = ev.params if isinstance(ev.params, dict) else {}
    action = str(params.get("action") or "").strip().lower()
    from_step = str(params.get("from_step") or "").strip().lower()
    to_step = str(params.get("to_step") or "").strip().lower()
    reason = str(params.get("reason") or "").strip()
    error_cat = str(params.get("error_category") or ev.defect_code or "").strip()

    actor_user = _resolve_workflow_actor(ev.username)
    actor_code = actor_user.code if actor_user else (ev.username or ev.actor_role or "cvat_bot")
    old_stage = wjob.stage

    # Map `job_stage_transition` into canonical lifecycle events
    eff_type = etype
    if etype == "job_stage_transition":
        if action in ("submit_for_review", "submit") or (from_step == "annotator" and to_step == "l1_qc"):
            eff_type = "job_submitted"
        elif action in ("accept_l1", "l1_accept") or (from_step == "l1_qc" and to_step in ("l2_qc", "dept_head")):
            eff_type = "job_accepted_l1"
        elif action in ("accept_l2", "complete", "dept_head_accept") or to_step == "completed":
            eff_type = "job_completed_l2"
        elif action in ("reject", "return_for_rework", "return_to_annotator"):
            eff_type = "job_returned_for_rework"

    if eff_type == "job_submitted":
        if old_stage not in (WorkflowJobStage.ANNO_IN_PROGRESS, WorkflowJobStage.TEAM_POOL):
            return False
        is_first = wjob.first_submitted_at is None
        edited_hint = _parse_optional_int(params.get("edited_cuboids"), "params.edited_cuboids", min_value=0)
        wjob.stage = WorkflowJobStage.QC1_PENDING
        if is_first:
            wjob.first_submitted_at = ev.timestamp_utc
            if edited_hint is not None:
                wjob.edited_cuboids = edited_hint
            elif wjob.edited_cuboids == 0:
                wjob.edited_cuboids = round(wjob.prelabel_cuboids * 0.4)
        wjob.save(update_fields=["stage", "first_submitted_at", "edited_cuboids"])
        _create_job_event(
            job=wjob,
            at=ev.timestamp_utc,
            actor=actor_user,
            actor_code=actor_code[:64],
            type="submit" if is_first else "resubmit",
            from_stage=old_stage,
            to_stage=wjob.stage,
        )
        if is_first and wjob.annotator_id:
            kpi_row, _ = WorkflowKpiDaily.objects.select_for_update().get_or_create(
                user_id=wjob.annotator_id,
                date=ev.timestamp_utc.date(),
                defaults={"edited_cuboids": 0},
            )
            kpi_row.edited_cuboids += wjob.edited_cuboids
            kpi_row.save(update_fields=["edited_cuboids"])
        return True

    if eff_type == "job_accepted_l1":
        if old_stage not in (WorkflowJobStage.QC1_PENDING, WorkflowJobStage.QC1_IN_PROGRESS):
            return False
        wjob.stage = WorkflowJobStage.QC2_PENDING
        wjob.save(update_fields=["stage"])
        _create_job_event(
            job=wjob,
            at=ev.timestamp_utc,
            actor=actor_user,
            actor_code=actor_code[:64],
            type="qc1_pass",
            from_stage=old_stage,
            to_stage=wjob.stage,
        )
        return True

    if eff_type in ("job_accepted_l2", "job_completed_l2"):
        if old_stage not in (WorkflowJobStage.QC2_PENDING, WorkflowJobStage.QC2_IN_PROGRESS):
            return False
        wjob.stage = WorkflowJobStage.READY_TO_DELIVER
        if actor_user:
            wjob.qc2 = actor_user
        wjob.save(update_fields=["stage", "qc2"])
        _create_job_event(
            job=wjob,
            at=ev.timestamp_utc,
            actor=actor_user,
            actor_code=actor_code[:64],
            type="qc2_pass",
            from_stage=old_stage,
            to_stage=wjob.stage,
        )
        return True

    if eff_type == "job_returned_for_rework":
        if old_stage in (WorkflowJobStage.QC1_PENDING, WorkflowJobStage.QC1_IN_PROGRESS):
            wjob.stage = WorkflowJobStage.ANNO_IN_PROGRESS
            wjob.rework_count += 1
            wjob.save(update_fields=["stage", "rework_count"])
            against = [wjob.annotator.code] if wjob.annotator else []
            _create_job_event(
                job=wjob,
                at=ev.timestamp_utc,
                actor=actor_user,
                actor_code=actor_code[:64],
                type="qc1_return",
                from_stage=old_stage,
                to_stage=wjob.stage,
                reason=reason or "Trả sửa từ QC1 (CVAT)",
                error_category=(error_cat or "Khác")[:128],
                rework_against=against,
            )
            return True
        if old_stage in (WorkflowJobStage.QC2_PENDING, WorkflowJobStage.QC2_IN_PROGRESS):
            to_qc1 = to_step == "l1_qc"
            wjob.stage = WorkflowJobStage.QC1_IN_PROGRESS if to_qc1 else WorkflowJobStage.ANNO_IN_PROGRESS
            wjob.rework_count += 1
            if actor_user:
                wjob.qc2 = actor_user
            wjob.save(update_fields=["stage", "rework_count", "qc2"])
            if to_qc1:
                against = [wjob.qc1.code] if wjob.qc1 else []
                ev_kind = "qc2_return_qc1"
            else:
                against = [u.code for u in (wjob.annotator, wjob.qc1) if u is not None]
                ev_kind = "qc2_return_anno"
            _create_job_event(
                job=wjob,
                at=ev.timestamp_utc,
                actor=actor_user,
                actor_code=actor_code[:64],
                type=ev_kind,
                from_stage=old_stage,
                to_stage=wjob.stage,
                reason=reason or "Trả sửa từ QC2 (CVAT)",
                error_category=(error_cat or "Khác")[:128],
                rework_against=against,
            )
            return True
    return False


def _sync_sjob_issue_counts(sjob: SyncedJob, *, extra_fields: list[str] | None = None) -> None:
    counts = dict(
        DefectRecord.objects.filter(job=sjob)
        .values_list("lifecycle_status")
        .annotate(c=Count("id"))
    )
    sjob.open_issues = counts.get("open", 0)
    sjob.addressed_issues = counts.get("addressed", 0)
    sjob.resolved_issues = counts.get("resolved", 0)
    fields = ["open_issues", "addressed_issues", "resolved_issues", "updated_at"]
    if extra_fields:
        fields.extend(extra_fields)
    sjob.save(update_fields=fields)


def _apply_side_effects_to_synced_models(ev: QcEvent) -> bool:
    """Updates `SyncedJob`, `StageTransition`, `DefectRecord`, and `JobQualitySnapshot` atomically."""
    if is_client_telemetry_event(ev.event_type, ev.scope):
        return False

    sjob = SyncedJob.objects.select_for_update().filter(cvat_job_id=ev.job_id).first()
    if sjob is None:
        return False

    applied = False
    etype = ev.event_type
    params = ev.params if isinstance(ev.params, dict) else {}

    # 1. Lifecycle transitions on SyncedJob (with timestamp monotonicity)
    step_map = {
        "job_released_pre_qc": PipelineStep.ANNOTATOR,
        "job_submitted": PipelineStep.L1_QC,
        "job_accepted_l1": PipelineStep.L2_QC,
        "job_escalated_to_l2": PipelineStep.L2_QC,
        "job_accepted_l2": PipelineStep.DEPT_HEAD,
        "job_completed_l2": PipelineStep.COMPLETED,
        "job_returned_for_rework": PipelineStep.ANNOTATOR,
    }
    target_step = step_map.get(etype)
    if etype == "job_stage_transition":
        to_step_raw = str(params.get("to_step") or "").strip().lower()
        if to_step_raw in PipelineStep.values:
            target_step = to_step_raw

    if target_step is not None:
        prev_step = sjob.pipeline_step
        prev_entered = sjob.step_entered_at
        is_newer_or_equal = prev_entered is None or ev.timestamp_utc >= prev_entered
        duration_sec = (
            (ev.timestamp_utc - prev_entered).total_seconds()
            if (prev_entered is not None and is_newer_or_equal)
            else None
        )
        if etype == "job_returned_for_rework" or str(params.get("action", "")).lower() in ("reject", "return_for_rework"):
            sjob.rework_count += 1
        if is_newer_or_equal:
            sjob.pipeline_step = target_step
            sjob.step_entered_at = ev.timestamp_utc
            if target_step == PipelineStep.COMPLETED:
                if sjob.completed_at is None or ev.timestamp_utc >= sjob.completed_at:
                    sjob.completed_at = ev.timestamp_utc
                sjob.deliver_status = DeliverStatus.READY
            sjob.save(update_fields=["pipeline_step", "step_entered_at", "rework_count", "completed_at", "deliver_status", "updated_at"])
        else:
            sjob.save(update_fields=["rework_count", "updated_at"])
        tr_defaults = {
            "job": sjob,
            "event_name": ev.scope[:48],
            "action": str(params.get("action") or etype)[:48],
            "from_step": prev_step[:24],
            "to_step": target_step[:24],
            "actor_username": ev.username[:150],
            "actor_role": ev.actor_role[:24],
            "reason": str(params.get("reason") or ""),
            "occurred_at": ev.timestamp_utc,
            "duration_prev_step_sec": max(0.0, duration_sec) if duration_sec is not None else None,
        }
        if ev.idempotency_key:
            StageTransition.objects.get_or_create(event_id=ev.idempotency_key[:64], defaults=tr_defaults)
        else:
            StageTransition.objects.create(**tr_defaults)
        applied = True

    # 2. Issue / defect mutations
    if etype in ("preqc_ingest", "issue_created") and ev.issue_id:
        source = "pre_qc_auto" if etype == "preqc_ingest" else ("auto" if ev.actor_role == "bot" else "manual")
        code = ev.defect_code or ("PREQC_DEFECT" if etype == "preqc_ingest" else "QC_ISSUE")
        DefectRecord.objects.update_or_create(
            cvat_issue_id=ev.issue_id,
            defaults={
                "job": sjob,
                "frame": ev.frame_number or 0,
                "primary_category": _infer_primary_category(code),
                "defect_code": code[:32],
                "severity": (ev.severity or "major")[:16],
                "source": source,
                "lifecycle_status": "open",
                "annotator_username": sjob.annotator_username,
                "owner_username": ev.username,
                "summary_text": str(params.get("message") or code)[:255],
            },
        )
        _sync_sjob_issue_counts(sjob)
        applied = True

    elif etype in (
        "qc_fixed",
        "issue_qc_fixed",
        "issue_addressed",
        "issue_resolved",
        "issue_reopened",
        "issue_disputed",
        "issue_dismissed_fp",
        "issue_escalated",
    ) and ev.issue_id:
        defect = DefectRecord.objects.select_for_update().filter(cvat_issue_id=ev.issue_id).first()
        snap, _ = JobQualitySnapshot.objects.select_for_update().get_or_create(job=sjob)
        if etype in ("qc_fixed", "issue_qc_fixed"):
            if defect:
                defect.lifecycle_status = "resolved"
                defect.save(update_fields=["lifecycle_status"])
            snap.qc_fixed_issues += 1
            snap.issues_tp += 1
            snap.save(update_fields=["qc_fixed_issues", "issues_tp", "updated_at"])
        elif etype == "issue_resolved":
            if defect:
                defect.lifecycle_status = "resolved"
                defect.save(update_fields=["lifecycle_status"])
            snap.issues_tp += 1
            snap.save(update_fields=["issues_tp", "updated_at"])
        elif etype == "issue_addressed":
            if defect:
                defect.lifecycle_status = "addressed"
                defect.save(update_fields=["lifecycle_status"])
        elif etype == "issue_reopened":
            if defect:
                defect.lifecycle_status = "open"
                defect.is_reopened = True
                defect.save(update_fields=["lifecycle_status", "is_reopened"])
            snap.issues_reopened += 1
            snap.save(update_fields=["issues_reopened", "updated_at"])
        elif etype == "issue_disputed":
            if defect:
                defect.is_disputed = True
                defect.save(update_fields=["is_disputed"])
            sjob.disputes += 1
        elif etype == "issue_dismissed_fp":
            if defect:
                defect.lifecycle_status = "resolved"
                defect.is_dismissed_fp = True
                defect.save(update_fields=["lifecycle_status", "is_dismissed_fp"])
            snap.issues_fp += 1
            snap.save(update_fields=["issues_fp", "updated_at"])
        elif etype == "issue_escalated":
            sjob.escalations += 1
        _sync_sjob_issue_counts(sjob, extra_fields=["disputes", "escalations"])
        applied = True

    elif etype in ("bulk_issue_addressed", "bulk_issue_resolved", "bulk_issue_reopened"):
        raw_ids = params.get("issue_ids")
        issue_ids = [x for x in (_parse_int(i) for i in raw_ids) if x is not None and x > 0] if isinstance(raw_ids, list) else []
        if ev.issue_id and ev.issue_id > 0:
            issue_ids.append(ev.issue_id)
        if issue_ids:
            qs_defects = DefectRecord.objects.filter(job=sjob, cvat_issue_id__in=issue_ids)
            if etype == "bulk_issue_addressed":
                qs_defects.update(lifecycle_status="addressed")
            elif etype == "bulk_issue_resolved":
                qs_defects.update(lifecycle_status="resolved")
            else:
                qs_defects.update(lifecycle_status="open", is_reopened=True)
            _sync_sjob_issue_counts(sjob)
            applied = True

    elif etype == "job_issues_cleared":
        DefectRecord.objects.filter(job=sjob, lifecycle_status__in=["open", "addressed"]).update(lifecycle_status="resolved")
        _sync_sjob_issue_counts(sjob)
        applied = True

    return applied


def emit_workflow_qc_event(
    *,
    job: WorkflowJob,
    event_type: str,
    actor: WorkflowUser | None = None,
    actor_role: str = "",
    stage: str = "",
    defect_code: str = "",
    status_val: str = "",
    params: dict[str, Any] | None = None,
    at: datetime | None = None,
) -> QcEvent:
    """
    Records a transactional `QcEvent` inside an ALREADY-OPEN `transaction.atomic()` block
    when a dashboard workflow mutation occurs (no circular side-effect re-application).
    """
    etype, scope = normalize_event_type_and_scope(event_type)
    return QcEvent.objects.create(
        scope=scope,
        event_type=etype,
        timestamp_utc=at or timezone.now(),
        job_id=job.cvat_job_id,
        task_id=job.batch.cvat_task_id if job.batch_id else None,
        workflow_job=job,
        stage=stage or job.stage,
        actor_role=actor_role or (actor.role if actor else ""),
        username=actor.cvat_username if actor else "",
        defect_code=defect_code,
        status=status_val,
        params=params or {},
        applied_to_workflow=True,
    )


def record_qc_event_transactional(
    raw_payload: dict[str, Any],
    *,
    apply_side_effects: bool = True,
    backfill_dedup: bool = False,
) -> tuple[QcEvent, bool]:
    """
    Atomically persists one `QcEvent` and applies all workflow/defect/KPI side effects
    within a single `transaction.atomic()` boundary.

    Returns `(qc_event, created)`. If `idempotency_key` already exists, returns
    `(existing_event, False)` without re-applying side effects.
    """
    norm = normalize_qc_event_payload(raw_payload)
    if backfill_dedup and not norm["idempotency_key"]:
        norm["idempotency_key"] = _compute_backfill_idempotency_key(norm)

    with transaction.atomic():
        if norm["idempotency_key"]:
            existing = QcEvent.objects.select_for_update().filter(
                idempotency_key=norm["idempotency_key"]
            ).first()
            if existing is not None:
                return existing, False

        wjob = WorkflowJob.objects.select_for_update().filter(cvat_job_id=norm["job_id"]).first()
        try:
            ev = QcEvent.objects.create(workflow_job=wjob, **norm)
        except IntegrityError:
            if norm["idempotency_key"]:
                existing = QcEvent.objects.get(idempotency_key=norm["idempotency_key"])
                return existing, False
            raise

        applied = False
        if apply_side_effects:
            if wjob is not None:
                applied = _apply_lifecycle_to_workflow_job(ev, wjob) or applied
            applied = _apply_side_effects_to_synced_models(ev) or applied
            if applied:
                ev.applied_to_workflow = True
                ev.save(update_fields=["applied_to_workflow"])

        return ev, True


def record_qc_events_batch_transactional(
    payloads: Iterable[dict[str, Any]],
    *,
    apply_side_effects: bool = True,
    backfill_dedup: bool = False,
) -> dict[str, Any]:
    """
    All-or-nothing transactional batch ingestion of `qc:*` events.
    If any event in the batch is malformed, the entire batch rolls back.
    """
    items = list(payloads)
    if len(items) > MAX_QC_EVENT_BATCH:
        raise QcEventError(f"Số lượng sự kiện trong một batch vượt quá giới hạn tối đa ({MAX_QC_EVENT_BATCH}).")
    created_ids: list[int] = []
    skipped = 0
    applied_count = 0

    with transaction.atomic():
        for raw in items:
            ev, created = record_qc_event_transactional(
                raw,
                apply_side_effects=apply_side_effects,
                backfill_dedup=backfill_dedup,
            )
            if created:
                created_ids.append(ev.id)
                if ev.applied_to_workflow:
                    applied_count += 1
            else:
                skipped += 1

    return {
        "total": len(items),
        "created": len(created_ids),
        "skipped_duplicates": skipped,
        "applied_to_workflow": applied_count,
        "event_ids": created_ids,
    }


def build_qc_activity_summary(qs: QuerySet[QcEvent], window_days: int = 7) -> dict[str, Any]:
    """
    Transactional Django-ORM port of `cvat-di-ext/backend/cvat_ext/qc_analytics.py::fetch_activity`.
    """
    days = max(1, min(90, int(window_days)))
    since = timezone.now() - timedelta(days=days)
    scoped = qs.filter(timestamp_utc__gte=since)

    total_events = scoped.count()
    dwell_total = scoped.aggregate(s=Sum("dwell_ms"))["s"] or 0
    submissions = scoped.filter(event_type="job_submitted").count()
    rework_returns = scoped.filter(event_type="job_returned_for_rework").count()
    active_users = scoped.exclude(username="").values("username").distinct().count()

    by_type = [
        {"event_type": row["event_type"], "scope": row["scope"], "count": row["c"]}
        for row in scoped.values("event_type", "scope").annotate(c=Count("id")).order_by("-c")[:30]
    ]

    defect_codes = [
        {"code": row["defect_code"], "count": row["c"]}
        for row in scoped.exclude(defect_code="").values("defect_code").annotate(c=Count("id")).order_by("-c")[:15]
    ]

    # Timeline grouped by UTC date using SQL aggregation
    timeline_rows = [
        {
            "date": row["day"].isoformat() if hasattr(row["day"], "isoformat") else str(row["day"]),
            "qc_events": row["qc_events"],
            "dwell_ms": int(row["dwell_ms"] or 0),
        }
        for row in scoped.annotate(day=TruncDate("timestamp_utc", tzinfo=UTC))
        .values("day")
        .annotate(qc_events=Count("id"), dwell_ms=Sum("dwell_ms"))
        .order_by("day")
        if row["day"] is not None
    ]

    users_rows = [
        {
            "username": r["username"],
            "actor_role": r["actor_role"] or None,
            "qc_events": r["qc_events"],
            "dwell_ms": int(r["dwell_ms"] or 0),
            "issues_raised": r["issues_raised"],
            "last_activity": r["last_activity"].isoformat() if r["last_activity"] else None,
        }
        for r in scoped.exclude(username="")
        .values("username", "actor_role")
        .annotate(
            qc_events=Count("id"),
            dwell_ms=Sum("dwell_ms"),
            issues_raised=Count("id", filter=Q(event_type__in=["issue_created", "preqc_ingest"])),
            last_activity=Max("timestamp_utc"),
        )
        .order_by("-qc_events")[:50]
    ]

    tasks_rows = [
        {
            "task_id": r["task_id"],
            "qc_events": r["qc_events"],
            "dwell_ms": int(r["dwell_ms"] or 0),
            "submissions": r["submissions"],
            "rework_returns": r["rework_returns"],
        }
        for r in scoped.exclude(task_id__isnull=True)
        .values("task_id")
        .annotate(
            qc_events=Count("id"),
            dwell_ms=Sum("dwell_ms"),
            submissions=Count("id", filter=Q(event_type="job_submitted")),
            rework_returns=Count("id", filter=Q(event_type="job_returned_for_rework")),
        )
        .order_by("-qc_events")[:100]
    ]

    return {
        "available": True,
        "transactional": True,
        "window_days": days,
        "totals": {
            "qc_events": total_events,
            "dwell_ms": int(dwell_total),
            "active_users": active_users,
            "submissions": submissions,
            "rework_returns": rework_returns,
        },
        "qc_events_by_type": by_type,
        "timeline": timeline_rows,
        "users": users_rows,
        "tasks": tasks_rows,
        "defect_codes": defect_codes,
    }
