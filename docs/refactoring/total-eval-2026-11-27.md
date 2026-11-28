# Total Evaluation Archive (`feature/issue-logger` @ `0beace7`, reconciled at `feature/annotator-qclv1` @ `b37b0b2` + working tree `2026-11-28`)

- **Date:** `2026-11-27` (reconciled `2026-11-28`, Asia/Ho_Chi_Minh)
- **Audited baseline:** `feature/issue-logger @ 0beace78eebc8d2bfac3db06ca203f2e6ac35819` (`T03` + `T04/T06` findings), reconciled against `feature/annotator-qclv1 @ b37b0b2` and the verified working tree on `2026-11-28`.
- **T05 Live Browser Status:** `37/37` Headless Chrome CDP checks passed on `7ff163b` for migrated AntD screens, and `25/25` 4-role Headless Chrome CDP checks (`Chrome/158.0.8127.88 --headless=new` across `pm_demo`, `qc2_demo`, `qc1_demo`, `ann1_demo` on `seed_demo` org `#8`) passed on `2026-11-28` covering `ProjectSettingsPage` (render + save), `ActivityLogPage`, `ProjectListPage` (`is_pm` sync/create gating), `OverviewPage` (`TD13`/`DH07`), `DeliveryPage`, `JobsPage`/`JobDetailDrawer` Slideover, `Qc2DashboardPage` (`errors_by_severity`), `NotificationBell` (tabs + category filter), `AccountSettingsPage`, `RequireCap` blocks, `Qc1DashboardPage`/`Qc1WorkPage`, `Annotator*` views, and `404` isolation with `0` console/JS/unexpected HTTP errors; real CVAT-linked E2E (`NT02`) remains pending.
- **Purpose:** Safekeeping archive of security, concurrency, migration, and API/UI contract defects, separating verified open/deferred items from resolved items recorded in [plan.md](./plan.md), [changes.md](./changes.md), and [contracts.md](../api/contracts.md). See also [security-and-verification.md](../operations/security-and-verification.md).

---

## 1. Open P0 Blockers

All 9 code/runtime P0 blockers from `0beace7` are resolved in `b37b0b2` (with `backend/Pipfile.lock` drift and CI `--deploy` remaining open below under P2 CI).

---

## 2. Open / Deferred P1 Security, Concurrency, CVAT & Migration Gaps

1. **`D03` residual operational boundaries (`backend/cvat_integration/assignee.py`):**
   - `invite_to_org` remains externally irreversible on CVAT once dispatched.
   - Asynchronous `CvatAssigneeOutbox` failures reaching `DEAD` status are visible in Django Admin (`CvatAssigneeOutboxAdmin`) and `manage.py drain_cvat_outbox` CLI rather than via a dedicated frontend outbox-alert panel (`cvat-sync` continues returning synchronous `assignee_error` / `waiting_link`).
2. **`D05` counting, baseline & QC2 denominator gaps:**
   - Missing pre-label `S0` baseline snapshot at initial sync: pre-labeled objects on `PENDING_ANNOTATION` jobs still credit when `count_objects=True` runs.
   - `Job` does not persist `cvat_frame_step` / `cvat_deleted_frames` / `cvat_included_frames` columns yet; `ensure_qc2_sample` calls `pick_frames(locked_job, project.sampling_rate)` without passing live CVAT `meta` unless attached on `job` attributes.
   - `AuditSample.checked_object_count` stays `None` (`CL02`, `CL05`, `CL11` return `status="pending_definition"`, `value=None`).
   - Manual `object_count` input on `submit_annotation` remains accepted (bounded `0..PG_INT32_MAX`) for non-CVAT jobs (`cvat_job_id is None`).
3. **`D06` & `T08` telemetry/time gaps:**
   - `NS04` (`audit_speed`) and `DB02`/`DB03` (`estimated_completion`) remain `status="pending_definition"` / `value=None`.
   - `T08` CVAT-side v2 emitter, `manage.py ingest_cvat_events`, and `PV04` amendment in `docs/platform-spec.md` are not implemented yet.
4. **Non-empty production migration hazards (historical committed migrations):**
   - Already-committed migrations (`jobs/0009`–`0010`, `projects/0010`–`0011`, `quality/0004`–`0005`, `teams/0003`, `accounts/0004`) are immutable by policy. Pre-existing non-empty production databases still require pre-clean/backfill procedures (`last_counted_objects`, `first_qc1_result`, `total_rework_rounds`, `Batch.qc2_confirmed_at`, `AuditSample.created_at`, constraint pre-checks, and `ACCESS EXCLUSIVE` lock windows) before executing those historical migrations. (The 3 new working-tree migrations `accounts/0007`, `projects/0012`, `cvat_integration/0002` are purely additive.)

