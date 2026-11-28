from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from django.conf import settings
from django.db.models import Q
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import workflow_service as wf
from .models import QcEvent, SyncedJob, WorkflowJob, WorkflowUser
from .qc_events import (
    MAX_QC_EVENT_BATCH,
    QcEventError,
    build_qc_activity_summary,
    normalize_event_type_and_scope,
    record_qc_event_transactional,
    record_qc_events_batch_transactional,
)


def _resolve_actor(request: Any) -> WorkflowUser:
    """
    Maps `request.user` (or `X-Workflow-User` override for staff/demo) to a `WorkflowUser`.
    Never elevates an unmapped non-staff user to an existing `pm` or `admin` profile;
    unmapped non-staff users are provisioned with least-privilege `annotator` role.
    """
    is_staff_or_super = bool(
        getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False)
    )
    override = str(request.headers.get("X-Workflow-User") or request.query_params.get("as_user") or "").strip()
    if override and is_staff_or_super:
        found = WorkflowUser.objects.filter(code=override).first()
        if found is not None:
            return found

    if getattr(request.user, "is_authenticated", False):
        by_fk = WorkflowUser.objects.filter(django_user=request.user).first()
        if by_fk is not None:
            return by_fk
        by_name = WorkflowUser.objects.filter(cvat_username__iexact=request.user.username).first()
        if by_name is not None:
            if by_name.django_user_id is None:
                by_name.django_user = request.user
                by_name.save(update_fields=["django_user"])
            return by_name

    # Only staff/superusers may fall back to an existing PM/Admin profile if unmapped
    if is_staff_or_super:
        fallback = (
            WorkflowUser.objects.filter(role="pm").first()
            or WorkflowUser.objects.filter(role="admin").first()
            or WorkflowUser.objects.first()
        )
        if fallback is not None:
            return fallback

    # Auto-provision a least-privilege profile for an unmapped authenticated Django user
    username = getattr(request.user, "username", "user") or "user"
    role = (
        "admin"
        if getattr(request.user, "is_superuser", False)
        else ("pm" if getattr(request.user, "is_staff", False) else "annotator")
    )
    code_base = f"u_{username}"
    code = code_base
    suffix = 1
    while WorkflowUser.objects.filter(code=code).exists():
        suffix += 1
        code = f"{code_base}_{suffix}"

    return WorkflowUser.objects.create(
        code=code,
        django_user=request.user if getattr(request.user, "is_authenticated", False) else None,
        name=username,
        cvat_username=username,
        role=role,
        is_qc=role in ("admin", "pm"),
        employee_id=1001,
    )


def _is_privileged_request(request: Any, actor: WorkflowUser | None = None) -> bool:
    """Returns True if `request.user` is Django staff/superuser or `actor` has QC/Lead/PM/Admin privileges."""
    if getattr(request.user, "is_staff", False) or getattr(request.user, "is_superuser", False):
        return True
    eff_actor = actor if actor is not None else _resolve_actor(request)
    return wf.is_supervisor_user(eff_actor)


def _state_response(actor: WorkflowUser, extra: dict[str, Any] | None = None, http_status: int = status.HTTP_200_OK) -> Response:
    payload = wf.serialize_dashboard_state(actor)
    if extra:
        payload = {**payload, **extra}
    return Response(payload, status=http_status)


def _run_wf(request: Any, fn: Any, *, http_status: int = status.HTTP_200_OK) -> Response:
    actor = _resolve_actor(request)
    try:
        extra = fn(actor)
    except wf.WorkflowPermissionError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except wf.WorkflowError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return _state_response(actor, extra=extra if isinstance(extra, dict) else None, http_status=http_status)


class WorkflowStateView(APIView):
    """GET /api/workflow/state/ — Hydrates the full React DashboardState from Django DB."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Any) -> Response:
        actor = _resolve_actor(request)
        return _state_response(actor)


class WorkflowSwitchUserView(APIView):
    """POST /api/workflow/switch-user/ — Returns state scoped to a target WorkflowUser (staff/dev)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any) -> Response:
        user_id = str(request.data.get("userId") or "").strip()
        target = WorkflowUser.objects.filter(code=user_id).first()
        if target is None:
            return Response({"detail": f"Không tìm thấy người dùng {user_id}"}, status=status.HTTP_400_BAD_REQUEST)
        if not (
            request.user.is_staff
            or request.user.is_superuser
            or target.django_user_id == request.user.id
            or target.cvat_username.lower() == request.user.username.lower()
        ):
            return Response({"detail": "Không có quyền chuyển tài khoản."}, status=status.HTTP_403_FORBIDDEN)
        return _state_response(target)


