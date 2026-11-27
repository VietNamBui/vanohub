# Logical change log

Record one concise entry for every meaningful refactoring, UI, or API unit. Explain the behavioral or structural change and why it matters. Link source, contract, decision, and verification evidence instead of copying implementation details. A unit affecting several layers gets one entry covering all impacts.

Keep implementation status separate from verification results. “Implemented” does not mean tested; a passed check establishes only what it exercised on the recorded revision. Update an existing entry as its evidence changes rather than appending every edit, retry, or tool call. Do not record private reasoning, credentials, personal data, or raw request payloads.

## 2026-11-27 — Initialize documentation package

- **Status:** Documentation package authored and checked; uninstalled. No application implementation is claimed.
- **Purpose:** Provide a small shared record for ongoing refactoring, UI behavior, API contracts, agent handoffs, and verification.
- **Before → after:** Pinned remote snapshots and attached notes are represented in a documentation package with explicit provenance, unresolved decisions, and reusable working procedures. This does not reconcile those snapshots with the user's current local checkout.
- **Scope and impact:** Documentation only. No application files were altered. No UI behavior, API route, payload, authorization rule, workflow transition, schema, or CVAT integration was implemented or changed by this initialization.
- **Compatibility:** No application compatibility claim is needed for this docs-only change. Existing `docs/platform-spec.md` remains the product authority. CVAT project-mapping and workflow-state conflicts remain evidence/decision items; this entry resolves neither. Telemetry and new API ideas remain proposals.
- **Provenance:** See the [baseline](./baseline.md) for pinned remote-source references and attached-note provenance, and [decisions](./decisions.md) for conflicts. The local branch, dirty state, runtime behavior, and MCP index freshness were not verified here. The [agent workflow](./agent-workflow.md) retains the user-reported orchestration configuration without capability claims.
- **Verification:** Internal document links resolved. The nine-file patch passed an isolated applicability/content check; an existing-target collision was rejected and an unrelated local instruction file was preserved. No application tests were run. Archive and checksum results are reported in the delivery README.
- **Reversibility:** The uninstalled package can be discarded or revised. No application migration or external-system effect was performed by this initialization.
- **Commit:** None.
- **Next:** Follow the [plan](./plan.md) to reconcile the package with the active checkout before treating observed claims as current implementation facts.

## 2026-11-27 — T00: Reconcile refactoring docs with `feature/issue-logger` (`0beace7`)