---

## 3. Open / Deferred P1 API Contract & Frontend Consumer Parity Gaps

1. **OpenAPI tooling (`T03`):** `drf-spectacular` and `docs/api/openapi.yaml` remain deferred post-Dec 4.
2. **Notification bell polling:** `frontend/src/layouts/NotificationBell.tsx` still polls every `60s` (no WebSocket/SSE push).
3. **Live CVAT E2E:** Real CVAT-linked E2E acceptance (`NT02` / `R01`–`R20`) remains pending.

---

## 4. Open P2 Cleanup & Hardening Backlog

- **CI & Tooling:** `backend/Pipfile.lock` omits `pydantic` from `[default]` and leaves `[develop]: []` (`pyright`, `ruff`) because local `pipenv lock` fails with `RuntimeError: Failed to lock Pipfile.lock!`; `.github/workflows/ci.yml` runs `manage.py check --deploy` now, while `pipenv install --dev --system` still omits `--deploy` until `Pipfile.lock` is regenerated cleanly. `pyproject.toml:14` still declares `target-version = "py312"` vs Python `3.14`, and `.github/workflows/ci.yml:76` uses Node `20` vs `@types/node ^24`.
- **Remaining unused routes/exports:** `GET /api/projects/{id}/permission-matrix/` (`getPermissionMatrix`), `PATCH /api/projects/{id}/datasets/{pk}/` (`updateDataset`), `POST /api/projects/{id}/jobs/bulk-move-batch/` (no UI), `rejectAuditSample` alias in `frontend/src/features/quality/api.ts`, `GET .../deliveries/{pk}/` (`405`, no retrieve), and unused `PUT` on ViewSets / `DefaultRouter` in `backend/projects/urls.py`.
- **Legacy/post-MVP schema & spec items:** `Project.sampling_method`/`stratify_by` and `Audit.method`/`seed`/`eligible_*` legacy columns; `Delivery.reopen` (`BG04`); `Project`/`Dataset` `deadline` (`TG01`); 12 unimplemented P1 spec metrics (`KPI05`, `KPI06`, `KPI11`, `NS07`, `NS08`, `CL12`, `RW03`, `RW05`, `RW06`, `TD04`, `TD12`, `DA03`) and remaining P2 metrics (`NS02`, `NS05`, `NS09`, `NS10`, `CL08`, `CL13`, `DB01`, `DB04`, `DA02`).

---

## 5. Resolved

### Historical commits (`f212a4f`, `7ff163b`, `36dae92`, `f4744c4`)

- `f212a4f`: Added `_validate_base_url()` and `CVAT_REQUIRE_HTTPS` in `backend/cvat_integration/client.py` (+3 tests) and added `npm test` (Vitest) to `.github/workflows/ci.yml`.
- `7ff163b`: Migrated all 13 remaining Ant Design 6 files to React Aria / Untitled UI, uninstalled `antd` and `@ant-design/icons`, and passed `37/37` Headless Chrome CDP checks on migrated screens.
- `36dae92`: Reconciled refactoring, contracts, security, UI, and product spec docs under `docs/`.
- `f4744c4`: Removed superset-only routes `GET /api/cvat/tasks/` (`P0 #2` cross-org leak), `GET /api/auth/users/`, and duplicate `POST /api/auth/change-password/`.

### Committed in `b37b0b2` (P0 #1, #3–#9 transport/redaction)

- **P0 #1 (`MemberCredentialView` / `MemberResetPasswordView`):** `_ensure_credential_target_manageable` blocks `is_superuser`/`is_staff`, `Role.PROJECT_MANAGER`, and multi-organization members unless actor is superuser; added `Cache-Control: no-store`.
- **P0 #3 (`POST /api/cvat/link/`):** Scoped link-time sync via `only_cvat_user_id` and switched `_filter_sync_result_for_user` to ID-based project filtering (`created_ids`/`updated_ids`/`organization_id`).
- **P0 #4 (`manage.py check --deploy` & prod settings):** Added env-driven `MAILERS`, `POSTGRES_SSLMODE`, HTTPS/HSTS/cookie flags, `DEBUG`-gated `SessionAuthentication`/`BrowsableAPIRenderer`/`CORS_ALLOWED_ORIGINS`, and DRF anon/user throttling in `backend/config/settings.py` + `backend/.env.example`.
- **P0 #5 (AB-BA deadlocks):** Added `lock_job_with_batch` (`Batch → Job`) for `qc1_pass`, sorted CVAT sync projects/tasks by ID, and ordered locked job/batch queries by `"id"`.
- **P0 #6 (Four-eyes `L13` gaps):** Added `QC1_PASSED` to `ASSIGN_LOCKED_STATUSES`, enforced `getJobLockReason` on `JobDetailDrawer`, added `audit_samples`/`review_errors` exclusions to `claim`, extended `get_stage_history` (`job.assign`/`job.import`, QC1 `after__event`, `DailyOutputRecord`), and attributed CVAT QC1 completions + `job.import` logs.
- **P0 #7 (QC2 frame-jump URL):** Added `cvatFrameUrl` in `frontend/src/shared/utils/cvat.ts` and updated `ReviewPanel.tsx`.
- **P0 #8 (`rework_round - 1` drift):** Unified active-round resolution to `max(total_rework_rounds, rework_round) - 1` across backend (`jobs/views.py`, `jobs/serializers.py`, `quality/qc2.py`, `cvat_integration/sync.py`) and frontend `activeErrorRound` / `splitActiveErrors`.
- **P0 #9 (`CvatClient` transport/redaction & workspace hygiene):** Set `session.trust_env = False`, validated/stripped tokens, removed raw upstream exception/payload text from `CvatError`, and unstaged starter archive files.