def _parse_optional_non_negative_int(raw: Any, field_name: str) -> int | None:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    if isinstance(raw, (bool, float)):
        raise wf.WorkflowValidationError(f"Trường {field_name} phải là số nguyên không âm.")
    try:
        val = int(raw)
    except (TypeError, ValueError) as exc:
        raise wf.WorkflowValidationError(f"Trường {field_name} phải là số nguyên không âm.") from exc
    if val < 0:
        raise wf.WorkflowValidationError(f"Trường {field_name} phải là số nguyên không âm.")
    return val


def _require_list_field(raw: Any, field_name: str) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise wf.WorkflowValidationError(f"Trường {field_name} phải là danh sách.")
    return raw


def _require_dict_body(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise wf.WorkflowValidationError("Dữ liệu gửi lên phải là JSON object.")
    return dict(data)


# ---------- Job Action Views


class WorkflowJobAssignView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.assign_job(
                actor,
                job_code,
                str(request.data.get("annotatorId") or ""),
                str(request.data.get("qc1Id") or ""),
            ),
        )


class WorkflowJobReassignView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.reassign_job(
                actor,
                job_code,
                annotator_code=request.data.get("annotatorId"),
                qc1_code=request.data.get("qc1Id"),
            ),
        )


class WorkflowJobSubmitView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        try:
            edited = _parse_optional_non_negative_int(request.data.get("editedCuboids"), "editedCuboids")
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.submit_job(actor, job_code, edited))


class WorkflowJobStartQc1View(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.start_qc1(actor, job_code))


class WorkflowJobQc1PassView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.qc1_pass(actor, job_code))


class WorkflowJobQc1ReturnView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.qc1_return(
                actor,
                job_code,
                str(request.data.get("reason") or ""),
                str(request.data.get("errorCategory") or ""),
            ),
        )


class WorkflowJobStartQc2View(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.start_qc2(actor, job_code))


class WorkflowJobQc2PassView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.qc2_pass(actor, job_code))


class WorkflowJobQc2ReturnQc1View(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.qc2_return_to_qc1(
                actor,
                job_code,
                str(request.data.get("reason") or ""),
                str(request.data.get("errorCategory") or ""),
            ),
        )


class WorkflowJobQc2ReturnAnnoView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.qc2_return_to_anno(
                actor,
                job_code,
                str(request.data.get("reason") or ""),
                str(request.data.get("errorCategory") or ""),
            ),
        )


class WorkflowJobDueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, job_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.set_job_due(
                actor,
                job_code,
                str(request.data.get("step") or ""),
                request.data.get("dueAt"),
            ),
        )


class WorkflowJobsDeliverView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any) -> Response:
        job_ids = request.data.get("jobIds") or []
        if not isinstance(job_ids, list):
            return Response({"detail": "jobIds phải là danh sách."}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.mark_delivered(actor, [str(x) for x in job_ids]))


# ---------- Batch Action Views


class WorkflowBatchPreviewDistributionView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, batch_code: str) -> Response:
        actor = _resolve_actor(request)
        if not (
            getattr(request.user, "is_staff", False)
            or getattr(request.user, "is_superuser", False)
            or actor.role in ("admin", "pm")
        ):
            return Response(
                {"detail": "Bạn không có quyền xem trước phân chia job (chỉ PM hoặc Admin)."},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            team_ids = [str(x) for x in _require_list_field(request.data.get("teamIds"), "teamIds")]
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"rows": wf.preview_distribution(batch_code, team_ids)})


class WorkflowBatchDistributeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, batch_code: str) -> Response:
        try:
            team_ids = [str(x) for x in _require_list_field(request.data.get("teamIds"), "teamIds")]
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.distribute_jobs(actor, batch_code, team_ids))


class WorkflowBatchReassignView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, batch_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.reassign_batch(
                actor,
                batch_code,
                str(request.data.get("step") or ""),
                str(request.data.get("picId") or ""),
            ),
        )


class WorkflowBatchReleaseView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, batch_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.release_batch(actor, batch_code))


class WorkflowBatchAutoLockView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, batch_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.set_auto_lock(actor, batch_code, request.data.get("autoLockAt")))