- **Status:** Documentation only (T00 and T02 closed; T01 partially resolved for `D01`–`D03`).
- **Purpose and before → after:** Reconciled the nine starter docs (originally authored from remote branch snapshots) against the active local checkout after merge `8d66adc`. Replaced placeholder T00 fields and stale `issue-logger`-only endpoint notes with verified model, URL, frontend, test, and environment facts on `0beace7`.
- **Scope:** Branch `feature/issue-logger` @ `0beace78eebc8d2bfac3db06ca203f2e6ac35819`; pre-existing staged starter files (`VanoHub-Docs-and-Plan-2026-11-27.zip`, `vanohub-docs-starter/*`); adopted and reconciled `docs/refactoring/{README,baseline,decisions,plan,agent-workflow,changes}.md`, `docs/api/contracts.md`, `docs/ui/verification.md`, and `docs/operations/security-and-verification.md`; synced `docs/{platform-spec,mvp-checklist,ui-spec-traceability}.md`, `ARCHITECTURE.md`, `AGENTS.md`, and `.agents/rules/domain-invariants.md`; plus `T06`/`T07` hardening (`backend/cvat_integration/{client,tests}.py`, `backend/config/settings.py`, `backend/.env.example`, `.github/workflows/ci.yml`).
- **Impacts:** Documentation reconciled against `8d66adc`/`0beace7` (marked `D01`–`D03` accepted/implemented, `D04`–`D06` open, documented `CL02`/`CL05`/`CL11` `pending_definition`, added 2-axis `AND` / `Edge %` / `NS10` proposals to `docs/platform-spec.md`); `T06` added `_validate_base_url()` and `CVAT_REQUIRE_HTTPS` transport enforcement in `CvatClient`; `.github/workflows/ci.yml` added `npm test` to the frontend CI job.
- **Compatibility:** No breaking runtime, API, or DB schema change (`CVAT_REQUIRE_HTTPS` defaults to `False`). Preserved `D04`–`D06` open; explicitly documented `CL02`/`CL05`/`CL11`, `NS04`, and `DB02`/`DB03` returning `status="pending_definition"` / `value=None` (`AuditSample.checked_object_count=None`) in `backend/analytics/views.py`.
- **Evidence:** Directly verified on disk across `backend/config/{settings,urls}.py`, `backend/*/urls.py`, `backend/{projects,jobs,quality,cvat_integration}/models.py`, `backend/projects/views.py`, `backend/quality/{qc2,views,serializers}.py`, `backend/analytics/views.py`, `backend/cvat_integration/{client,sync,assignee,views,schemas,tests}.py`, `.github/workflows/ci.yml`, `frontend/src/app/router.tsx`, `frontend/src/features/**`, and `rg` across `frontend/src`.
- **Verification:** Observed passing across workspace changes: `cd backend && pipenv run ruff check ../backend` (`All checks passed!`), `cd backend && pipenv run pyright -p ../pyproject.toml` (`0 errors, 0 warnings, 0 informations`), `pipenv run python manage.py check` (`0 issues`), `pipenv run python manage.py makemigrations --check --dry-run` (`No changes detected`), `pipenv run python manage.py test --noinput` against PostgreSQL 17 (**`Ran 208 tests in 198.134s — OK`** = `205` baseline + `3` new `CvatClient` tests), `manage.py check --deploy` (6 expected dev items under `DJANGO_DEBUG=True`: `mail.E001`, `security.W004/W008/W012/W016/W018`); `cd frontend && npx tsc -b --noEmit` (`0` errors), `npm run lint` (`0` errors), `npm test` (`4` Vitest files / `13` tests passed), `npm run build` (`vite build` succeeded in `819ms`); relative markdown link check across `14` doc files (`109` links, `0` broken).
- **Reversibility:** Code/config changes (`CvatClient` validation, `CVAT_REQUIRE_HTTPS`, CI `npm test`) revert cleanly with zero DB migration or external CVAT side effect.
- **Commit:** None.
- **Follow-up:** Unstage starter archive before commit (`git reset HEAD -- VanoHub-Docs-and-Plan-2026-11-27.zip vanohub-docs-starter`), resolve `D05` (`CL02`/`CL05`/`CL11` frame count, `S0`, manual `object_count` lock), execute `T03` OpenAPI generation (`drf-spectacular` → `docs/api/openapi.yaml`), and configure production `DJANGO_DEBUG=False` / `CVAT_REQUIRE_HTTPS=True` / TLS settings (`T06`).

## 2026-11-27 — T05: Migrate remaining 13 Ant Design 6 files to React Aria / Untitled UI and uninstall `antd`

