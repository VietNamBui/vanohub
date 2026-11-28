# VanoHub Backlog

> Consolidated backlog on `feature/auth-new`, verified against current codebase and docs.
> Related checklists: [MVP Checklist](./mvp-checklist.md), [Platform Spec Backlog](./platform-spec.md#backlog--kiến-trúc-plugin-stub-trên-nền-cvat-base-gốc), [Refactor Plan](./refactoring/plan.md#explicitly-deferred-post-dec-4), [Total Eval](./refactoring/total-eval-2026-11-27.md).

---

## 1. Authentication & Identity

### `BL-AUTH-01` — Delegated CVAT Auth (`AUTH_MODE=cvat`) inside Django + `sync_cvat`
- **Status:** Design locked ([`docs/auth-new/README.md`](./auth-new/README.md)); unimplemented.
- **Server ownership:** Implement inside VanoHub's Django backend ([`backend/accounts/`](../backend/accounts/) + [`backend/cvat_integration/`](../backend/cvat_integration/)) and existing [`sync_cvat`](../backend/cvat_integration/management/commands/sync_cvat.py) cron — **no standalone custom auth microservice**.
- **Remaining implementation:**
  - `AUTH_MODE` (`"local"` | `"cvat"`) in [`settings.py`](../backend/config/settings.py) & [`.env.example`](../backend/.env.example), `GET /api/auth/config/`, `10/min` login throttle, and `--deploy` guard requiring `CVAT_REQUIRE_HTTPS=True` in `cvat` mode.
  - Dedicated `CvatIdentityClient` (`POST /api/auth/login` -> `GET /api/users/self` -> `POST /api/auth/logout`), keeping service [`CvatClient`](../backend/cvat_integration/client.py) strictly separate.
  - Strictly disable/hide password & PAT-link endpoints/UI in `cvat` mode (`ChangePasswordView`, `MemberCredentialView`, `MemberResetPasswordView`, `/api/cvat/link/`, `CvatLinkPage`, `MemberPasswordCell`, `SecurityTab`, editable `email`).
  - Keep `POST /api/auth/token/refresh/` local-only (`User.is_active` + `token_version`); sync user orgs at login; extend [`sync_organizations`](../backend/cvat_integration/sync.py) / `sync_cvat` to auto-provision active org members, revoke removed org `RoleAssignment`s, deactivate CVAT-disabled users, bump `token_version`, preserve historical rows, and alert PMs on held open jobs.
  - Adapt `ProjectMembersView.post` & `CreateMemberDialog` for exact CVAT username/email lookup + org invite; add `cutover_cvat_auth` CLI to link existing `User`s by `cvat_user_id` and scrub local passwords/`initial_password_encrypted`.

### `BL-AUTH-02` — True Browser SSO & Centralized MFA (Post-MVP)
- **Status:** Deferred post-MVP.
- **Gap:** `AUTH_MODE=cvat` leaves VanoHub (SPA JWT) and `CVAT_PUBLIC_URL` (CVAT session) as separate browser login sessions.
- **Target:** Deploy a standard OIDC/SAML Identity Provider (e.g., Keycloak or Authentik) in front of both CVAT and VanoHub instead of building a custom auth service.

---

## 2. Active Milestone & Pre-Release Blockers

### `BL-REL-01` — Gate 0 & `T08` Telemetry / Export Ingestion (`D04`, `PV04`)
- Amend `PV04` in [`docs/platform-spec.md`](./platform-spec.md) to authorize the slim in-process CVAT extension; sign off `D05`/`D06` MVP defaults.
- Provision dedicated read-only CVAT export service account (`user` global + `maintainer`/`owner` org + `read_only=True` PAT), persistent `/home/django/events` & `/vector-data-dir` with Vector buffer/ack, and `CVAT_EXPORT_CACHE_TTL=3600`.
- Extend [`CvatClient`](../backend/cvat_integration/client.py) with separate read-only export token config, org-header-free `create_events_export(?org_id=...)`, `get_request_status`, `CVAT_HOST_HEADER`-safe `stream_download(result_url)` (`allow_redirects=False`), and `target_frames` support on `count_job_objects`.
- Add PostgreSQL telemetry tables (`CvatSyncScope`, `CvatExportBatch`, `CvatEventLedger`, `CvatWorkingTimeEvent`, `CvatEventQuarantine`) and `manage.py ingest_cvat_events` (PII redaction, `org_id=null`/foreign-org quarantine, isolated from `ActivityLog` four-eyes & workflow transitions).
- Strip conflicting 5-tier workflow/OPA/client-gate hooks (`EV-02`) from `cvat-di-ext` and emit 3D-first `payload.cvat_ext` v2 events via `record_server_event(..., on_commit=True)`.

### `BL-REL-02` — Unblock `pending_definition` Metrics & QC2 Sampling Edge Cases (`D05`, `D06`)
- Compute and persist `AuditSample.checked_object_count` in [`backend/quality/views.py`](../backend/quality/views.py) / [`qc2.py`](../backend/quality/qc2.py) to unblock `CL02`, `CL05`, and `CL11` on `ProjectOverviewView` and `Qc2SummaryView` (currently `value=None`, `status="pending_definition"`).
- Wire `NS04` (`audit_speed` via `send:working_time`) and `DB02`–`DB03` (`estimated_completion`) in [`backend/analytics/views.py`](../backend/analytics/views.py).
- Persist CVAT frame metadata (`frame_step`, `deleted_frames`, `included_frames`, `stop_frame`) on `Job` (or pass live `meta` into `ensure_qc2_sample` in [`qc2.py`](../backend/quality/qc2.py)), and fix `pick_frames` returning `[start]` instead of `[]` when `job.frame_count == 0` and `included_list is None`.
- Lock `User` via `select_for_update()` in `pick_auditor` ([`qc2.py`](../backend/quality/qc2.py)) against concurrent role removal and load skew.

### `BL-REL-03` — Release Ops, Dependencies & Live QA (`T06`, `T07`, `NT02`)
- Refresh [`backend/Pipfile.lock`](../backend/Pipfile.lock) (currently missing `pydantic` in `[default]` and empty `[develop]: {}`) and switch [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) to `pipenv install --dev --system --deploy` + `manage.py check --deploy`.
- Document `CVAT_MAX_RESPONSE_BYTES`, `CVAT_MAX_REQUEST_DURATION`, `CVAT_SYNC_COOLDOWN_SECONDS`, `CVAT_OUTBOX_ON_COMMIT_LIMIT`, `CVAT_OUTBOX_ON_COMMIT_TIMEOUT` in [`backend/.env.example`](../backend/.env.example).
- Configure production deploy settings (`DJANGO_DEBUG=False`, `CVAT_REQUIRE_HTTPS=True`, `CREDENTIAL_LEGACY_SECRET_KEY_FALLBACK=False`, `STATIC_ROOT`, `pg_dump`/WAL backup schedule, RPO/RTO & P95 SLAs).
- Run live multi-role browser checks across new/updated parity UI screens, live CVAT 4-role E2E (`NT02`), and acceptance matrix (`R01`–`R20`).

---

## 3. Backend Hardening, Concurrency & Validation

### `BL-SEC-01` — Auth & Serializer Input Bounds
- Add scoped brute-force rate limits (e.g. `10/minute`) on `POST /api/auth/token/` and `POST /api/auth/me/password/`.
- Fix missing bounds causing `500 DataError` on oversized PostgreSQL inputs:
  - `ProfileUpdateSerializer.full_name` (`max_length` against `User.first_name`/`last_name`),
  - `CreateMemberSerializer.email` (`max_length=254`),
  - `ProjectWriteSerializer.max_rework_rounds` and `ProjectSettingsSerializer.max_rework_rounds` (`max_value=32767`),
  - `PG_INT32_MAX` bounds on `PrimaryKeyRelatedField` inputs (`CreateMemberSerializer.team`, `MemberInputSerializer.user`, `TransferSerializer`, `_BaseErrorInputSerializer.category`).

### `BL-SEC-02` — Tenant Isolation & Cross-Project Probing Oracles
- Scope `_BaseErrorInputSerializer.category` ([`backend/quality/serializers.py`](../backend/quality/serializers.py)) to the current project instead of querying `ErrorCategory.objects.filter(is_active=True)` globally before `validate_category`.
- Harden `ProjectWriteSerializer.validate_pm_ids` / `ProjectViewSet._sync_pms` (lock `User`s, stop enumerating missing platform IDs, restrict attaching arbitrary users across organizations) and `MemberInputSerializer.user` ([`backend/teams/serializers.py`](../backend/teams/serializers.py)) probing unroled platform users.

### `BL-SEC-03` — Locking, State Integrity & Validation Gaps
- **`BatchViewSet.perform_update` ([`backend/projects/views.py`](../backend/projects/views.py)):** Enforce `DataStatus.ACTIVE` on `Batch` and `Dataset` so `LOCKED`/`DELIVERED` batches cannot have `team`/`deadline` mutated (which retroactively alters dynamic `Delivery.is_on_time`).
- **`DatasetViewSet.update`:** Add `select_for_update()`, `DataStatus.ACTIVE` guard, and `ActivityLog.record()`.
- **Parent/child locking:** Align `lock_job`, `BatchViewSet.lock`, `DatasetViewSet.lock`, and `JobViewSet.bulk_move_batch` (lock source/target `Batch`/`Dataset`, re-align moved deadlines, guard historical `AuditSample`s).
- **`assign_job` / `resolve_escalation` ([`backend/jobs/views.py`](../backend/jobs/views.py)):** Disallow `annotator=None` while status remains `ANNOTATING` or `REWORK` (unclaimable state).
- **`DeliveryViewSet.perform_create`:** Include `updated_at` on bulk `Job.status=DELIVERED` updates and handle/block open `AnnotatorRequest`s; validate `frame_number in sample.frames` (and require `frame_number` for `is_missing_object=True`) in `AuditSampleViewSet.reject`.
- **Single-team invariant:** Decide and enforce at DB level whether a user can belong to only one `Team` per `Project` ([`backend/teams/models.py`](../backend/teams/models.py)).

### `BL-SEC-04` — Pagination, Notification Ordering & CVAT Payload Parsing
- Add `pagination_class` to currently unbounded list views (`ProjectViewSet`, `ProjectMembersView.get`, `DatasetViewSet`, `BatchViewSet`, `DeliveryViewSet`, `AnnouncementViewSet`, `GuidelineViewSet`, `TeamViewSet`, `AnnotatorRequestViewSet`, `ErrorCategoryViewSet`, `AuditViewSet`, `AuditSampleViewSet`) and avoid materializing all announcements in `_visible_announcements`.
- Fix `ProjectNotificationsView.get` slicing `UserNotification[:40]` before sorting `is_pinned_pending=True` (can drop older pinned notifications).
- Validate remaining [`CvatClient`](../backend/cvat_integration/client.py) responses with Pydantic (`list_organizations`, `list_memberships`, `get_user`, `list_*_projects`, `list_project_tasks`, `list_project_labels`, `get_self`) and parse tasks in `sync_organization` via `_parse_task`.

---

## 4. Deferred Product, KPI & CVAT Features

### `BL-FEAT-01` — Workflow & Lifecycle Extensions
- `Delivery.reopen` (`BG04` / `L14`) for client-rejected deliveries, plus Dataset-level delivery readiness (`BG01`).
- `Project` & `Dataset` `deadline` (`TG01` / `DA03`), SLA pause tracking during pending `data_issue`/`error_dispute` (`TG05`), and enforcing `CL12` quality gates (`quality_cl_threshold` / `defect_rate_threshold`) on `confirm-qc2` / `Delivery`.
- Pre-label baseline `S0` (`baseline_frame_counts`, `baseline_track_ids`, `count_sync_pending` on `submit`, locking manual `object_count` on non-CVAT jobs — `D05`).
- `Guideline.annotation_policies` (`do_not_delete`, `outside_only`, `add_only`, `suspect_untouched`) & `Job.guideline_version` snapshot (`DL07`).
- In-app/PM member deactivation & offboarding (`PQ03`, complement to `BL-AUTH-01` CVAT sync), internal Dataset/Batch/Job create & archive (`DataStatus.ARCHIVED`), `KpiTargetHistory(effective_from)` (`CS04`), `Project.workday_cutoff_hour` + multi-timezone (`User.timezone_name`), 12-month `ActivityLog`/`UserNotification` retention (`PQ05`), free-form job comments (`TB04`), and 2-way reassignment confirmation (`GV04`).

### `BL-FEAT-02` — Missing Analytics, KPIs & Evaluation Axes
- **12 missing P1 metrics:** `KPI05`, `KPI06`, `KPI11`, `NS07`, `NS08`, `CL12`, `RW03`, `RW05`, `RW06`, `TD04`, `TD12`, `DA03`.
- **6 missing P2 metrics:** `NS02`, `NS05`, `CL08`, `CL13`, `DB01`, `DA02` (plus `NS04`, `DB02`–`DB04`, `NS09`, `NS10`).
- **2-axis `AND` evaluation (`SL × CL` matrix + 3-tier thresholds + `Edge %`)** and missing role/scope breakdowns (`SL02` initial vs re-check, `DH06` on `QC2`, `CS08` `last_cvat_sync_at` on `ProjectOverviewView`, `Qc1SummaryView` `NS04`, `TeamRankingView`/`MemberPerformanceView` period filters & `KPI08`/`KPI09`/`NS06`).

### `BL-FEAT-03` — Post-Dec 4 CVAT Telemetry, Outbox Alerting & Plugin Stubs (`B1`–`B5`)
- 2D CVAT extension parity (`R03`/`R14` 2D), CVAT-side `QcEventOutbox` feed (`R21`), `JobAnnotationRevision` split/merge lineage (`ID-01`, `R15`), external Pre-QC worker (`R07`).
- Plugin `Protocol` hooks (`B1`), `JobTelemetryEvent` (`B2`), Auto-QC `ReviewError` fields & `POST .../plugin-findings/` (`B3`), `POST .../telemetry/` (`B4`), and CVAT HMAC webhook ingest (`B5`).
- PM alert / status surface for `CvatAssigneeOutbox.Status.DEAD` failures (`D03`).

---

## 5. Frontend Parity, UX & Testing

### `BL-FE-01` — Unwired APIs & Page/Control Gaps
- Wire orphaned APIs/endpoints: [`getPermissionMatrix`](../frontend/src/features/projects/api.ts), `updateDataset` (`Dataset.description` in [`DatasetsPage.tsx`](../frontend/src/features/projects/pages/DatasetsPage.tsx)), and `POST .../jobs/bulk-move-batch/` in [`JobsPage.tsx`](../frontend/src/features/jobs/pages/JobsPage.tsx).
- [`OverviewPage.tsx`](../frontend/src/features/projects/pages/OverviewPage.tsx): render `project.cvat_synced_at`, `stage_progress`, `defect_rate_by_severity`, and fix `major` severity label (`"Trung bình"` -> `"Nặng"`).
- [`Qc2DashboardPage.tsx`](../frontend/src/features/quality/qc2/Qc2DashboardPage.tsx): render `errors_by_severity`, `kpi_summary`, `kpi_target`, `overdue`/`due_soon`/`assigned`, and `pct_change`.
- [`AuditWorkPage.tsx`](../frontend/src/features/quality/qc2/AuditWorkPage.tsx): add deadline column, `overdue`/`due_soon` & URL filters, and pagination.
- Filter/table parity: `?locked=1` & advanced filters on `JobsPage.tsx`, `status` filter on `BatchesPage.tsx`, Untitled UI `<Table>` on `DatasetsPage.tsx`, search/pagination on `DeliveryPage.tsx`, category filter / load-more / push on `NotificationBell.tsx`, `?job=` on QC1 links & QC2 search in `QuickSearchModal.tsx`, client-side file size/MIME check on `AccountSettingsPage.tsx` avatar upload.

### `BL-FE-02` — Automated Testing & API Schema Tooling (`T03`)
- Install `@testing-library/react` + DOM environment (`jsdom`/`happy-dom`) and add interactive component tests (`auth`, `client.ts` 401 interceptor, `RequireCap`, modals/drawers/tables) plus Playwright/Cypress multi-role E2E tests.
- **`T03` OpenAPI:** Install `drf-spectacular` and generate `docs/api/openapi.yaml`.

---

## 6. Cleanup, Tooling & Doc Reconciliation

### `BL-CLEAN-01` — Legacy Code, Schema & Tooling Drift
- Retire legacy unused sampling columns (`Project.sampling_method`/`stratify_by`, `Audit.{method,stratify_by,seed,eligible_*}`, `AuditSample.stratum`) once safe.
- Remove dead code/exports: `_my_roles` ([`projects/serializers.py`](../backend/projects/serializers.py)), unused `me`/`change_password` aliases ([`accounts/views.py`](../backend/accounts/views.py)), unused `rejectAuditSample` ([`frontend/src/features/quality/api.ts`](../frontend/src/features/quality/api.ts)), unused constants in [`frontend/src/features/quality/constants.ts`](../frontend/src/features/quality/constants.ts), legacy `JOB_STATUS_COLORS`, unused `.gitkeep` files, and `DefaultRouter` vs `SimpleRouter` in [`backend/projects/urls.py`](../backend/projects/urls.py).
- Align `pyproject.toml` (`target-version = "py312"` -> `py314`) and `.github/workflows/ci.yml` (`node-version: "20"` -> `24`), and maintain non-empty prod DB runbooks for historical `AddConstraint`/`RunPython` migrations.

### `BL-CLEAN-02` — Stale Documentation Sync
- Reconcile [`docs/platform-spec.md`](./platform-spec.md) (`DH07` batch-level implemented, `confirm-qc2` notification unpinning, CVAT-linked `submit` manual `object_count` ignored, `DH06` QC1 coverage, `PV04` vs `D04`), [`docs/refactoring/plan.md`](./refactoring/plan.md) & [`decisions.md`](./refactoring/decisions.md) (`D03` outbox, `pick_frames`, `T05` completion, `b37b0b2` test counts), and [`docs/ui-spec-traceability.md`](./ui-spec-traceability.md) (`DH07`, `TD13`, `CL04`).