class WorkflowBatchDueView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, batch_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.set_batch_due(
                actor,
                batch_code,
                request.data.get("dueAt"),
                request.data.get("stepBufferDays"),
            ),
        )


class WorkflowBatchPriorityView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, batch_code: str) -> Response:
        raw_p = request.data.get("priority")
        if isinstance(raw_p, (bool, float)):
            return Response({"detail": "Mức ưu tiên phải từ 1 đến 5"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            prio = int(raw_p)
        except (TypeError, ValueError):
            return Response({"detail": "Mức ưu tiên phải từ 1 đến 5"}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.set_batch_priority(actor, batch_code, prio))


class WorkflowBatchAssignTeamView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, batch_code: str) -> Response:
        team_id = str(request.data.get("teamId") or "").strip()
        return _run_wf(request, lambda actor: wf.assign_batch_team(actor, batch_code, team_id))


class WorkflowTeamPmView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, team_code: str) -> Response:
        pm_id = str(request.data.get("pmId") or "").strip()
        return _run_wf(request, lambda actor: wf.set_team_pm(actor, team_code, pm_id))


class WorkflowUserMoveTeamView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, user_code: str) -> Response:
        raw_to = request.data.get("toTeamId")
        to_team = str(raw_to).strip() if raw_to is not None and str(raw_to).strip() else None
        return _run_wf(request, lambda actor: wf.move_member(actor, user_code, to_team))


# ---------- Audit Action Views


class WorkflowAuditCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any) -> Response:
        try:
            batch_ids = [str(x) for x in _require_list_field(request.data.get("batchIds"), "batchIds")]
            pct = _parse_optional_non_negative_int(request.data.get("percent"), "percent")
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        def _do(actor: WorkflowUser) -> dict[str, Any]:
            audit = wf.create_audit(actor, batch_ids, pct)
            return {"createdAuditId": audit.code}

        return _run_wf(request, _do, http_status=status.HTTP_201_CREATED)


class WorkflowAuditPassJobView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, audit_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.audit_job_pass(actor, audit_code, str(request.data.get("jobId") or "")),
        )


class WorkflowAuditReturnJobView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, audit_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.audit_job_return(
                actor,
                audit_code,
                str(request.data.get("jobId") or ""),
                str(request.data.get("target") or "anno"),
                str(request.data.get("reason") or ""),
                str(request.data.get("errorCategory") or ""),
            ),
        )


class WorkflowAuditCloseView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, audit_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.close_audit(actor, audit_code))


# ---------- Teams, Users, Projects, DataTypes, Favorites


class WorkflowTeamsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any) -> Response:
        try:
            raw_steps = _require_list_field(request.data.get("allowedSteps"), "allowedSteps")
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        def _do(actor: WorkflowUser) -> dict[str, Any]:
            t = wf.create_team(
                str(request.data.get("name") or ""),
                raw_steps,
                bool(request.data.get("canQa", False)),
                actor=actor,
            )
            return {"createdTeamId": t.code}

        return _run_wf(request, _do, http_status=status.HTTP_201_CREATED)


class WorkflowTeamDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request: Any, team_code: str) -> Response:
        try:
            body = _require_dict_body(request.data)
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.update_team(team_code, body, actor=actor))

    def delete(self, request: Any, team_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.delete_team(team_code, actor=actor))


class WorkflowTeamMembersView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, team_code: str) -> Response:
        return _run_wf(
            request,
            lambda actor: wf.add_team_member(team_code, str(request.data.get("userId") or ""), actor=actor),
        )


class WorkflowTeamMemberDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request: Any, team_code: str, user_code: str) -> Response:
        return _run_wf(request, lambda actor: wf.remove_team_member(team_code, user_code, actor=actor))


class WorkflowUserDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def patch(self, request: Any, user_code: str) -> Response:
        try:
            body = _require_dict_body(request.data)
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.update_user(user_code, body, actor=actor))


class WorkflowDataTypeDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def put(self, request: Any, dt_code: str) -> Response:
        try:
            body = _require_dict_body(request.data)
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.update_data_type(dt_code, body, actor=actor))


class WorkflowProjectAssignView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any, project_code: str) -> Response:
        try:
            pm_ids = [str(x) for x in _require_list_field(request.data.get("pmIds"), "pmIds")]
        except wf.WorkflowError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.assign_project(actor, project_code, pm_ids))