- **Status:** Implemented and verified (TypeScript, ESLint, Vitest, Vite production build, and live 4-role Headless Chrome suite green; live CVAT-linked E2E `NT02` and non-AntD FE↔BE parity screens remain open).
- **Purpose and before → after:** Eliminated dual UI frameworks (`antd` 6.7.1 + React Aria) across the remaining 13 files in `frontend/src/`, eliminating Ant Design bundle overhead (`vendor-antd-*` / `vendor-rc-*` chunks and 66 npm packages) and the runtime `Spin` deprecation `console.error` warning in favor of `react-aria-components`, Untitled UI primitives, Tailwind CSS 4, and `@untitledui/icons`.
- **Scope:** Branch `feature/issue-logger` @ `0beace7` (dirty workspace). Created `frontend/src/shared/hooks/toastContext.ts`, `frontend/src/shared/components/ui/ToastProvider.tsx`, `frontend/src/shared/components/ui/Slideover.tsx`, and `frontend/src/shared/components/ui/SearchableSelect.tsx`; extended `FormDialog.tsx` (`maxWidthClass`); migrated `frontend/src/main.tsx`, `frontend/src/shared/hooks/useAction.ts`, `frontend/src/shared/components/StateView.tsx`, `frontend/src/features/projects/components/{ProjectSwitcher,MemberSelect,CvatSyncButton}.tsx`, `frontend/src/features/jobs/components/{JobStatusTag,AssigneeSelect,AssignModal,JobDetailDrawer}.tsx`, `frontend/src/features/jobs/pages/{QueuePage,JobsPage}.tsx`, and `frontend/src/features/quality/qc2/AuditsPage.tsx`; restored header `RoleBadges` + `projectId`-scoped header refresh in `MainLayout.tsx`, 1-click search clear + 3-state sort cycle in `JobsPage.tsx`, and wider modal/validation/React Aria `Select` in `GuidelinesPage.tsx`; cleaned `frontend/vite.config.ts` and `frontend/src/index.css`; removed `antd` and `@ant-design/icons` from `frontend/package.json` and `frontend/package-lock.json`.
- **Impacts:** Frontend only; no backend or API contract changes. Preserved capability guards, read-only `AuditsPage`, searchable dropdowns & rich assignee role/CVAT hints, URL filter sync, bulk selection, 3-state sortable columns, four-eyes disabled keys, keyed React 19 modal/drawer state resets, and `JOB_STATUS_COLORS` export tested by `constants.test.ts`.
- **Compatibility:** Drop-in replacement across internal callers; no external API consumers affected.
- **Evidence:** `rg -n "antd|@ant-design" frontend/src frontend/vite.config.ts frontend/package.json` returned zero matches after `npm uninstall antd @ant-design/icons`. Vite build output dropped from `5864` modules (`819ms`) to `2788` modules (`519ms`) with only `vendor-react`, `vendor-aria`, and `vendor-icons` vendor chunks.
- **Verification:** Passed in `frontend/`: `npx tsc -b --noEmit` (0 errors), `npm run lint` (0 errors), `npm test` (`4` files / `13` tests passed), `npm run build` (`vite build` `519ms`). Live Headless Chrome CDP suite (`Google Chrome 158.0.8127.88 --headless=new`, `seed_demo --reset` org `#7`) passed **37/37 checks** across `pm_demo`, `qc2_demo`, `qc1_demo`, and `ann1_demo` (including `SearchableSelect` in `ProjectSwitcher` & `AssigneeSelect` role/unlinked options, `JobsPage` clear & `JobDetailDrawer` Slideover, `GuidelinesPage` validation modal, `confirm-qc2`, QC2 `Pass`, `QueuePage` stage tabs, `AuditsPage` Slideover, `404` isolation, and `RequireCap`) with **0** console errors, **0** JS exceptions, and **0** unexpected HTTP `>= 400` responses.
- **Reversibility:** Frontend-only diff; zero DB migrations or persistent external effects.
- **Commit:** None.
- **Follow-up:** Complete remaining non-AntD FE↔BE parity items (Project Settings, Activity Log, `ReviewError` display on `Qc1ReviewPanel`/`AnnotatorJobDrawer`) and CVAT-linked E2E acceptance (`NT02`).

## Reusable entry

Copy this template for a logical unit; omit irrelevant subdetails, not material risks. Use the actual completion/update date and stable task identifier. Record UI label examples in Vietnamese when needed. Refer to [contracts](../api/contracts.md), [UI verification](../ui/verification.md), and [operational verification](../operations/security-and-verification.md) where applicable.

