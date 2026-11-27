# API contracts and change procedure

Prepared: 2026-11-27. This is a populated contract inventory and implementation guide. It is not a complete generated OpenAPI description of the live local application.

## 1. Ownership and boundaries

Maintain separate surfaces:

| Surface | Authority | Documentation treatment |
| --- | --- | --- |
| VanoHub API consumed by its frontend/integrations | Active URL configuration, views/serializers, accepted behavior, and contract tests | One reproducible current OpenAPI artifact; behavioral explanations here |
| Native CVAT API consumed by VanoHub | The actual deployed CVAT version and its published schema/source | Reference or pin that schema; document adapter expectations rather than copying the whole API |
| Proposed VanoHub/CVAT/gateway extensions | Accepted requirement and a clearly labeled proposal | Keep proposed operations separate until implemented and verified |

The product specification defines intended behavior. Current code and runtime evidence establish implemented behavior. A schema disagreement is a defect to resolve, not permission to silently change either side.

Do not publish a new custom route under CVAT's existing API documentation unless the route actually exists in the selected CVAT deployment. Shared Django/DRF technology does not automatically provide shared permissions, schema tooling, or resource isolation.

## 2. Verified endpoint inventory (`0beace7`)

Source: `feature/issue-logger` at `0beace7`; [root URLs](../../backend/config/urls.py), [accounts](../../backend/accounts/urls.py), [projects](../../backend/projects/urls.py), [teams](../../backend/teams/urls.py), [jobs](../../backend/jobs/urls.py), [quality](../../backend/quality/urls.py), [analytics](../../backend/analytics/urls.py), and [cvat_integration](../../backend/cvat_integration/urls.py).

All `/api/projects/{id}/...` views inherit `ProjectScopedViewMixin` + `HasProjectCapability` (`404` outside membership; `403` when missing capability). Global endpoints require `IsAuthenticated` unless noted.

### Auth & Account (`/api/auth/`)

| Endpoint / View | Methods | Auth / Capability & Behavior |
| --- | --- | --- |
| `/api/auth/token/`, `/api/auth/token/refresh/` | `POST` | SimpleJWT login and refresh (`AllowAny` token endpoints). |
| `/api/auth/me/` (`MeView`) | `GET`, `PATCH` | `IsAuthenticated`; current user profile, preferences, `cvat_account`, project roles. |
| `/api/auth/me/password/` (`ChangePasswordView`) | `POST` | `IsAuthenticated`; returns `204` and clears `initial_password_encrypted`. |

### CVAT Integration (`/api/cvat/`)

| Endpoint / View | Methods | Auth / Capability & Behavior |
| --- | --- | --- |
| `/api/cvat/status/` (`status`) | `GET` | `IsAuthenticated`; calls `CvatClient.about()` (timeout `5s`). Returns `200` with `{connected, url, version}` or `{connected: false, url, detail}` with sanitized error text. |
| `/api/cvat/link/` (`link`) | `GET`, `POST`, `DELETE` | `IsAuthenticated`; `GET` returns `CvatAccount` state + `jobs_held`. `POST {"token"}` verifies PAT once via `/users/self` (never stores token), links `CvatAccount`, pushes held-job assignees, and quietly syncs orgs (`sync_organizations_quietly`). `DELETE` unlinks and clears CVAT assignees on held jobs. |
| `/api/cvat/sync-organizations/` (`sync_organizations_view`) | `POST` | `user.is_pm()`; pulls CVAT orgs/memberships into VanoHub `Project` + `RoleAssignment` (`owner`/`maintainer` -> `project_manager`; other linked members default to `annotator`) and filters summary to caller's orgs unless superuser; maps `CvatError` to `502`. |

### Projects, Members, Data, Delivery & Notifications (`/api/projects/`)

