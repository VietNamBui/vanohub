# VanoHub implementation and documentation plan

Prepared: 2026-11-27, Asia/Ho_Chi_Minh.

**Goal:** finish the ongoing VanoHub refactor with coherent CVAT mapping, reliable workflow behavior, matching backend/frontend contracts, and enough documentation to resume work without replaying the conversation.

**Starting position (reconciled on `0beace7`):** `feature/issue-logger` has already incorporated `8d66adc` (merging `annotator-qclv1 @ 6384711` and `feature/project-manager @ 24ca99c`), and `codebase-memory-mcp` indexes `media-bang-Work-projects-vanohub` (generation `2026-11-27T04:48:39Z`). The reported coordination default is Neon Extra High as orchestrator and Hydrogen Extra High as executor.

**Operating default:** one orchestrator and one executor. Preserve completed work, retrieve narrow context, and document logical changes. Model labels do not imply a measured token saving.

## 1. Scope and constraints

- Consume CVAT annotation and operational data through its API. VanoHub must not read CVAT PostgreSQL or NAS directly. VanoHub's own database remains its normal persistence layer.
- Keep CVAT responsible for annotation data; keep VanoHub responsible for its business workflow, QC decisions, assignments, audit history, and delivery.
- Preserve the four-role model, project isolation, four-eyes rules, and protection of QC2/approved/delivered states unless a specific product change is accepted.
- Reuse `docs/platform-spec.md`, `docs/mvp-checklist.md`, `ARCHITECTURE.md`, `AGENTS.md`, and scoped rules. Record conflicts instead of silently choosing a historical branch.
- Keep new telemetry, webhook, native CVAT extension, and sidecar work conditional on an actual requirement. Documentation alone does not create an endpoint.
- Distinguish structural refactoring from changes to behavior, permissions, data models, API payloads, or UI semantics.

See [baseline](baseline.md) for evidence and [decisions](decisions.md) for unresolved choices.

## 2. Work plan

Statuses reconciled against `feature/issue-logger @ 0beace7`:

| ID | Status | Outcome and work | Dependency | Owner | Acceptance evidence |
| --- | --- | --- | --- | --- | --- |
| T00 | **closed** | Captured active checkout (`0beace7`), staged starter diff, index coverage (`2026-11-27T04:48:39Z`), OpenAPI tooling absence, and reconciled docs. | None | Executor gathers; orchestrator reconciles | [baseline.md](baseline.md), [contracts.md](../api/contracts.md), [ui/verification.md](../ui/verification.md) |
| T01 | **in progress** *(partial)* | `D01`–`D03` accepted and implemented in `8d66adc`/`3fb6b6f`; `D04` accepted (VanoHub SSoT + strict stock CVAT API-only CSV export; `PV04` intact, external CVAT extensions decoupled); `D05`–`D06` remain open for final KPI formula sign-off. | T00 | Orchestrator; executor provides evidence | [decisions.md](decisions.md) |
| T02 | **closed** | Runnable green baseline verified on `0beace7`: 205 Django tests (PostgreSQL 17), 4 Vitest files / 13 tests, ruff/pyright/check/migrations/tsc/eslint/vite build clean. | T00 | Executor | [baseline.md](baseline.md), [changes.md](changes.md) |
| T03 | **planned** *(deferred post-Dec 4)* | Endpoint inventory synced in [contracts.md](../api/contracts.md); establish reproducible OpenAPI generation (`drf-spectacular` → `docs/api/openapi.yaml`) and contract examples. | T00, T02; T01 for disputed surfaces | Orchestrator owns semantic decisions; executor owns schema implementation | Current contract identified by revision, generated schema validated, consumers aligned |
| T04 | **in progress** | Core Hybrid A2, frame QC2, structured `ReviewError`, `DailyOutputRecord`, CVAT org/task/job sync & assignee push implemented in `8d66adc`. Remaining: `D03` durable `CvatAssigneeOutbox` (cron-drained without broker), frame-scoped `AuditSample.checked_object_count` via existing `CvatAnnotationsPayload.count_object_frames(..., included_frames=sample.frames)` (no CVAT sidecar needed), `quality/qc2.py:pick_frames` alignment for `frame_step`/`deleted_frames`, and `D05`-blocked counting (`CL02`/`CL05`/`CL11`, `S0`, manual `object_count` lock). | Affected T01 decisions and affected T03 contracts | Executor | Focused diff, regression tests, migrations when needed |
| T05 | **in progress** *(AntD complete)* | Migrated ALL 13 remaining `antd` files (`main.tsx`, `StateView`, `useAction`, `ProjectSwitcher`, `MemberSelect`, `CvatSyncButton`, `JobStatusTag`, `AssigneeSelect`, `AssignModal`, `JobDetailDrawer`, `QueuePage`, `JobsPage`, `AuditsPage`) to React Aria (`react-aria-components`) / Untitled UI + shared `ToastProvider`/`Slideover`; uninstalled `antd` & `@ant-design/icons` (`vite build` 513ms, 37/37 Headless Chrome checks with 0 console errors). Remaining: non-AntD FE↔BE parity screens (Project Settings, Activity Log, Org create/edit, `ReviewError` display gaps) + real CVAT browser QA (`NT02`). | Stable affected T03 contracts; T04 for integration checks | Executor; separate UI writer only for independent files | [UI checklist](../ui/verification.md) zero remaining `antd` imports (verified), Headless Chrome 37/37 green |
| T06 | **in progress** *(partial)* | `DJANGO_ALLOWED_HOSTS` env parsing (`settings.py:34-41`) and `CvatClient` URL/`CVAT_REQUIRE_HTTPS` transport hardening + CI tests implemented in current workspace; production deployment hardening (`DJANGO_DEBUG=False`, `mail.E001`, `security.W004/W008/W012/W016`, TLS/proxy headers, `pg_dump` backups) and CVAT export/read-only PAT transport controls remain open. | T00; T01 if write or trust boundaries change | Executor | [Security checks](../operations/security-and-verification.md), `CvatClient` URL/HTTPS unit tests, `manage.py check --deploy` under `DJANGO_DEBUG=False` |
| T07 | **in progress** | `.github/workflows/ci.yml` updated with `npm test` (`.github/workflows/ci.yml:88-89`); run full backend + frontend CI-parity gates across workspace changes and verify live browser flows + Dec 4 runtime acceptance matrix (`R01`, `R02`, `R03` 3D, `R04`–`R06`, `R11`–`R13`, `R17`–`R20`). | Affected T04/T05/T06 work and Dec 4 `T08` implementation | Executor runs; orchestrator reviews | Exact commands/results tied to final revision and environment |
| T08 | **planned** *(Dec 4 MVP optional)* | Implement `D04` stock CVAT API-only export ingestion on Django + PostgreSQL 17 (`POST /api/events/export` for `send:working_time`, cron + DB lease/advisory lock) with zero CVAT fork/patch/extension dependency (`PV04` intact). | `D04` (`PV04` intact), `D05`/`D06` MVP rules via T01; affected T03 contracts | Orchestrator scopes; executor implements | Accepted contract, authorization, replay/idempotency behavior, stock CVAT export tests & live verification |
| T09 | **planned** | Close milestone and hand over next bounded task. | Required scope passes T07 on final revision | Orchestrator | Updated current docs, change entry, disclosed out-of-scope work |