### Resolved in working tree (`feature/annotator-qclv1` @ `b37b0b2`, reconciled `2026-11-28`)

- **Backend Core (RMW locks, `IntegrityError`, security, JWT revocation, P2 guards):**
  - Added `select_for_update()` locking on `DatasetViewSet.lock/unlock`, `BatchViewSet.{lock,unlock,perform_update}`, `DeliveryViewSet.perform_create` (`Dataset → Batch → Job` ordered by `id`), `ProjectSettingsView.patch`, `ProjectViewSet.{create,update,_sync_pms}`, `MemberResetPasswordView.post`, `ProjectMemberRolesView.post`, `ProjectMemberRoleDetailView.delete`, and `AnnotatorJobViewSet.claim` (locking `User` before reading roles/`team_ids`/WIP inside `transaction.atomic()`).
  - Handled concurrent `IntegrityError` cleanly as `400 ValidationError` across `ProjectMembersView.post`, `ProjectViewSet`, `TeamViewSet`, `ErrorCategoryViewSet`, `cvat/link`, `sync_organizations`, `sync_organization`, and `import_task_jobs`.
  - Added `CREDENTIAL_ENCRYPTION_KEYS` + `MultiFernet` decoupling (`backend/accounts/credentials.py`), `Cache-Control: no-store` on `ProjectMembersView.post`, `LOGGING` `SecretRedactionFilter`/`RedactingFormatter` (`backend/config/settings.py`), `parse_int_param` `PG_INT32_MAX` bounds in `ProjectScopedViewMixin` (returning `404` on out-of-range IDs), and `User.token_version` (`accounts/0007_user_token_version.py`, `tv` claim, `VanoHubJWTAuthentication`, revoking JWTs with `401` on password change, PM reset-password, role removal, and PM removal).
  - Fixed `AuditSampleViewSet.assign` & `resolve_escalation` status guards, superuser `PROJECT_MANAGER` visibility/capability parity across `/api/projects/`, `/api/auth/me/`, and `ProjectScopedViewMixin`, `DeliverySerializer` read-only `batch` on update (`PUT /deliveries/{pk}/`) + `deadline`/`is_on_time` + enriched `/deliveries/candidates/` (retaining `open_audits` compat), and batch-level `review_needed` notification unpinning (`UserNotification.batch` via `projects/0012_usernotification_batch.py`).
- **Backend CVAT / QC2 (`D03` outbox, `D05` freeze & bounds, DoS/OOM limits):**
  - Added durable `CvatAssigneeOutbox` (`cvat_integration/0002_cvatassigneeoutbox.py`) + `drain_cvat_outbox` CLI (`--limit`, `--force`, `--max-attempts`) with PostgreSQL advisory lock, stale `PROCESSING` reclamation, exponential backoff, stale-write protection (`_persist_push_success`), per-job `push_assignees` error isolation, `current_holder()` returning `None` on `QC1_PASSED`/`APPROVED`/`DELIVERED`, and `ActivityLog` entries (`cvat.assignee_push`, `cvat.org_invite` with `actor=None`).
  - Added `sync_organization` PostgreSQL advisory lock + `CVAT_SYNC_COOLDOWN_SECONDS` (default `10s`; `sync_cvat` passes `0`), froze `object_count`/`DailyOutputRecord` outside `SYNCABLE_STATUSES`, blocked writes on locked/delivered batches/datasets/jobs, and cascaded `Batch.source_missing=True` to unlocked/non-delivered child jobs.
  - Hardened `CvatClient` (`allow_missing_meta=False` default on `data/meta` 404, `close()`/context manager, `CVAT_HOST_HEADER` CRLF/SNI validation, `CVAT_MAX_REQUEST_DURATION`, streaming `CVAT_MAX_RESPONSE_BYTES`), fixed `resolve_stop_frame` precedence and `count_object_frames` frame-constraint guard, expanded `pick_frames` for `frame_step`/`deleted_frames`/`included_frames`/`stop_frame`/`meta`, and made `submit_annotation` ignore client `object_count` when `cvat_job_id is not None` while bounding `0..PG_INT32_MAX`.