| Endpoint / View | Methods | Auth / Capability & Behavior |
| --- | --- | --- |
| `/api/projects/` (`ProjectViewSet`) | `GET`, `POST` | Membership-filtered list; `create` requires `user.is_pm()`. |
| `/api/projects/{id}/` (`ProjectViewSet`) | `GET`, `PUT`, `PATCH` | Membership-filtered detail; `update`/`partial_update` requires `PROJECT_MANAGER` of that project or superuser. |
| `/api/projects/{id}/settings/` (`ProjectSettingsView`) | `GET`, `PATCH` | `VIEW_PROJECT` / `MANAGE_SETTINGS`; rework, `escalation_policy`, `annotator_wip_limit`, `sampling_rate`, thresholds, KPI targets. |
| `/api/projects/{id}/members/` (`ProjectMembersView`) | `GET`, `POST` | `VIEW_PROJECT` / `MANAGE_TEAM`; `GET` lists org members, expanded roles, `cvat_linked`, `has_initial_password`; `POST` creates account with encrypted temporary password. |
| `/api/projects/{id}/members/{uid}/credential/` (`MemberCredentialView`) | `GET` | `MANAGE_TEAM`; returns `{username, password, status}` (`initial`/`changed`/`unreadable`) and logs `member.view_password`. |
| `/api/projects/{id}/members/{uid}/reset-password/` (`MemberResetPasswordView`) | `POST` | `MANAGE_TEAM`; regenerates temp password (`200`), rejects self and PMs. |
| `/api/projects/{id}/members/{uid}/roles/` (`ProjectMemberRolesView`) | `POST` | `MANAGE_TEAM`; grants direct role (`qc2`, `qc1`, `annotator`). |
| `/api/projects/{id}/members/{uid}/roles/{role}/` (`ProjectMemberRoleDetailView`) | `DELETE` | `MANAGE_TEAM`; revokes grantable role after active-work checks (rejects `project_manager` and last role). |
| `/api/projects/{id}/permission-matrix/` (`PermissionMatrixView`) | `GET` | `VIEW_PROJECT`; read-only `CAPABILITY_ROLES` and `implied_roles`. |
| `/api/projects/{id}/cvat-sync/` (`ProjectCvatSyncView`) | `POST` | `MANAGE_DATA`; body `{"count_objects": bool}`; syncs CVAT Projects→`Dataset`, Tasks→`Batch`, annotation Jobs→`Job` outside DB transaction, respects `SYNCABLE_STATUSES` + Hybrid A2 gate (`QC1_PASSED` until `batch.qc2_confirmed_at`), pushes assignees, maps `CvatError` to `502`. |
| `/api/projects/{id}/datasets/` & `.../{pk}/`, `.../{pk}/labels/`, `.../{pk}/lock/`, `.../{pk}/unlock/` (`DatasetViewSet`) | `GET`, `PUT`, `PATCH`, `POST` | `VIEW_JOBS` for list/retrieve, `MANAGE_DATA` for update/labels/lock/unlock; no `create`/`destroy`. |
| `/api/projects/{id}/batches/` & `.../{pk}/`, `.../{pk}/lock/`, `.../{pk}/unlock/`, `.../{pk}/confirm-qc2/` (`BatchViewSet`) | `GET`, `PUT`, `PATCH`, `POST` | `VIEW_PROJECT` for list, `VIEW_JOBS` for retrieve, `MANAGE_DATA` for update/actions. `confirm-qc2` enforces 100% QC1 passed (`QC2_NON_BLOCKING_STATUSES`) & 0 locked jobs, sets `qc2_confirmed_at`/`qc2_confirmed_by`, moves `QC1_PASSED` → `PENDING_QC2`, creates `AuditSample` rows, schedules CVAT assignee push. No per-batch `import-cvat`/`sync-cvat` action exists on `BatchViewSet`. |
| `/api/projects/{id}/deliveries/` (`list`, `create`, `candidates`) & `.../{pk}/` (`update`, `partial_update`; no `retrieve`) (`DeliveryViewSet`) | `GET` (list/`candidates`), `POST`, `PUT`, `PATCH` (`405` on `GET .../{pk}/`) | `MANAGE_DELIVERY` / `VIEW_DASHBOARD` (list & `candidates`), `MANAGE_DELIVERY` (create/update). `perform_create` requires all batch jobs `APPROVED`, 0 locked, 0 pending `AuditSample`s; transitions jobs + batch to `DELIVERED` and closes open `Audit`s to `COMPLETED`. |
| `/api/projects/{id}/activity/` & `.../{pk}/` (`ActivityLogViewSet`) | `GET` | `VIEW_ACTIVITY`; read-only paginated audit trail (`StandardPagination`). |
| `/api/projects/{id}/announcements/` (`AnnouncementViewSet`) | `GET`, `POST` | `VIEW_PROJECT` / `SEND_ANNOUNCEMENT`; role/team-filtered reads. |
| `/api/projects/{id}/guidelines/` (`GuidelineViewSet`) | `GET`, `POST` | `VIEW_GUIDELINES` / `MANAGE_QUALITY_CATALOG`; append-only versioned Markdown. |
| `/api/projects/{id}/notifications/` & `.../mark-read/` (`ProjectNotificationsView`, `MarkNotificationsReadView`) | `GET`, `POST` | `VIEW_PROJECT`; merges persisted `UserNotification`, dynamic deadline warnings, and unread `Announcement`s. |