T08 is strictly scoped to stock CVAT API-only export ingestion (`PV04` intact — zero CVAT fork, patch, or in-process extension owned by VanoHub). Keep VanoHub on Django 6 + PostgreSQL 17 without introducing Celery, RQ, Redis, or direct CVAT DB/ClickHouse access.

## 3. T00: adopt the active work, once

Capture the worktree identity using read-only commands from its root:

~~~bash
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
git diff --stat
git diff --cached --stat
~~~

Inspect relevant untracked files as well as staged and unstaged diffs. These commands do not establish index freshness by themselves. Use the installed MCP server's actual tool schema to inspect the indexed project/root and available revision, coverage, watcher, or freshness information. If this is unavailable, record unknown and validate the specific current files before relying on graph results.

Read existing local instructions before applying any advice in this package. Do not reset, stash, rebase, or discard another agent's work as part of adoption. If parallel implementation is useful, use isolated worktrees with explicit ownership and confirm each index targets the correct worktree.

Add the local record to [baseline.md](baseline.md). Update task status from evidence. Keep historical source observations intact and clearly dated.

## 4. T01: decisions that change the implementation

Historical branch discrepancies for `D01` (CVAT Organization → `Project`, CVAT Project → `Dataset`, CVAT Task → `Batch`, CVAT Job → `Job`), `D02` (Hybrid A2 `confirm-qc2` + frame-level QC2), and `D03` (`CvatAccount` + `invite_to_org` + `schedule_assignee_push`) were resolved and implemented in `8d66adc` (see [decisions.md](decisions.md)).

Remaining open decisions are `D04` (telemetry/extension placement), `D05` (frame-level `CL02`/`CL05`/`CL11` denominator, pre-label `S0`, locking manual `object_count`, `NS09`/`NS10`, 2-axis evaluation), and `D06` (time/duration semantics for `NS04` and `DB02`/`DB03`). Resolve affected open records before changing schemas, metrics, or workflow gates.

The orchestrator can resolve routine implementation choices. Ask the user only when a genuinely unresolved product choice would change behavior or invalidate existing data; prepare the alternatives and consequences first. Continue unrelated work.

