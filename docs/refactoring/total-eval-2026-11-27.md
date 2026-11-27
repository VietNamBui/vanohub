# Total Evaluation Archive (`feature/issue-logger` @ `0beace7`, reconciled at `7ff163b`)

- **Date:** `2026-11-27` (Asia/Ho_Chi_Minh)
- **Audited baseline:** `feature/issue-logger @ 0beace78eebc8d2bfac3db06ca203f2e6ac35819` (`T03` + `T04/T06` findings, reconciled against `7ff163b` on `2026-11-27 15:00 +07:00`).
- **T05 Live Browser Status:** Not run in the original `0beace7` eval (`DevToolsActivePort` ENOENT); later covered partially in the `7ff163b` AntD migration (`37/37` Headless Chrome CDP checks for migrated AntD screens), while non-AntD parity checks remain open.
- **Purpose:** Safekeeping archive of verified security, concurrency, migration, and API/UI contract defects not yet recorded in [plan.md](./plan.md), [changes.md](./changes.md), or [contracts.md](../api/contracts.md). See also [security-and-verification.md](../operations/security-and-verification.md).

---

## 1. Open P0 Blockers (Verified Present at `7ff163b`)

1. **Cross-org account takeover & superuser password reset** — `backend/projects/views.py:407-436`
   - `MemberResetPasswordView.post` (`backend/projects/views.py:427-436`) only blocks targets with `Role.PROJECT_MANAGER`, leaving `is_superuser` / `is_staff` and members belonging to other organizations unprotected. A PM of Org A can reset the global password of a superuser holding any non-PM role in Org A (full platform takeover) or hijack credentials of a multi-org member to enter Org B.
   - `MemberCredentialView.get` (`backend/projects/views.py:412-419`) does not block reading plaintext `initial_password_encrypted` of PMs, superusers, or users created in other organizations.

2. **Cross-org tenant leak & D01 `project_id` ambiguity on `GET /api/cvat/tasks/`** — `backend/cvat_integration/views.py:51-81`, `backend/cvat_integration/client.py:177-184`
   - Checks only `user.is_pm()` and invokes global system-admin `CvatClient(timeout=10).list_tasks(project_id=project_id, search=search)` without `X-Organization`. Any single-org PM can omit `project_id` or pass a foreign CVAT project ID to enumerate tasks across all CVAT organizations and personal workspaces.
   - `project_id` forwards raw CVAT Project ID (`Dataset.cvat_project_id`), violating D01. Route has 0 frontend callers (`Orphan Backend`).

3. **Cross-org global sync mutation & name-collision tenant leak on `POST /api/cvat/link/`** — `backend/cvat_integration/views.py:165-182`, `backend/cvat_integration/sync.py:377-458`
   - Any authenticated user (including an Annotator) calling `POST /api/cvat/link/` runs `sync_organizations_quietly(user)` using global admin CVAT credentials across every CVAT organization, creating foreign `Project` rows, granting `PM`/`Annotator` roles with `granted_by=actor`, and invoking `sync_organization(..., client=client)` (`backend/cvat_integration/sync.py:451`) without `X-Organization`.
   - `_filter_sync_result_for_user` (`backend/cvat_integration/views.py:169-182`) filters by non-unique `Project.name` instead of `project_id` / `cvat_org_id`, leaking cross-org data when two organizations share a name.

4. **Production deploy check failure (`mail.E001`) + missing production hardening** — `backend/config/settings.py:29-41, 154-209`
   - Hardcoded `django.core.mail.backends.console.EmailBackend` fails `manage.py check --deploy` with ERROR `mail.E001`.
   - Missing `SECURE_PROXY_SSL_HEADER`, `SECURE_SSL_REDIRECT` (`W008`), `SECURE_HSTS_SECONDS` (`W004`), `SESSION_COOKIE_SECURE` (`W012`), `CSRF_COOKIE_SECURE` (`W016`), `CSRF_TRUSTED_ORIGINS`, and PostgreSQL TLS `OPTIONS` (`sslmode`).
   - `CORS_ALLOWED_ORIGINS` defaults to `http://localhost:5173,http://127.0.0.1:5173` even when `DEBUG=False`. `REST_FRAMEWORK` omits `DEFAULT_RENDERER_CLASSES` (leaving `BrowsableAPIRenderer` + `SessionAuthentication` active in prod) and `DEFAULT_THROTTLE_CLASSES` / `DEFAULT_THROTTLE_RATES`.