### Teams (`/api/projects/{id}/teams/`)

| Endpoint / View | Methods | Auth / Capability & Behavior |
| --- | --- | --- |
| `/api/projects/{id}/teams/` & `.../{pk}/` (`TeamViewSet`) | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` | `MANAGE_TEAM` / `VIEW_DASHBOARD` (reads), `MANAGE_TEAM` (writes). |
| `.../teams/{pk}/add-member/`, `.../remove-member/`, `.../set-capacity/`, `.../teams/transfer/` (`TeamViewSet`) | `POST` | `MANAGE_TEAM`; defaults unroled new members to `annotator` and logs `ActivityLog`. |
| `/api/projects/{id}/teams/workload/` (`TeamViewSet`) | `GET` | `MANAGE_TEAM` / `VIEW_DASHBOARD`; annotator/QC1 active holding, overdue, due-soon, escalated counts. |

### Jobs & Annotator Workflow (`/api/projects/{id}/...`)

| Endpoint / View | Methods | Auth / Capability & Behavior |
| --- | --- | --- |
| `/api/projects/{id}/jobs/` & `.../{pk}/` (`JobViewSet`) | `GET` | `VIEW_JOBS`; paginated list (`StandardPagination`) and detail with `timeline` and `errors`. |
| `.../jobs/{pk}/assign/`, `deadline/`, `lock/`, `unlock/`, `resolve-escalation/`, `.../jobs/bulk-assign/`, `bulk-deadline/`, `bulk-move-batch/` (`JobViewSet`) | `POST` | `MANAGE_JOBS`; enforces four-eyes, `ASSIGN_LOCKED_STATUSES`, and `schedule_assignee_push`; `bulk-move-batch` rejects `cvat_job_id`-linked jobs. |
| `/api/projects/{id}/job-queue/` (`JobQueueView`) | `GET` | `VIEW_JOBS`; stage aggregates (`annotation`, `qc1`, `qc2`, `done`). |
| `/api/projects/{id}/annotator/jobs/`, `.../{pk}/`, `.../claim/`, `.../{pk}/start/`, `.../{pk}/submit/` (`AnnotatorJobViewSet`) | `GET`, `POST` | `ANNOTATE_JOBS`; `claim` enforces WIP limit (`skip_locked`, team pool, four-eyes); `submit` currently still accepts optional manual `object_count` (open under D05). |
| `/api/projects/{id}/annotator/requests/`, `.../{pk}/`, `.../{pk}/resolve/` (`AnnotatorRequestViewSet`) | `GET`, `POST` | `ANNOTATE_JOBS` / `MANAGE_JOBS` (read), `ANNOTATE_JOBS` (create `error_dispute`/`data_issue`), `MANAGE_JOBS` (`resolve` voids linked `ReviewError` on `resolved`). |
| `/api/projects/{id}/annotator/search/?q=` (`AnnotatorQuickSearchView`) | `GET` | `ANNOTATE_JOBS`; top 8 matching annotator jobs ordered by DB06 priority. |

### Quality (`/api/projects/{id}/...`)

| Endpoint / View | Methods | Auth / Capability & Behavior |
| --- | --- | --- |
| `/api/projects/{id}/error-categories/` & `.../{pk}/` (`ErrorCategoryViewSet`) | `GET` (list), `POST`, `PUT`, `PATCH` | `VIEW_PROJECT` (list), `MANAGE_QUALITY_CATALOG` (writes); no retrieve/delete (`is_active` toggle only). |
| `/api/projects/{id}/audits/` & `.../{pk}/` (`AuditViewSet`) | `GET` | **Read-only** (`MANAGE_AUDITS`, `PERFORM_AUDIT`, `VIEW_DASHBOARD`). Audits are auto-created by `ensure_qc2_sample` and closed on `Delivery`. No manual `create`, `preview`, `accept`, `reject`, or `partial_reject` endpoints exist. |
| `/api/projects/{id}/audit-samples/` & `.../{pk}/` (`AuditSampleViewSet`) | `GET` | `PERFORM_AUDIT` (PM with `MANAGE_AUDITS` sees project unless `?mine=1`). Exposes `frames` (frame-level QC2) and `checked_object_count` (`null` until D05 settles frame denominator). |
| `/api/projects/{id}/audit-samples/{pk}/pass/`, `.../reject/` (`AuditSampleViewSet`) | `POST` | `PERFORM_AUDIT`; enforces four-eyes & active batch. `pass/` moves `PENDING_QC2` → `APPROVED`. `reject/` requires `errors[]` (`category`, optional `severity`, `verdict` `fail|edge`, `frame_number`, `cvat_object_id`, `is_missing_object`, `location`, `description`) and `rework_scope`; moves job → `REWORK` and schedules CVAT assignee push. |
| `/api/projects/{id}/audit-samples/{pk}/assign/` (`AuditSampleViewSet`) | `POST` | `MANAGE_AUDITS`; reassigns pending sample auditor (checks `Role.QC2` and four-eyes). |
| `/api/projects/{id}/audit-strategy/` (`AuditStrategyView`) | `GET` | `MANAGE_AUDITS`; returns `sampling_rate`, `can_edit`, settings change history, and sample counts. |
| `/api/projects/{id}/qc1/jobs/`, `.../{pk}/`, `.../start/`, `.../pass/`, `.../reject/` (`Qc1JobViewSet`) | `GET`, `POST` | `PERFORM_QC1`; excludes four-eyes conflicts and enforces team pool. `pass/` moves to `QC1_PASSED` (pre-`confirm-qc2`) or straight to `PENDING_QC2` + `ensure_qc2_sample` (post-`confirm-qc2`). `reject/` requires structured `errors[]` + `rework_scope`. |

### Analytics (`/api/projects/{id}/...`)

| Endpoint / View | Methods | Auth / Capability & Behavior |
| --- | --- | --- |
| `/api/projects/{id}/overview/` (`ProjectOverviewView`) | `GET` | `VIEW_DASHBOARD` |
| `/api/projects/{id}/team-ranking/` (`TeamRankingView`) | `GET` | `VIEW_DASHBOARD` |
| `/api/projects/{id}/member-performance/` (`MemberPerformanceView`) | `GET` | `VIEW_DASHBOARD` |
| `/api/projects/{id}/annotator/dashboard/` (`AnnotatorDashboardView`) | `GET` | `ANNOTATE_JOBS` |
| `/api/projects/{id}/annotator/analytics/` (`AnnotatorAnalyticsView`) | `GET` | `ANNOTATE_JOBS` |
| `/api/projects/{id}/qc1-summary/` (`Qc1SummaryView`) | `GET` | `PERFORM_QC1` or `VIEW_DASHBOARD` |
| `/api/projects/{id}/qc2-summary/` (`Qc2SummaryView`) | `GET` | `PERFORM_AUDIT` or `VIEW_DASHBOARD` |

**Pending-definition metrics (`backend/analytics/views.py`):** In `ProjectOverviewView` and `Qc2SummaryView`, `CL02` (`defect_error_rate` / `error_percent_in_job`), `CL05` (`defect_rate_by_severity`), and `CL11` (`quality_cl`) currently return `{"value": null, "status": "pending_definition", "formula": ...}` alongside `NS04` (`audit_speed`) and `DB02`/`DB03` (`estimated_completion`) until frame-level `checked_object_count` (`D05`) and duration semantics (`D06`) are settled.

## 3. Current schema workflow

T00 confirmed on `0beace7` that no OpenAPI schema generator (`drf-spectacular` is absent from `backend/Pipfile` and `backend/Pipfile.lock`), OpenAPI route (`backend/config/urls.py`), or schema artifact (`docs/api/openapi.yaml`) currently exists. Generator selection and schema generation belong to T03, after T02's green baseline and affected T01 decisions.

If none exists:

1. Select a generator compatible with the actual installed Django/DRF versions and existing dependency policy.
2. Generate from active routes and serializers, adding explicit schema annotations for permissions, custom actions, responses, and nontrivial errors.
3. Record the exact command, environment, output path, and source revision. A conventional target is `docs/api/openapi.yaml`; this package does not create a misleading empty schema.
4. Validate the schema and compare representative real responses/errors against it.
5. Review schema diffs alongside code. Keep frontend types or generated clients synchronized through one documented command if code generation is adopted.

For implemented operations, the generated artifact is the current machine-readable contract. Do not maintain a second full handwritten copy. For a new operation, a small contract-first proposal can guide implementation; reconcile it with generated output before marking the operation current.

Record generator/schema changes in [changes.md](../refactoring/changes.md). A docs renderer or DRF browsable API alone is not a contract-parity check.

## 4. Contract entry for every changed operation

Use this template in the task or proposal, then retain the enduring details here or in a dedicated proposal when its size warrants it:

~~~text
Contract ID / status / owner:
Source revision and related decision/task:
Provider, consumers, method, path:
Identifier meaning and tenant scope:
Authentication and required capability:
Request fields, types, bounds, null/omitted semantics:
Success status, fields, units, timestamps, pagination:
Error statuses and safe error body:
State transition, side effects, locks/concurrency:
Idempotency, retries, timeout and stale-data behavior:
Examples: valid, boundary, unauthorized, conflict/upstream failure:
Compatibility and consumer migration:
Schema source/generation and verification:
~~~

Cover behavior as well as JSON shape. A status enum change, different authorization, new default, changed unit, or automatic workflow transition is a contract change even when field names remain the same.

Adding an optional field is not automatically compatible with strict validators; adding an enum value may break exhaustive frontend handling. Reuse the application's accepted error shape instead of introducing a new envelope during an unrelated refactor.

For project-scoped endpoints, preserve the accepted project-isolation behavior and capability checks. The reference repository rules require 404 isolation outside project scope. Do not blindly copy that rule onto authentication or globally scoped operations without checking their actual contract.

## 5. Existing proposals to evaluate, not implement automatically

These paths come from [the reference specification's backlog](../platform-spec.md#backlog--kiến-trúc-plugin-stub-trên-nền-cvat-base-gốc). They are not established live routes.

| Proposal | Purpose | Contract decisions needed |
| --- | --- | --- |
| B3: `POST /api/projects/{id}/jobs/{job_id}/plugin-findings/` | Receive suggested auto-QC findings for human review | Project/job ownership; plugin identity; finding identity/deduplication; severity/confidence; suggested/confirmed lifecycle; no automatic job transition |
| B4: `POST /api/projects/{id}/telemetry/` | Ingest a bounded event batch | Service identity and allowed source; event schema and units; user/job mapping; limits; atomic vs partial acceptance; deduplication and retry response |
| B5: `POST /api/integrations/cvat/webhook/` | Trigger sync from supported CVAT events | Actual version-specific signature/header/body rules; event identity; replay/duplicate behavior; persistence/acknowledgment; safe retry and ordering |
| Optional GET telemetry/summary extension | Expose a demonstrated gap through an API | Provider/hosting decision D04, exact path, permitted project/job scope, filters, pagination, time window, data freshness and resource budget |

A GET-only query gateway and POST ingestion/webhook endpoints are different surfaces. Choose the required direction and owner explicitly; do not use GET to trigger business mutations.

### B4 design checklist, ready for the first proposal

The reference backlog proposes event fields such as project, job, user, source, event type, occurrence time, duration, object delta, payload, and idempotency key. Their exact types and optionality remain to be decided.

- Authenticate the service and bind it to permitted projects and sources; do not trust the submitted project/source/user as authorization.
- Specify whether job/user identifiers are VanoHub or external IDs and how mappings are resolved.
- Normalize timestamp/duration semantics under D06; bound batch size and payload depth/size.
- Define the deduplication namespace and retention window. Retries of the same logical event must not increase credited counts twice.
- Define whether a duplicate returns the original outcome, and whether invalid batches fail atomically or return per-item results.
- Reject or quarantine unmapped/invalid events according to an explicit policy; do not convert failures into zero-duration records.
- State whether telemetry informs a metric, creates a suggestion, or changes business state. No implicit workflow advancement.

This checklist is a draft contract specification, not an implemented schema or a promise about current responses.

## 6. Verification and compatibility

For each changed surface, collect:

- Schema validation and representative request/response checks.
- Allowed and disallowed project/role examples, including cross-project object IDs.
- Boundary inputs, omitted/null fields, pagination/limits, and safe upstream failures.
- Retry/replay/concurrency cases when the operation can mutate or accept duplicate work.
- Frontend type, API-wrapper, form, and status-label parity.
- Migration/rollout order if an old consumer can remain active.

Use focused checks during edits and the current repository's required gates before completing the task. Store concise outcomes with revision/environment in [changes.md](../refactoring/changes.md). A generated schema alone does not verify authorization or workflow correctness.