## 5. T03–T05: contract-led implementation slices

For each slice, identify the source revision and state the intended behavior:

1. Capture current inputs, outputs, permissions, state changes, and actual consumers.
2. Describe the proposed change and whether existing consumers continue to work.
3. Implement the smallest coherent backend slice, including any necessary migration.
4. Update affected frontend types, API wrappers, guards, forms, and Vietnamese labels.
5. Verify the relevant behavior, then satisfy the repository's required task-completion gates.
6. Record one entry in [changes.md](changes.md) and update the relevant current document.

Use a stable contract to enable independent backend/UI work. Assign one writer to shared serializers, schema output, migrations, role definitions, and the plan's active handoff. Do not merge entire historical branches merely because one contains a useful implementation.

### Backend focus for T04

- Fetch and validate remote data outside long database transactions; recheck mutable local preconditions under the appropriate lock before applying a result.
- Preserve validated CVAT payload handling, bounded request behavior, and project/job ownership checks.
- Distinguish current visible object-frame counts, credited output, and quality denominators. Validate track/frame edge cases against the deployed CVAT version.
- Keep remote writes explicit. A post-commit callback is not a durable background job.
- Specify retry, stale-data, partially missing-job, and source-deleted behavior. Do not claim incremental sync correctness from an unverified timestamp filter.
- Attribute audit actions to the correct actor/source. Avoid interpreting a PM-triggered sync as proof that the PM performed annotation or QC.

### UI focus for T05

Prioritize the existing import/sync, assignment/claim, QC1, PM confirmation, QC2 audit, and delivery flows. Reuse the active design system. If an Ant Design-to-Untitled UI migration is part of the local task, migrate a coherent screen and keep behavior/contract checks separate from visual changes.

## 6. Dec 4 MVP Plan — VanoHub SSoT + Stock CVAT API Only

**Topology invariant (`D04` / `PV04`):** VanoHub remains the sole workflow, 4-role RBAC, Hybrid A2 `confirm-qc2`, frame-level `AuditSample`, `Delivery`, and KPI SSoT, integrating **strictly through stock `cvat-base` REST APIs** (`PV04` intact — zero CVAT fork, patch, or in-process extension owned by or coupled to VanoHub). Direct CVAT PostgreSQL, ClickHouse, Vector, and NAS access from VanoHub remain prohibited.

### Day-by-Day Dec 4 Schedule (Nov 27 → Dec 4)

- **Day 1 (Nov 27–28) — Gate 0 & CVAT Infra:**
  - Preserve `PV04` in `docs/platform-spec.md` (stock `cvat-base` only; zero CVAT extension dependency); sign off `D05`/`D06` MVP formulas (`AuditSample.frames` denominator, `Quality CL = (pass + edge) / checked` with `Fail > Edge > Pass`, stock `send:working_time` window attribution to `NS04` with `unavailable` fallback, untrusted client telemetry banned from KPIs).
  - Provision a dedicated non-admin CVAT service account (global privilege `user` + org role `maintainer`/`owner` + `read_only=True` PAT) for export/poll/download; mount persistent `/home/django/events` and `/vector-data-dir` with Vector disk buffer/acknowledgements; set `CVAT_EXPORT_CACHE_TTL=3600`.
- **Days 2–3 (Nov 29–30) — VanoHub Stock CVAT Export Consumer + `D03`/`D05`/`D06`:**
  - Extend `CvatClient` (`backend/cvat_integration/client.py`) with dedicated read-only export token support, org-header-free `create_events_export` (never combining `X-Organization`/`org` with `?org_id=`), `get_request_status`, `CVAT_HOST_HEADER`-safe `stream_download(result_url)` (`allow_redirects=False`), and `count_job_objects(..., target_frames=sample.frames)`.
  - Add PostgreSQL 17 models (`CvatSyncScope`, `CvatExportBatch`, `CvatEventLedger`, `CvatWorkingTimeEvent`, `CvatEventQuarantine`; `CvatAssigneeOutbox` for `D03` is already implemented in `3fb6b6f`) and `manage.py ingest_cvat_events` (5-min cron/systemd timer, DB lease/advisory lock, bounded `from`/`to` windows outside DB locks, redact comment bodies & `user_email`, reject `org_id=null`/foreign-org rows, store raw `(cvat_job_id, cvat_user_id)` with nullable `job`/`user` FKs).
  - Keep ingested events strictly isolated from `ActivityLog` four-eyes history, `Job.status`, `ReviewError`, and `AnnotatorRequest`. Align `quality/qc2.py:pick_frames` for `frame_step`/`deleted_frames`, and wire `AuditSample.checked_object_count` (`CL02`/`CL05`/`CL11`) + `NS04` (`send:working_time`).