```text
## YYYY-MM-DD — ID: concise change title

- Status: proposed / in progress / implemented / blocked / documentation only.
- Purpose and before → after: problem, logical change, resulting behavior.
- Scope: owner; worktree/branch; HEAD; relevant dirty diff; changed files.
- Impacts: refactoring; UI; API; permissions/workflow; data/CVAT; consumers.
- Compatibility: preserved behavior or breaking change; rollout/deprecation;
  linked contract/decision; affected consumers and required coordination.
- Evidence: current source references and revision; distinguish historical
  evidence, proposals, and directly observed implementation.
- Verification: check/command, working directory, revision/environment,
  actual result; failed, blocked, or unrun checks and their concrete reason.
- Reversibility: code rollback; migration/data limits; external effects;
  compensating actions when rollback cannot undo effects.
- Commit: exact authorized commit hash, or none.
- Follow-up: remaining decision/check/action, owner, and completion condition.
```

Do not describe a code revert as a complete rollback when migrations, data transformations, notifications, or CVAT API writes have already taken effect. Record those limits and any verified recovery procedure. Never infer a successful application check from a documentation check or from another branch's historical test result.

## 2026-11-27 — T01/T08: Record D04 hybrid SSoT/sidecar decision and Dec 4 MVP implementation plan

- **Status:** Documentation only.
- **Purpose and before → after:** Updated VanoHub refactoring and operational docs to adopt the user-selected architecture (**VanoHub = workflow/QC SSoT; slim in-process CVAT-side `cvat-event-pipeline-v2` extension; API-only export ingestion**), integrate findings from the 4-agent technical/spec feasibility audit and `/media/bang/Work/projects/cvat-docs/cvat-event-pipeline-v2`, mark `T05` Ant Design migration status consistent with `changes.md`, and scope `T08` to a concrete 7-day **Dec 4, 2026 MVP** cut.
- **Scope:** Branch `feature/issue-logger` @ `0beace7` (dirty workspace). Updated `docs/refactoring/plan.md`, `docs/refactoring/decisions.md`, `docs/refactoring/README.md`, `docs/operations/security-and-verification.md`, and `docs/refactoring/changes.md`. Left `docs/platform-spec.md`, `backend/`, and `frontend/` untouched in this turn.
- **Impacts:** Sets `D04` to accepted (pending `PV04` amendment in `docs/platform-spec.md` & implementation), establishes non-contaminating boundary rules (no CVAT event mutations into `Job.status`, `AuditSample`, `ReviewError`, `AnnotatorRequest`, or `ActivityLog` four-eyes history), documents CVAT `POST /api/events/export` OPA/transport/ClickHouse constraints, and scopes Dec 4 MVP deliverables vs post-Dec 4 deferrals (2D parity, `QcEventOutbox` feed `R21`, external Pre-QC worker `R07`, `T03` OpenAPI).
- **Compatibility:** Documentation only; preserves existing application contracts and `D05`/`D06` pending-definition analytics behavior until implementation.
- **Evidence:** Directly verified against `backend/cvat_integration/{client,sync,assignee,schemas,models,views}.py`, `backend/quality/{models,views,qc2}.py`, `backend/analytics/views.py`, `backend/Pipfile`, `docker-compose.yml`, `/media/bang/Work/projects/cvat-base/cvat/apps/{events,access_tokens,iam}/`, `/media/bang/Work/projects/cvat-di-ext/`, and `/media/bang/Work/projects/cvat-docs/cvat-event-pipeline-v2/`.
- **Verification:** Verified zero broken relative markdown links across `vanohub/docs/` and inspected `git diff --stat` scoped strictly to the 5 documentation files; no backend/frontend code changed and no runtime tests run in this docs-only pass.
- **Reversibility:** Documentation-only edits; revert cleanly via `git checkout -- docs/refactoring docs/operations/security-and-verification.md`.
- **Commit:** None.
- **Follow-up:** Day 1 Gate 0 — amend `PV04` in `docs/platform-spec.md`, sign off `D05`/`D06` MVP defaults, configure CVAT read-only service PAT + persistent Vector/ClickHouse volumes, then execute Days 2–3 VanoHub API export consumer + `D03`/`D05`/`D06` implementation.

