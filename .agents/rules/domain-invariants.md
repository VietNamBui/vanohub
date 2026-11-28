---
trigger: always_on
description: "Core VanoHub domain, 4-role RBAC, four-eyes, workflow, CVAT sync, and audit invariants."
---

# Domain & RBAC Invariants

- **Flat 4-role model only:** Valid project roles are strictly `project_manager` (`PM`), `qc2`, `qc1`, and `annotator` (`backend/accounts/models.py:Role`). Never reintroduce removed roles (`Director`, `Team Leader`).
- **Implied role direction:** `PM` dynamically implies `QC2` via `expand_roles()` (`IMPLIED_ROLES`). Never insert synthetic `QC2` `RoleAssignment` rows for a `PM`, and never imply `PM` from `QC2`.
- **Grantable roles:** `PM` may only grant `qc2`, `qc1`, and `annotator` (`GRANTABLE_ROLES` in `backend/projects/views.py` and `frontend/src/shared/types/roles.ts`).
- **Capability-based authorization:** Every endpoint under `/api/projects/<project_id>/...` must inherit `ProjectScopedViewMixin` and declare `required_capabilities` using `accounts.permissions.Cap` constants. Do not scatter ad-hoc role checks in views.
- **404 project isolation:** Users without membership/capabilities in a project must receive `404 NotFound` (never `403`) on project-scoped endpoints so project existence is not leaked.
- **Four-eyes rule (mandatory):**
  - A user must never QC1-review a job they annotated or QC2-audited (`_check_qc1_access` / `_exclude_qc1_four_eyes_conflicts` in `backend/quality/views.py`).
  - A user must never QC2-audit a job they annotated or QC1-reviewed (`four_eyes_conflicts` / `get_stage_history` in `backend/quality/qc2.py`).
  - **Stage-aware `JobIssue` propagation:** Valid QC `JobIssue` authors (`authority_status="valid"`, `author_stage in ("qc1", "qc2")`) feed `get_stage_history`, `_exclude_qc1_four_eyes_conflicts`, and `AnnotatorJobViewSet.claim`. Valid annotator clarifications (`author_stage="annotator"`) and PM `ActivityLog(action="issue.ruling")` are strictly excluded from four-eyes history. Dual `PM + Annotator` self-void (`not_an_issue` via `issues/{id}/rule` or `AnnotatorRequest.resolve` → `resolved` when `user.id in annotator_ids`) is blocked (`403`).
- **Batch & job lifecycle (Hybrid A2):**
  - Moving a Task (`Batch`) to `pending_qc2` initially happens via PM `confirm-qc2` (`BatchViewSet.confirm_qc2`), allowed when `batch` and `dataset` are `active`, zero jobs have `is_locked=True`, ≥ 1 job is `qc1_passed`, and zero jobs are outside `QC2_NON_BLOCKING_STATUSES` (`qc1_passed`, `pending_qc2`, `approved`, `delivered`).
  - Once `batch.qc2_confirmed_at` is set, post-QC2 rework returning via `qc1_pass` (or CVAT sync `POST_QC1_CVAT_STATES`) transitions straight to `pending_qc2` and creates a new frame-level `AuditSample` via `ensure_qc2_sample` (`backend/quality/qc2.py`).
  - Recording a `Delivery` (`DeliveryViewSet.perform_create`) requires active `batch`/`dataset`, ≥ 1 job, all batch jobs `approved` with zero locked jobs and zero `pending` `AuditSample`s, closes any `in_progress` `Audit` to `completed`, and locks/marks the batch and its jobs `delivered`.
  - Respect `is_locked`, `is_escalated` (`EscalationPolicy.BLOCK` vs `WARN_ONLY`), and `Project.annotator_wip_limit` on all job mutations.
- **`JobIssue` two-gate boundary & stock CVAT OPA tamper defense (`backend/quality/issues.py`):**
  - **Two-gate boundary (`Project.issue_gate_enabled`, default `False`):** Submit Gate (`submit_annotation`, `sync.py → pending_qc1`) blocks only valid non-missing `open`/`reopened` issues (`major`/`critical` or `ruled_at` set) and allows `unclear` holds to avoid WIP deadlock (`submit_annotation` fails open to cached local issues with `issue_sync_warning=True` on CVAT error; `sync.py` fails closed). Acceptance Gate (`qc1_pass`, `sync.py` `POST_QC1_CVAT_STATES`, `confirm-qc2`, `AuditSample.pass_`, `DeliveryViewSet.perform_create`) blocks `unclear` and unverified `open`/`reopened`/`addressed` blockers.
  - **Stock CVAT OPA tamper defense:** Lock the opening comment envelope on first valid import (`first_comment_id`, `defect_code`, `primary_category`, `severity`, `source`, `is_clarification`, `track_id`, `shape_id`, `position`), flagging later downgrades/deletes/wipes via `tampered=True` + `tamper_reason`; mirror CVAT `resolved` in `cvat_resolved` only (never closing `JobIssue.status`); authorize every lifecycle comment by `comment.owner` → `CvatAccount` + project roles + four-eyes with monotonic comment floors (`last_applied_lifecycle_comment_id`, `reopened_after_comment_id`).
- **Canonical PostgreSQL lock order:** Acquire `select_for_update(of=("self",))` strictly in `Dataset → Batch → AuditSample → Job → JobIssue → ReviewError → AnnotatorRequest` order (ascending `id` within child tables) across all mutators to prevent deadlocks.
- **CVAT ownership boundary:** CVAT is the annotation data source; VanoHub owns workflow state. `backend/cvat_integration/sync.py` may only sync statuses inside `SYNCABLE_STATUSES` (`pending_annotation`, `annotating`, `rework`, `pending_qc1`, `qc1_reviewing`) and must never overwrite jobs in `qc1_passed`, `pending_qc2`, `approved`, or `delivered`. Outbound CVAT writes (`backend/cvat_integration/assignee.py`, `backend/cvat_integration/client.py`) are strictly limited to CVAT job `assignee` (`PATCH /api/jobs/{id}`) and organization `worker` invitations (`POST /api/invitations?org=<slug>`).
- **Audit trail & notifications:**
  - Record immutable `ActivityLog.record(...)` entries for all state transitions and management actions.
  - Emit `UserNotification` events per the notification matrix in `docs/platform-spec.md`; set `is_pinned_pending=True` on actionable items that remain pinned until resolved.