- **Days 4–5 (Dec 1–2) — VanoHub Issue Logging & Management (Slices 1–2, Stock CVAT Read-Only):**
  - Implement [issue-logging-port-plan.md](./issue-logging-port-plan.md) Slices 1–2 strictly over stock CVAT `GET /api/issues` and `GET /api/comments` (`JobIssue`, hardened OPA tamper defenses, Submit/Acceptance gates, PM ruling, and Untitled UI review controls).
- **Days 6–7 (Dec 3–4) — Runtime Acceptance & Release Gate:**
  - Execute live stock CVAT + VanoHub 4-role E2E (`NT02`), deploy hardening (`T06`: `Pipfile.lock`, prod env, TLS, backups), full VanoHub CI gates (Ruff, Pyright, Django `check`/`check --deploy`, `makemigrations --check --dry-run`, PostgreSQL 17 tests, frontend `tsc`, `eslint`, `vitest`, `vite build`), and multi-role live browser smoke tests.

### Explicitly Deferred Post-Dec 4

- VanoHub plug-in stubs (`B1`–`B5` in `docs/platform-spec.md`: `Protocol` hooks, `JobTelemetryEvent`, external Auto-QC findings ingest, CVAT HMAC webhook ingest).
- VanoHub-native `S0` pre-label baseline & 3D geometry diff over stock CVAT annotation payloads, `T03` OpenAPI generation, `Delivery.reopen` (`BG04`), and remaining non-blocking FE↔BE parity / P2 KPIs.

## 7. Definition of completion

A milestone is complete when its accepted scope is implemented, its affected contract and UI agree, applicable required gates pass on the final integrated revision, and relevant documentation reflects the result. A documented exception counts only when the existing repository policy permits it. Keep implemented work with failed, blocked, or unrun required gates open and report that verification status. An unfinished optional telemetry task does not block unrelated core work when it is outside the accepted milestone scope.

For schema changes, include migration/roll-forward evidence and distinguish database rollback from code rollback. For remote writes, explain any persistent external effects. Do not imply that reverting a commit reverses invitations, assignments, notifications, or data migrations.

## 8. Active handoff

| Field | Current value (`feature/annotator-qclv1`) |
| --- | --- |
| Task | Dec 4 MVP active (`D04` strict stock CVAT API-only integration, `PV04` intact, external CVAT extensions decoupled), following `3fb6b6f` P1/P2 hardening + FE parity. Execute Gate 0 (`D05`/`D06` MVP defaults, CVAT read-only export PAT & Compose persistence), VanoHub `AuditSample.checked_object_count` / `T08` stock export ingestion, and [issue-logging-port-plan.md](./issue-logging-port-plan.md) Slices 1–2. Deferred post-Dec 4: plug-in stubs (`B1`–`B5`), `S0`/3D diff, `T03` OpenAPI, non-blocking FE↔BE parity & prod TLS. |
| Worktree / revision | `/media/bang/Work/projects/vanohub`, branch `feature/annotator-qclv1` (atop `3fb6b6f`) |
| Files owned | Reconciled `docs/refactoring/*`, `docs/api/contracts.md`, `docs/ui/verification.md`, `docs/operations/security-and-verification.md`, synced product/rule docs, `T06`/`T07` backend/CI hardening, and decoupling guardrail in `backend/projects/test_integrity.py`; assign single-writer ownership per next slice |
| Established evidence | [baseline.md](baseline.md), [decisions.md](decisions.md) (`D01`–`D04` accepted; `D05`–`D06` open with Dec 4 defaults), [contracts.md](../api/contracts.md), [ui/verification.md](../ui/verification.md), [security-and-verification.md](../operations/security-and-verification.md), [changes.md](changes.md) |
| Checks / outcomes | Backend (`3fb6b6f`): `ruff check ../backend` (0), `pyright -p ../pyproject.toml` (0), `manage.py check` (0), `manage.py check --deploy` (`PIPENV_DONT_LOAD_ENV=1`, exit 0), `makemigrations --check --dry-run` (0), `manage.py test --noinput` (`248/248` OK on PostgreSQL 17). Frontend: `0` `antd` refs, `tsc -b --noEmit` (0), `npm run lint` (0), `npm test` (`10` files / `48` tests OK), `npm run build` (`vite build` `542ms`), and Headless Chrome CDP multi-role suite (`25/25` passed, `0` console/JS/unexpected HTTP errors). |
| Next action / blocker | **Gate 0:** sign off `D05`/`D06` MVP rules (preserving `PV04`), configure stock CVAT `read_only=True` export PAT + persistent Vector/ClickHouse mounts if enabling `T08`, and begin [issue-logging-port-plan.md](./issue-logging-port-plan.md) Slice 1 or `checked_object_count` / `T08` stock export consumer. |

Replace this handoff when the active task changes. Preserve only durable outcomes in the change log.