5. **PostgreSQL AB-BA deadlocks (workflow vs CVAT sync)**
   - **`Job -> Batch` vs `Batch -> Job` inversion:** `qc1_pass` (`backend/quality/views.py:456, 500`) locks `Job` via `lock_job()` then calls `ensure_qc2_sample(job)` (`backend/quality/qc2.py:125-127`), which locks `Batch`. Meanwhile `confirm_qc2` (`backend/projects/views.py:645, 657`), `DeliveryViewSet.perform_create` (`backend/projects/views.py:785, 793`), `bulk_move_batch` (`backend/jobs/views.py:593, 604`), `sync_organization` (`backend/cvat_integration/sync.py:610, 661`), `import_task_jobs` (`backend/cvat_integration/sync.py:766, 779`), and `sync_batch` (`backend/cvat_integration/sync.py:880, 888`) lock `Batch -> Job`.
   - **Unordered multi-row locks:** `sync_organization` (`backend/cvat_integration/sync.py:610, 649, 661, 690, 704`), `import_task_jobs` (`backend/cvat_integration/sync.py:779`), and `sync_batch` (`backend/cvat_integration/sync.py:888`, inherits `Job.Meta.ordering = ["deadline", "id"]` at `backend/jobs/models.py:136`) lack `.order_by("id")`, deadlocking against bulk endpoints and concurrent sync runs.

6. **Four-eyes (`L13`) bypasses**
   - `_apply_cvat_state` (`backend/cvat_integration/sync.py:266-318`) never sets `job.qc1_reviewer` from CVAT validation assignee and writes `actor=None` (`backend/cvat_integration/sync.py:287`); `_new_job` (`backend/cvat_integration/sync.py:333-371`) writes no `ActivityLog` — a QC1+QC2 user reviewing on CVAT bypasses `four_eyes_conflicts` and can be auto-picked by `pick_auditor`.
   - `get_stage_history` (`backend/quality/qc2.py:31-76`) omits `DailyOutputRecord` and `job.assign` history — reassigning `job.annotator` erases the prior annotator from four-eyes history.
   - `ASSIGN_LOCKED_STATUSES` (`backend/jobs/views.py:58, 326`) omits `QC1_PASSED` — PM can overwrite or clear `annotator` / `qc1_reviewer` after QC1 pass.
   - `AnnotatorJobViewSet.claim` (`backend/jobs/views.py:796-800`) omits QC2 (`AuditSample`) and `ReviewError(QC1)` history when checking exclusions.

7. **Broken QC2 CVAT frame-jump URL (double `?`)** — `backend/jobs/models.py:227-234`, `frontend/src/features/quality/qc2/ReviewPanel.tsx:415`
   - `Job.cvat_url()` appends `?org=${slug}` when `project.cvat_org_slug` is set, while `FramesToCheck` in `ReviewPanel.tsx` unconditionally formats `href={`${url}?frame=${frame}`}`, producing malformed `.../tasks/{tid}/jobs/{jid}?org={slug}?frame={n}` on all CVAT-synced orgs.

8. **Post-escalation active rework errors vanish & partial-rework mis-credit (`rework_round - 1` drift)**
   - `resolve_escalation` (`backend/jobs/views.py:529-533`) resets `job.rework_round = 0` while preserving `job.total_rework_rounds`; `ReviewError.rework_round` stores `max(total_rework_rounds, rework_round)` (`backend/quality/views.py:242, 543`).
   - After escalation reset + next reject, `rework_round - 1` diverges in: `backend/jobs/views.py:89` (`_active_rework_error_count`), `backend/jobs/serializers.py:103` (`JobSerializer.get_open_error_count`), `backend/jobs/views.py:252-256` (`submit_annotation` partial-rework credit), `backend/quality/qc2.py:117, 153` (`pick_frames` RNG seed & `AuditSample.rework_round`), `backend/cvat_integration/sync.py:176, 180`, and frontend `frontend/src/features/jobs/pages/AnnotatorJobDetailPage.tsx:155`, `frontend/src/features/jobs/pages/AnnotatorReworkPage.tsx:50`, `frontend/src/features/jobs/pages/AnnotatorDashboardPage.tsx:324`.