- **Backend Analytics (`ProjectOverviewView`, `AnnotatorAnalyticsView`, `Qc1SummaryView`, `Qc2SummaryView`):**
  - Added `locked_jobs == 0` to `pending_decisions.batches_ready_for_qc2_confirm`, serialized `thresholds` as `"0.00"` strings (`_format_decimal`), and added `counts.overdue_batches` + `metrics.delivery_on_time_rate` (`DH07`).
  - Fixed `AnnotatorAnalyticsView` to return `null` (not `0`) when hours `== 0` and exposed `hours_provenance`, `measured_objects`, `submitted_objects`, `unsubmitted_cvat_objects`, and `hours_status`.
  - Aligned `Qc1SummaryView` `scope="project"` `assigned`/`pending` filters with `scope="mine"`, and added `stats.audited_today` to `Qc2SummaryView`.
- **Frontend Parity (`Shell/Auth/Projects` + `Jobs/Quality/Analytics/Teams`):**
  - Added `/settings` (`ProjectSettingsPage.tsx`, all 9 fields) and `/activity` (`ActivityLogPage.tsx`) routes, sidebar items, and `QuickSearchModal` entries; gated `ProjectListPage.tsx` sync/create via `user.is_pm` and added internal Org create/edit (`pm_ids`).
  - Added `OverviewPage.tsx` `"Việc cần quyết định (TD13)"`, `"Phân bố lỗi QC (CL04)"`, `overdue_batches`, and `DH07`; updated `DeliveryPage.tsx` with `DH07`, `deadline`/`DueStateBadge`, `pending_qc2_samples`, `in_progress_audits`, and full `FeedbackDialog` (`recipient`, `output_path`).
  - Updated `CvatSyncButton.tsx` (`countObjects` toggle), `DatasetsPage.tsx`/`BatchesPage.tsx` (`?org=` links, CVAT status guard, `last_sync_error`), `NotificationBell.tsx` (`all_count`/`unread_count`, `sortUnifiedNotifications`, `due-*` guard), `AccountSettingsPage.tsx` (multi-org roles via `CurrentUser.projects`), and removed dead `teamLeaderName`/`team_leader_name`.
  - Replaced `"Pass → QC2"` copy with `"Đạt QC1"` (`Qc1DashboardPage.tsx`), added `WARN_ONLY` + `ReviewErrorChips` + `splitActiveErrors` to `Qc1ReviewPanel.tsx`/`Qc1WorkPage.tsx`/`AnnotatorJobDrawer.tsx`, split `?overdue=1` vs `?due_soon=1` (`AnnotatorDashboardPage.tsx`, `AnnotatorJobsPage.tsx`), guarded Lock/Assign/DataIssue/CVAT `object_count` inputs (`JobDetailDrawer.tsx`, `AnnotatorJobDetailPage.tsx`), switched `AnnotatorReworkPage.tsx` to `?include_errors=1`, updated `AnnotatorAnalyticsPage.tsx` (`previous_rank == null`, D06 provisional copy, `measured_objects ÷ total_hours`, `buildContiguousRateRuns`), and synchronized TypeScript interfaces across `auth`, `projects`, `jobs`, `quality`, and `teams`.
- **Follow-up hardening & live QA (`2026-11-28`):**
  - Added `select_for_update(of=("self",))` + `Role.QC2` re-check in `pick_auditor` (`backend/quality/qc2.py`, preserving `Batch -> Job -> User` lock order) and eliminated cross-project `PrimaryKeyRelatedField` ID existence oracles across `CreateMemberSerializer.team`, `BatchSerializer.team`, `DeliverySerializer.batch`, `AnnouncementSerializer.target_team` (`backend/projects/serializers.py`), `TransferSerializer.to_team` (`backend/teams/serializers.py`), and `_ProjectErrorCategoryField` (`backend/quality/serializers.py`), verified by 4 new regression tests (`248/248` PostgreSQL tests OK).
  - Added category filter pills to `NotificationBell.tsx`, `cvat_synced_at` (`CS08`) display to `OverviewPage.tsx`, `errors_by_severity` card to `Qc2DashboardPage.tsx`, and `manage.py check --deploy` to `.github/workflows/ci.yml`; verified **25/25** live 4-role Headless Chrome CDP checks (`0` console/JS/unexpected HTTP errors).