class WorkflowFavoriteToggleView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request: Any) -> Response:
        target_id = str(request.data.get("targetId") or "").strip()
        if not target_id:
            return Response({"detail": "Thiếu targetId."}, status=status.HTTP_400_BAD_REQUEST)
        return _run_wf(request, lambda actor: wf.toggle_favorite(actor, target_id))


# ==============================================================================
# Transactional `qc:*` Custom Event Endpoints (Ported from `cvat-di-ext`)
# ==============================================================================


def _verify_hmac_signature(request: Any) -> bool:
    """Verifies HMAC-SHA256 from either `X-Signature-256` or `X-CVAT-Signature-256`."""
    secret = getattr(settings, "CVAT_WEBHOOK_SECRET", "")
    if not secret:
        return False
    sig = str(
        request.headers.get("X-Signature-256")
        or request.headers.get("X-CVAT-Signature-256")
        or ""
    ).strip()
    if not sig:
        return False
    computed = "sha256=" + hmac.new(secret.encode("utf-8"), request.body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, computed)


def _verify_hmac_or_authenticated(request: Any) -> tuple[Response | None, bool]:
    """
    Allows either authenticated DRF user OR valid HMAC-SHA256 webhook signature.
    Returns `(error_response, is_hmac_verified)`.
    """
    if _verify_hmac_signature(request):
        return None, True
    if getattr(request.user, "is_authenticated", False):
        return None, False
    if getattr(settings, "CVAT_WEBHOOK_SECRET", ""):
        return Response({"detail": "Chữ ký HMAC không hợp lệ."}, status=status.HTTP_401_UNAUTHORIZED), False
    return Response({"detail": "Authentication credentials were not provided."}, status=status.HTTP_401_UNAUTHORIZED), False


def _serialize_qc_event(ev: QcEvent) -> dict[str, Any]:
    return {
        "id": ev.id,
        "idempotency_key": ev.idempotency_key,
        "scope": ev.scope,
        "event_type": ev.event_type,
        "timestamp_utc": ev.timestamp_utc.isoformat(),
        "job_id": ev.job_id,
        "task_id": ev.task_id,
        "project_id": ev.project_id,
        "workflow_job_code": ev.workflow_job.code if ev.workflow_job else None,
        "stage": ev.stage,
        "actor_role": ev.actor_role,
        "user_id": ev.user_id,
        "username": ev.username,
        "issue_id": ev.issue_id,
        "defect_code": ev.defect_code,
        "severity": ev.severity,
        "status": ev.status,
        "frame_number": ev.frame_number,
        "frames_span": ev.frames_span,
        "track_id": ev.track_id,
        "shape_id": ev.shape_id,
        "label_class": ev.label_class,
        "dwell_ms": ev.dwell_ms,
        "params": ev.params,
        "metric_delta": ev.metric_delta,
        "extra": ev.extra,
        "applied_to_workflow": ev.applied_to_workflow,
    }