9. **`backend/Pipfile.lock` drift + residual `CvatClient` transport/redaction issues**
   - `backend/Pipfile.lock` omits `pydantic` from `[default]`, leaves `[develop]: []` (missing `pyright`, `ruff`), and has a stale `_meta.hash`; `.github/workflows/ci.yml:46` omits `--deploy`.
   - `CvatClient` (`backend/cvat_integration/client.py:54-88`, `backend/cvat_integration/sync.py:114-122`) retains `requests.Session().trust_env=True` (`HTTP_PROXY` / `~/.netrc`), does not strip/validate `CVAT_ACCESS_TOKEN` (whitespace/CRLF triggers `InvalidHeader` embedding literal `Bearer <token>` into `CvatError`), and embeds raw upstream JSON from `PydanticValidationError` into `CvatError`, returned verbatim in API responses (`backend/cvat_integration/views.py:105, 146, 199`, `backend/projects/views.py:512, 539`) and `Batch.last_sync_error`.

---

## 2. Open P1 Security, Concurrency, CVAT & Migration Gaps (`T04/T06`)

1. **Unlocked RMW races & unhandled `IntegrityError` (HTTP 500):**
   - `DatasetViewSet.lock/unlock` and `BatchViewSet.lock/unlock` (`backend/projects/views.py:452-468, 514-526, 620-632`) lack `transaction.atomic()` + `select_for_update()`, allowing concurrent lock/unlock to downgrade `DELIVERED` -> `LOCKED` -> `ACTIVE`. `DeliveryViewSet.perform_create` does not lock `Dataset` (`backend/projects/views.py:791`).
   - Unlocked mutations: `BatchViewSet.perform_update`, `ProjectSettingsView.patch`, `ProjectViewSet._sync_pms`, `MemberResetPasswordView.post`. Role-removal vs assignment race between `ProjectMemberRoleDetailView.delete` and `assign_job` / `pick_auditor`.
   - Uncaught `IntegrityError` on concurrent requests: `cvat/link`, `sync_organizations`, `sync_organization`, `import_task_jobs`, `ProjectMembersView.post`, `TeamViewSet`, `ErrorCategoryViewSet`.

2. **`D03` outbound assignee push (`backend/cvat_integration/assignee.py:85-175`):**
   - Runs synchronously in `transaction.on_commit()` inside WSGI/HTTP request threads (blocking `bulk_assign` / `confirm_qc2`), swallows `CvatError` returning HTTP `200`, aborts remaining jobs on first error (partial CVAT mutation), saves `job.save(update_fields=["cvat_assignee_id"])` unlocked, writes no `ActivityLog` for `set_job_assignee` / `invite_to_org`, auto-invites irreversibly via admin token, and is a no-op on `QC1_PASSED` / `AuditSample.pass_` (`_NOT_MANAGED`), leaving prior reviewers assigned on CVAT.

3. **`D05` counting, output inflation & frozen-state leakage:**
   - Client-supplied `object_count` up to `PG_INT32_MAX` trusted in `submit_annotation` (`backend/jobs/views.py:237-277`), even on CVAT-linked jobs.
   - `_apply_object_count` (`backend/cvat_integration/sync.py:216-241`) checks `or job.submitted_at is not None`, mutating `job.object_count` on `QC1_PASSED` / `PENDING_QC2` / `APPROVED` jobs and crediting post-QC edits to the annotator's `DailyOutputRecord`.
   - Missing S0 baseline: pre-labeled objects are credited 100% to the annotator on initial sync while `PENDING_ANNOTATION`.
   - Counting edge cases: `CvatJobMetaPayload.resolved_stop_frame` (`backend/cvat_integration/schemas.py:138-146`) falls back to task `size` before caller `cvat_job.stop_frame`; `count_job_objects` ignores `data/meta` 404; shape/track missing `frame`/`shapes` unconditionally adds `+1`.
   - `Batch.source_missing=True` does not cascade to child `Job`s; `sync_organization` overwrites `Batch.name`/`dataset` and creates new jobs inside `LOCKED`/`DELIVERED` batches; `_apply_cvat_state` overwrites metadata on `LOCKED`/`DELIVERED` jobs.

4. **Synchronous DoS & OOM risk:** `CvatClient` (`backend/cvat_integration/client.py:22-123`) permits `MAX_PAGES = 1000 x 15s` with no total request deadline, no per-project sync lock/cooldown, unbounded `jobs/{id}/annotations` `response.json()` memory allocation, and unclosed `requests.Session()` objects.