## 2026-11-27 — Remove superset-only `urls.py` routes to match `annotator-qclv1`

- **Status:** Implemented and verified.
- **Purpose and before → after:** Removed the three superset-only routes present on `feature/issue-logger` (`GET /api/cvat/tasks/`, `GET /api/auth/users/`, and duplicate `POST /api/auth/change-password/`) so all 8 backend `urls.py` route sets match `annotator-qclv1` (`backend/accounts/urls.py` retains CBV `.as_view()` bindings for `MeView` and `ChangePasswordView`) and eliminate the P0 `GET /api/cvat/tasks/` cross-org leak and orphan `GET /api/auth/users/` email exposure.
- **Scope:** Branch `feature/issue-logger` @ `cbc05e5` (dirty workspace). Updated `backend/accounts/{urls,views,tests}.py`, `backend/cvat_integration/{urls,views,tests}.py`, `docs/api/contracts.md`, `docs/platform-spec.md`, and `docs/refactoring/changes.md`.
- **Impacts:** Backend API surface and docs only; frontend had zero callers for all three removed routes (`AccountSettingsPage` uses `/api/auth/me/password/`).
- **Compatibility:** Breaking only for any external caller of `/api/cvat/tasks/`, `/api/auth/users/`, or `/api/auth/change-password/` (now 404). Canonical `/api/auth/me/password/` is unchanged.
- **Evidence:** `git diff annotator-qclv1 -- backend/*/urls.py` shows empty diff across `config`, `analytics`, `cvat_integration`, `jobs`, `projects`, `quality`, and `teams`, and only FBV→CBV style difference on `accounts/urls.py` (`me`→`MeView.as_view()`, `change_password`→`ChangePasswordView.as_view()`).
- **Verification:** `cd backend`: `pipenv run ruff check .` (`All checks passed!`), `pipenv run pyright -p ../pyproject.toml` (`0 errors, 0 warnings, 0 informations`), `pipenv run python manage.py check` (`0 issues`), `pipenv run python manage.py makemigrations --check --dry-run` (`No changes detected`), `pipenv run python manage.py test --noinput` (`Ran 212 tests in 206.701s — OK`).
- **Reversibility:** Pure code/doc diff; zero DB migrations or external CVAT side effects.
- **Commit:** None.
- **Follow-up:** None for `urls.py` parity.

## 2026-11-27 — Fix open P0 blockers (#1, #3–#9) from `total-eval-2026-11-27.md`