def _extract_raw_field(raw: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if raw.get(k) is not None:
            return raw.get(k)
    nested = raw.get("payload")
    if isinstance(nested, str) and nested.strip().startswith("{"):
        try:
            nested = json.loads(nested)
        except ValueError:
            nested = None
    if isinstance(nested, dict):
        for k in keys:
            if nested.get(k) is not None:
                return nested.get(k)
    return None


def _sanitize_annotator_qc_event(raw: Any, request: Any, actor: WorkflowUser) -> dict[str, Any]:
    """
    For non-privileged annotators, verifies job assignment, forces identity fields
    from `request.user` / `actor`, and enforces the `client_` telemetry prefix so
    server lifecycle/defect events cannot be forged or pollute `QcEventsActivityView`.
    """
    if not isinstance(raw, dict):
        raise QcEventError("Payload sự kiện QC phải là JSON object.")

    raw_job_id = _extract_raw_field(raw, "job_id")
    if raw_job_id is None or isinstance(raw_job_id, bool) or not str(raw_job_id).isdigit():
        raise QcEventError("Thiếu hoặc sai `job_id` hợp lệ (> 0).")
    job_id = int(raw_job_id)
    if job_id <= 0:
        raise QcEventError("Thiếu hoặc sai `job_id` hợp lệ (> 0).")

    wjob = WorkflowJob.objects.filter(cvat_job_id=job_id).first()
    sjob = SyncedJob.objects.filter(cvat_job_id=job_id).first()
    actor_uname = (actor.cvat_username or getattr(request.user, "username", "")).strip().lower()
    is_assigned = (wjob is not None and wjob.annotator_id == actor.id) or (
        wjob is None and sjob is not None and sjob.annotator_username.strip().lower() == actor_uname
    )
    if not is_assigned:
        raise wf.WorkflowPermissionError(f"Bạn không được phân công job #{job_id}.")

    item = dict(raw)
    for alias in ("user_name", "actor", "obj_val"):
        item.pop(alias, None)

    raw_et = _extract_raw_field(raw, "event_type")
    raw_sc = _extract_raw_field(raw, "scope")
    et, _ = normalize_event_type_and_scope(raw_et, raw_sc)
    if not et.lower().startswith("client_"):
        et = f"client_{et}"
    et = et[:64]

    item["job_id"] = job_id
    item["event_type"] = et
    item["scope"] = f"qc:{et}"[:96]
    item["username"] = (actor.cvat_username or getattr(request.user, "username", "")).strip()[:150]
    item["user_id"] = getattr(request.user, "id", None)
    item["actor_role"] = (actor.role or "annotator")[:32]
    return item


class QcEventsView(APIView):
    """
    GET  /api/qc-events/ — Query persisted transactional `qc:*` custom events (scoped for annotators).
    POST /api/qc-events/ — Ingest single event or batch (`{"events": [...]}`) transactionally.
    """

    permission_classes = [permissions.AllowAny]
    throttle_scope = "qc_events"

    def get(self, request: Any) -> Response:
        if not getattr(request.user, "is_authenticated", False):
            return Response({"detail": "Authentication credentials were not provided."}, status=status.HTTP_401_UNAUTHORIZED)

        actor = _resolve_actor(request)
        qs = QcEvent.objects.select_related("workflow_job").all()
        if not _is_privileged_request(request, actor):
            qs = qs.filter(
                Q(username__iexact=actor.cvat_username)
                | Q(workflow_job__annotator=actor)
            )

        for param, field in (
            ("job_id", "job_id"),
            ("task_id", "task_id"),
            ("project_id", "project_id"),
        ):
            val = request.query_params.get(param)
            if val and str(val).isdigit():
                qs = qs.filter(**{field: int(val)})
        for param, field in (
            ("scope", "scope"),
            ("event_type", "event_type"),
            ("username", "username"),
            ("defect_code", "defect_code"),
        ):
            val = request.query_params.get(param)
            if val:
                qs = qs.filter(**{field: str(val)})

        raw_limit = request.query_params.get("limit", "100")
        limit = max(1, min(500, int(raw_limit) if str(raw_limit).isdigit() else 100))
        rows = list(qs[:limit])
        return Response({"count": len(rows), "results": [_serialize_qc_event(ev) for ev in rows]})

    def post(self, request: Any) -> Response:
        auth_err, is_hmac = _verify_hmac_or_authenticated(request)
        if auth_err is not None:
            return auth_err

        data = request.data
        raw_apply = bool(data.get("apply_side_effects", True)) if isinstance(data, dict) else True
        actor = None if is_hmac else _resolve_actor(request)
        # Non-privileged annotators cannot trigger authoritative workflow/defect side effects via raw event POST
        can_apply_effects = is_hmac or _is_privileged_request(request, actor)
        apply_side_effects = raw_apply and can_apply_effects

        delivery_hdr = str(request.headers.get("X-CVAT-Delivery") or "").strip()

        try:
            if isinstance(data, list):
                if len(data) > MAX_QC_EVENT_BATCH:
                    return Response(
                        {"detail": f"Số lượng sự kiện trong một batch vượt quá giới hạn ({MAX_QC_EVENT_BATCH})."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                items = (
                    data
                    if can_apply_effects
                    else [_sanitize_annotator_qc_event(ev, request, actor) for ev in data]  # type: ignore[arg-type]
                )
                summary = record_qc_events_batch_transactional(items, apply_side_effects=apply_side_effects)
                return Response(summary, status=status.HTTP_201_CREATED)
            if isinstance(data, dict) and isinstance(data.get("events"), list):
                raw_events = data["events"]
                if len(raw_events) > MAX_QC_EVENT_BATCH:
                    return Response(
                        {"detail": f"Số lượng sự kiện trong một batch vượt quá giới hạn ({MAX_QC_EVENT_BATCH})."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                items = (
                    raw_events
                    if can_apply_effects
                    else [_sanitize_annotator_qc_event(ev, request, actor) for ev in raw_events]  # type: ignore[arg-type]
                )
                summary = record_qc_events_batch_transactional(
                    items, apply_side_effects=apply_side_effects
                )
                return Response(summary, status=status.HTTP_201_CREATED)
            if isinstance(data, dict):
                payload = (
                    dict(data)
                    if can_apply_effects
                    else _sanitize_annotator_qc_event(data, request, actor)  # type: ignore[arg-type]
                )
                if delivery_hdr and not payload.get("idempotency_key") and not payload.get("event_id"):
                    payload["idempotency_key"] = delivery_hdr
                ev, created = record_qc_event_transactional(payload, apply_side_effects=apply_side_effects)
                return Response(
                    {"created": created, "event": _serialize_qc_event(ev)},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
                )
        except wf.WorkflowPermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except QcEventError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Payload sự kiện QC không hợp lệ."}, status=status.HTTP_400_BAD_REQUEST)


class QcEventsBackfillView(APIView):
    """
    POST /api/qc-events/backfill/ — Transactional, idempotent import of `cvat-di-ext`
    `qc_events.jsonl` lines or JSON array (Supervisor / Staff only).
    """

    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "qc_events"

    def post(self, request: Any) -> Response:
        if not _is_privileged_request(request):
            return Response(
                {"detail": "Chỉ quản trị viên, PM, Team Lead hoặc QC mới được phép backfill dữ liệu sự kiện."},
                status=status.HTTP_403_FORBIDDEN,
            )
        data = request.data
        apply_side_effects = bool(data.get("apply_side_effects", False)) if isinstance(data, dict) else False
        events: list[dict[str, Any]] = []

        if isinstance(data, dict) and isinstance(data.get("jsonl"), str):
            for idx, line in enumerate(data["jsonl"].splitlines(), start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    obj = json.loads(stripped)
                except ValueError as exc:
                    return Response(
                        {"detail": f"JSONL không hợp lệ ở dòng {idx}: {exc}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if not isinstance(obj, dict):
                    return Response(
                        {"detail": f"Dòng {idx} phải là JSON object."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                events.append(obj)
                if len(events) > MAX_QC_EVENT_BATCH:
                    return Response(
                        {"detail": f"Số lượng sự kiện trong một batch vượt quá giới hạn ({MAX_QC_EVENT_BATCH})."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        elif isinstance(data, dict) and isinstance(data.get("events"), list):
            events = data["events"]
        elif isinstance(data, list):
            events = data
        else:
            return Response({"detail": "Cần truyền `jsonl` hoặc `events`."}, status=status.HTTP_400_BAD_REQUEST)

        if len(events) > MAX_QC_EVENT_BATCH:
            return Response(
                {"detail": f"Số lượng sự kiện trong một batch vượt quá giới hạn ({MAX_QC_EVENT_BATCH})."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            summary = record_qc_events_batch_transactional(
                events,
                apply_side_effects=apply_side_effects,
                backfill_dedup=True,
            )
        except QcEventError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(summary, status=status.HTTP_201_CREATED)


class QcEventsActivityView(APIView):
    """GET /api/qc-events/activity/ — Transactional DB port of `cvat-di-ext` `qc_analytics.fetch_activity`."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Any) -> Response:
        actor = _resolve_actor(request)
        if not _is_privileged_request(request, actor):
            return Response(
                {"detail": "Phân tích hoạt động QC chỉ dành cho QC, Team Lead, PM hoặc Admin."},
                status=status.HTTP_403_FORBIDDEN,
            )
        raw_days = request.query_params.get("days", "7")
        days = int(raw_days) if str(raw_days).isdigit() else 7
        qs = QcEvent.objects.all()

        task_id = request.query_params.get("task_id")
        job_id = request.query_params.get("job_id")
        project_id = request.query_params.get("project_id")
        scope_q = Q()
        if task_id and str(task_id).isdigit():
            scope_q |= Q(task_id=int(task_id))
        if job_id and str(job_id).isdigit():
            scope_q |= Q(job_id=int(job_id))
        if scope_q:
            qs = qs.filter(scope_q)
        if project_id and str(project_id).isdigit():
            qs = qs.filter(project_id=int(project_id))

        return Response(build_qc_activity_summary(qs, window_days=days))