5. **Non-empty production migration hazards:**
   - Missing `RunPython` pre-clean before `CheckConstraint`/`UniqueConstraint` in `backend/jobs/migrations/0010_*`, `backend/projects/migrations/0011_*`, `backend/quality/migrations/0005_*` (plus earlier `jobs/0009`, `projects/0010`, `quality/0004`, `teams/0003`) — fails on legacy `0`, out-of-range, or duplicate production rows.
   - Missing data backfills: `last_counted_objects=0` double-credits existing `object_count > 0`, `first_qc1_result=""` drops historical FPY, `total_rework_rounds=0` omitted, `Batch.qc2_confirmed_at=NULL` traps post-QC2 rework at `QC1_PASSED`, `AuditSample.created_at=timezone.now()` skews `CL06`/`CL07` windows and `bisect_right` reviewer attribution.
   - `AddConstraint` holds `ACCESS EXCLUSIVE` locks; reverting `jobs/0010` drops `DailyOutputRecord`; `accounts/0004` uses `RunPython.noop` reverse; remote CVAT assignments/invitations are irreversible.

6. **Credential key coupling & missing JWT revocation:**
   - `backend/accounts/credentials.py:25-27` derives the Fernet key directly from `SECRET_KEY` (no dedicated key / `MultiFernet`).
   - No refresh-token blacklist (`token_blacklist` not configured) on password change/reset or role revocation; plaintext password responses (`backend/projects/views.py:290-299, 419, 436`) omit `Cache-Control: no-store`.

---

## 3. Open P1 API Contract & Frontend Consumer Parity Gaps (`T03`)