- **Status:** Implemented and verified locally (`Pipfile.lock` / CI `--deploy` blocked offline by sandbox PyPI SSL).
- **Purpose and before → after:** Closed the remaining 8 open P0 blockers from [total-eval-2026-11-27.md](./total-eval-2026-11-27.md) alongside the already-removed `/api/cvat/tasks/` route (`P0 #2`): prevented cross-org/superuser credential exposure and password resets, scoped link-time CVAT org sync to the linking user with ID-based filtering, hardened `CvatClient` transport/error redaction, added env-driven Django production security/mail/throttling defaults, eliminated `qc1_pass` AB-BA lock inversions and unordered CVAT sync row locks, plugged four-eyes (`L13`) bypasses across `QC1_PASSED` reassignment/`claim`/`get_stage_history`/CVAT QC1 completion, fixed double-`?` QC2 CVAT frame-jump links, unified post-escalation active rework error round resolution (`max(total_rework_rounds, rework_round) - 1`), and unstaged starter archive files from the git index.
- **Scope:** Branch `feature/issue-logger` @ `761ae78` (dirty workspace; no commit created by this task). Updated `backend/projects/{views,tests}.py`, `backend/cvat_integration/{client,sync,views,tests}.py`, `backend/jobs/{views,serializers,tests}.py`, `backend/quality/{qc2,views,tests}.py`, `backend/config/settings.py`, `backend/.env.example`, `.github/workflows/ci.yml`, `frontend/src/shared/utils/cvat{.test,}.ts`, `frontend/src/features/quality/qc2/ReviewPanel.tsx`, `frontend/src/features/jobs/{jobHelpers.ts,jobs.test.tsx,components/JobDetailDrawer.tsx,pages/{AnnotatorDashboardPage,AnnotatorJobDetailPage,AnnotatorReworkPage}.tsx}`, `docs/refactoring/{total-eval-2026-11-27,changes}.md`, and `docs/operations/security-and-verification.md`.
- **Impacts:** Strengthens multi-org tenant isolation and four-eyes enforcement; `POST /api/projects/{id}/jobs/{id}/assign/` and UI "Giao lại" now reject `qc1_passed` onward; `DEBUG=False` disables `SessionAuthentication`, `BrowsableAPIRenderer`, and localhost CORS defaults while enabling JWT-only auth, `smtp.EmailBackend`, HTTPS security headers/cookies, and DRF rate throttling (`120/minute` anon, `2000/minute` user).
- **Compatibility:** Existing VanoHub API contracts preserved (`created_ids`/`updated_ids`/`organization_id` added internally for view filtering and stripped before response); non-QC1-passed rework error resolution now aligns `open_error_count`, `submit_annotation`, and annotator UI after `resolve-escalation`.
- **Evidence:** [total-eval-2026-11-27.md](./total-eval-2026-11-27.md), [security-and-verification.md](../operations/security-and-verification.md), `backend/projects/views.py`, `backend/cvat_integration/{client,sync,views}.py`, `backend/jobs/{views,serializers}.py`, `backend/quality/{qc2,views}.py`, `backend/config/settings.py`, and frontend helpers/tests.
- **Verification:**
  - Frontend (`frontend/`): `npm test` (`10` files / `37` tests passed), `npx tsc -b --noEmit` (0 errors), `npm run lint` (0 errors), `npm run build` (`vite build` succeeded in `527ms`).
  - Backend (`backend/`): `pipenv run ruff check .` (`All checks passed!`), `pipenv run pyright -p ../pyproject.toml` (`0 errors, 0 warnings, 0 informations`), `manage.py check` (`0 issues`), `manage.py makemigrations --check --dry-run` (`No changes detected`), `DJANGO_DEBUG=False DJANGO_ALLOWED_HOSTS=vanohub.example.com manage.py check --deploy` (exit `0`, 0 errors — `mail.E001` resolved, only optional `security.W005`/`W021`), `manage.py test --noinput` (`Ran 219 tests in 216.877s — OK` under `DEBUG=True`), and `DJANGO_DEBUG=False DJANGO_SECURE_SSL_REDIRECT=False manage.py test --noinput` (`Ran 219 tests in 212.455s — OK`).
  - Blocked offline: `pipenv lock` failed with `SSLCertVerificationError` connecting to `files.pythonhosted.org`, so `backend/Pipfile.lock` and `--deploy` in `.github/workflows/ci.yml` were skipped per plan.
- **Reversibility:** Code/config changes only; zero DB migrations added. Note `git reset HEAD -- VanoHub-Docs-and-Plan-2026-11-27.zip vanohub-docs-starter` unstaged the starter files without deleting disk copies.
- **Commit:** None.
- **Follow-up:** Run `cd backend && pipenv lock && pipenv sync --dev` in a network/cert-trusted environment and switch `.github/workflows/ci.yml` to `pipenv install --dev --system --deploy`, plus triage remaining §2 P1 / §3 parity items in [total-eval-2026-11-27.md](./total-eval-2026-11-27.md).
