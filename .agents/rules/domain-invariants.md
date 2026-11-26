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
  - A user must never QC1-review a job they annotated.
  - A user must never QC2-audit a job they annotated or QC1-reviewed (`_four_eyes_conflicts` in `backend/quality/views.py`).
- **Batch & job lifecycle:**
  - Moving a batch to `pending_qc2` happens exclusively via PM `confirm-qc2` when the batch is `active` and 100% of its jobs are `qc1_passed`.
  - Recording a `Delivery` requires all batch jobs to be `approved` with zero open audits, and locks/marks the batch and its jobs delivered.
  - Respect `is_locked`, `is_escalated` (`EscalationPolicy.BLOCK` vs `WARN_ONLY`), and `Project.annotator_wip_limit` on all job mutations.
- **CVAT ownership boundary:** CVAT is the annotation data source; VanoHub owns workflow state. `backend/cvat_integration/sync.py` may only sync statuses inside `SYNCABLE_STATUSES` (`annotation` and `qc1` stages) and must never overwrite jobs in `pending_qc2`, `approved`, or `delivered`.
- **Audit trail & notifications:**
  - Record immutable `ActivityLog.record(...)` entries for all state transitions and management actions.
  - Emit `UserNotification` events per the notification matrix in `docs/platform-spec.md`; set `is_pinned_pending=True` on actionable items that remain pinned until resolved.