1. **Hybrid A2 & copy drift:** `ProjectOverviewView` (`backend/analytics/views.py:389-397`) computes `pending_decisions.batches_ready_for_qc2_confirm` without `and b.locked_jobs == 0` (disagreeing with `BatchSerializer` & `confirm_qc2`). `OverviewPage.tsx` never renders `pending_decisions`. Stale pre-A2 labels remain in `frontend/src/features/quality/pages/Qc1WorkPage.tsx:71` (`"Pass sang QC2"`) and `frontend/src/features/quality/pages/Qc1DashboardPage.tsx:21` (`"Pass → QC2"`).
2. **`AnnotatorAnalytics` runtime bug & D06 violations:** `frontend/src/features/jobs/pages/AnnotatorAnalyticsPage.tsx:96` renders literal `"kỳ trước hạng null"` when `ranking.previous_rank` is `null` (`frontend/src/features/jobs/types.ts:265` mis-typed as `number`). D06 violations: `AnnotatorAnalyticsPage.tsx:106` mislabels clamped wall-clock `[15m, 10h]` elapsed intervals as `"Cuboid / giờ làm thực tế"`; `backend/analytics/views.py:1386-1392` returns `0` instead of `null` when `hrs == 0`; `AnnotatorAnalyticsPage.tsx:81-82` displays `total_objects ÷ total_hours` beneath `objects_per_hour` computed server-side from `measured_objects ÷ total_hours`.
3. **Cuboid fields & `is_voided` dropped by readers:** `frontend/src/features/quality/qc1/Qc1ReviewPanel.tsx:115-130` and `frontend/src/features/jobs/components/AnnotatorJobDrawer.tsx:148-155` omit `verdict`, `frame_number`, `cvat_object_id`, `is_missing_object`, and `is_voided` (voided errors appear active).
4. **QC1 UI ignores `EscalationPolicy.WARN_ONLY`:** `frontend/src/features/quality/qc1/Qc1ReviewPanel.tsx:99-101` and `frontend/src/features/quality/pages/Qc1WorkPage.tsx:123` hard-block all `is_escalated` jobs despite backend allowing `WARN_ONLY`.
5. **Removed `team_leader_name` field retained in frontend:** Referenced by `frontend/src/features/jobs/types.ts:212`, `AnnotatorDashboardPage.tsx:76-78`, `ShellContext.tsx:13-14`, `AnnotatorJobDetailPage.tsx`, `AnnotatorReworkPage.tsx`, `DisputeErrorModal.tsx`, and `SupportCenterDrawer.tsx`, while omitted by `AnnotatorDashboardView`.
6. **Non-PM users shown `"Đồng bộ từ CVAT"` (`403`):** `frontend/src/features/projects/pages/ProjectListPage.tsx:52-54` shows the sync trigger (`POST /api/cvat/sync-organizations/`) to all users; `CurrentUser` TS omits `is_pm` and `projects`.
7. **Annotator "Sắp / quá hạn" excludes overdue jobs:** `frontend/src/features/jobs/pages/AnnotatorDashboardPage.tsx:165-171` links `due_soon + overdue` to `?due_soon=1`, which filters `deadline__gte=now` in `backend/jobs/views.py:738-744`; `frontend/src/features/jobs/pages/AnnotatorJobsPage.tsx:147-150` mislabels `?due_soon=1` as `"Sắp / quá hạn"`.
8. **`thresholds` JSON type mismatch:** `backend/analytics/views.py:561-564` passes raw `Decimal` values serialized as JSON `number` (`95.5`), contradicting `string | null` in `frontend/src/features/projects/types.ts:253` and `ProjectSettingsSerializer`.
9. **Notification bell drift:** `frontend/src/layouts/NotificationBell.tsx:59, 142, 225, 235` ignores server `all_count`/`unread_count` (counts only the truncated 50-item slice), diverges on multi-project pin sorting vs `is_read`, and sending ephemeral `due-*` IDs to `mark-read` returns `400` (`backend/projects/views.py:1117-1130`).
10. **Delivery drift:** `DeliveryViewSet.candidates` (`backend/projects/views.py:753-767`) places `pending_qc2_samples` in `open_audits` (labeled `"Đợt QC2 đang mở"` in `frontend/src/features/projects/pages/DeliveryPage.tsx:58`); `PUT /deliveries/<id>/` always returns `400` (`batch` writable in serializer, rejected in `perform_update`); `DeliveryPage.tsx` `FeedbackDialog` omits editing `recipient`/`output_path`.
11. **UI action guards & missing controls:**
    - UI leaves Assign enabled on `pending_qc2`/`approved` (`JobsPage.tsx`, `JobDetailDrawer.tsx`), Lock enabled on `delivered` (`JobDetailDrawer.tsx`), and Report Data Issue enabled on `approved`/`delivered` (`AnnotatorJobDetailPage.tsx:189-196`) where backend returns `400`.
    - External CVAT links in `DatasetsPage.tsx:118` and `BatchesPage.tsx:133` omit `?org=<slug>` and ignore `connected`/`detail` from `GET /api/cvat/status/`.
    - `CvatSyncButton.tsx` exposes no toggle for `count_objects=true`.
    - 8 TS interfaces (`ProjectOverview`, `Qc1Summary`, `Qc2Summary`, `AnnotatorDashboard`, `AnnotatorAnalytics`, `TeamRanking`/`MemberPerformance`, `Workload`, plus `Job`/`SampleJob`/`AuditSample`/`Batch`/`ProjectSummary`/`ProjectSettings`/`CurrentUser`) omit live backend fields; `Qc1Summary` declares nonexistent top-level `pool_pending`.
    - OpenAPI tooling (`drf-spectacular` / `docs/api/openapi.yaml`) remains missing (`T03`).

---

## 4. P2 Cleanup & Hardening Backlog

- **CI:** `.github/workflows/ci.yml` missing `pipenv install --dev --system --deploy` and `manage.py check --deploy`; `pyproject.toml:14` targets `py312` vs runtime `3.14`; `.github/workflows/ci.yml:75` uses Node `20` vs `@types/node ^24`.
- **Orphan routes/exports:** 16 unused backend routes/methods (incl. `GET /api/auth/users/` exposing all-org user emails to single-org PMs, duplicate `/api/auth/change-password/`, `POST/PATCH /api/projects/`, `/settings/`, `/activity/`, `/permission-matrix/`, `bulk-move-batch/`, unused `PUT` on 6 ViewSets, `DefaultRouter` on `backend/projects/urls.py`) and 5 unused frontend exports (`getSettings`, `getPermissionMatrix`, `updateDataset`, `listActivity`, `rejectAuditSample`).
- **Remaining hardening & UX items:** `AnnotatorReworkPage.tsx:26-40` N+1 instead of `?include_errors=1`; `AccountSettingsPage.tsx:46-50` displays only `uniqueRoles[0]`; `backend/accounts/permissions.py:118` lacks `PG_INT32_MAX` bound (HTTP 500 `DataError`); `PrimaryKeyRelatedField` ID existence oracles; `AnnotatorJobViewSet.claim` reads `team_ids` outside `transaction.atomic()`; `AuditSampleViewSet.assign` lacks `PENDING_QC2` guard; `resolve_escalation` leaves `job.status` unconstrained when `annotator` omitted; `ProjectViewSet.get_queryset` superuser mismatch; missing `LOGGING` secret-redaction filter; `CVAT_HOST_HEADER` CRLF/SNI validation.

---

## 5. Resolved Since `0beace7` (Traceability)

- `f212a4f`: Added `_validate_base_url()` and `CVAT_REQUIRE_HTTPS` in `backend/cvat_integration/client.py` (+3 tests) and added `npm test` (Vitest) to `.github/workflows/ci.yml`.
- `7ff163b`: Migrated all remaining Ant Design 6 views to React Aria / Untitled UI, uninstalled `antd` and `@ant-design/icons`, and verified `37/37` Headless Chrome CDP checks on migrated AntD screens.
- `36dae92`: Reconciled refactoring, contracts, security, UI, and product spec docs under `docs/`.
- **Workspace hygiene reminder:** Unstage `VanoHub-Docs-and-Plan-2026-11-27.zip` and `vanohub-docs-starter/*` in the git index before committing.

### Resolved in working tree (2026-11-27)

- **P0 #1 (`MemberCredentialView` / `MemberResetPasswordView`):** Added `_ensure_credential_target_manageable` blocking `is_superuser`/`is_staff`, `Role.PROJECT_MANAGER`, and multi-organization members unless the actor is a superuser; added `Cache-Control: no-store`.
- **P0 #2 (`GET /api/cvat/tasks/`):** Removed the cross-org CVAT task proxy route and view from `backend/cvat_integration/{urls,views}.py` (synced in `docs/api/contracts.md` and `docs/platform-spec.md`).
- **P0 #3 (`POST /api/cvat/link/`):** Scoped link-time sync via `only_cvat_user_id=cvat_id` and switched `_filter_sync_result_for_user` to ID-based project filtering (`created_ids`/`updated_ids`/`organization_id`).
- **P0 #4 (`manage.py check --deploy` & prod settings):** Added env-driven `MAILERS` (`smtp.EmailBackend` when `DEBUG=False`), `POSTGRES_SSLMODE`, HTTPS/HSTS/cookie security flags, `DEBUG`-gated `SessionAuthentication`/`BrowsableAPIRenderer`/`CORS_ALLOWED_ORIGINS`, and DRF anon/user rate throttling in `backend/config/settings.py` + `backend/.env.example` + `.github/workflows/ci.yml`.
- **P0 #5 (AB-BA deadlocks):** Added `lock_job_with_batch` (`Batch → Job`) for `qc1_pass`, sorted CVAT sync projects/tasks by ID, prelocked batch jobs with `.order_by("id")`, and added `.order_by("id")` to `absent_jobs`/`absent_batches`/`sync_batch`.
- **P0 #6 (Four-eyes `L13` gaps):** Added `QC1_PASSED` to `ASSIGN_LOCKED_STATUSES`, enforced `getJobLockReason` on `JobDetailDrawer` Assign button, added `audit_samples`/`review_errors` exclusions to `AnnotatorJobViewSet.claim`, extended `get_stage_history` to `job.assign`/`job.import` payloads, QC1 `after__event`, and `DailyOutputRecord`, and attributed CVAT QC1 completions + `job.import` logs in `sync.py`.
- **P0 #7 (QC2 frame-jump URL):** Added `cvatFrameUrl` helper in `frontend/src/shared/utils/cvat.ts` and updated `ReviewPanel.tsx` to preserve existing `?org=` query params.
- **P0 #8 (`rework_round - 1` drift):** Unified active-round resolution to `max(total_rework_rounds, rework_round) - 1` across `jobs/views.py`, `jobs/serializers.py`, `quality/qc2.py`, `cvat_integration/sync.py`, and frontend `activeErrorRound` / `splitActiveErrors` helpers (`AnnotatorJobDetailPage`, `AnnotatorReworkPage`, `AnnotatorDashboardPage`).
- **P0 #9 (`CvatClient` transport/redaction; `Pipfile.lock` blocked offline):** Set `session.trust_env = False`, stripped/validated tokens before setting headers without echoing secrets, removed raw exception/payload text from `CvatError`, and unstaged starter archive files (`git reset HEAD`). `pipenv lock` failed on sandbox SSL (`SSLCertVerificationError` to `files.pythonhosted.org`), so `Pipfile.lock` and `--deploy` in CI remain untouched.
