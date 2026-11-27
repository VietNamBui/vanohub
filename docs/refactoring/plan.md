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
| T01 | **in progress** *(partial)* | `D01`–`D03` accepted and implemented in `8d66adc` (note `D03` reliability gap); `D04`–`D06` remain open (`CL02`/`CL05`/`CL11`, `S0`, `object_count` lock, `NS09`/`NS10`, 2-axis evaluation). | T00 | Orchestrator; executor provides evidence | [decisions.md](decisions.md) |
| T02 | **closed** | Runnable green baseline verified on `0beace7`: 205 Django tests (PostgreSQL 17), 4 Vitest files / 13 tests, ruff/pyright/check/migrations/tsc/eslint/vite build clean. | T00 | Executor | [baseline.md](baseline.md), [changes.md](changes.md) |
| T03 | **planned** | Endpoint inventory synced in [contracts.md](../api/contracts.md); establish reproducible OpenAPI generation (`drf-spectacular` → `docs/api/openapi.yaml`) and contract examples. | T00, T02; T01 for disputed surfaces | Orchestrator owns semantic decisions; executor owns schema implementation | Current contract identified by revision, generated schema validated, consumers aligned |
| T04 | **in progress** | Core Hybrid A2, frame QC2, structured `ReviewError`, `DailyOutputRecord`, CVAT org/task/job sync & assignee push implemented in `8d66adc`. Remaining: `D03` durable assignee push retry/alerting and `D05`-blocked counting (`CL02`/`CL05`/`CL11`, `S0`, manual `object_count` lock). | Affected T01 decisions and affected T03 contracts | Executor | Focused diff, regression tests, migrations when needed |
| T05 | **in progress** *(partial)* | Migrated ALL 13 remaining `antd` files (`main.tsx`, `StateView`, `useAction`, `ProjectSwitcher`, `MemberSelect`, `CvatSyncButton`, `JobStatusTag`, `AssigneeSelect`, `AssignModal`, `JobDetailDrawer`, `QueuePage`, `JobsPage`, `AuditsPage`) to React Aria (`react-aria-components`) / Untitled UI + shared `ToastProvider`/`Slideover`; uninstalled `antd` & `@ant-design/icons` (`vite build` 513ms, 37/37 Headless Chrome checks with 0 console errors). Remaining: FE↔BE parity screens (Project Settings, Activity Log, Org create/edit, `ReviewError` display gaps) + real CVAT browser QA (`NT02`). | Stable affected T03 contracts; T04 for integration checks | Executor; separate UI writer only for independent files | [UI checklist](../ui/verification.md) zero remaining `antd` imports (verified), Headless Chrome 37/37 green |
| T06 | **in progress** *(partial)* | `DJANGO_ALLOWED_HOSTS` env parsing (`settings.py:34-41`) and `CvatClient` URL/`CVAT_REQUIRE_HTTPS` transport hardening + CI tests implemented in current workspace; production deployment hardening (`DJANGO_DEBUG=False`, `mail.E001`, `security.W004/W008/W012/W016`, TLS/proxy headers, `pg_dump` backups) remains open. | T00; T01 if write or trust boundaries change | Executor | [Security checks](../operations/security-and-verification.md), `CvatClient` URL/HTTPS unit tests, `manage.py check --deploy` under `DJANGO_DEBUG=False` |
| T07 | **in progress** | `.github/workflows/ci.yml` updated with `npm test` (`.github/workflows/ci.yml:88-89`); run full backend + frontend CI-parity gates across workspace changes and verify live browser flows. | Affected T04/T05/T06 work and any included T08 implementation | Executor runs; orchestrator reviews | Exact commands/results tied to final revision and environment |
| T08 | **planned** *(conditional)* | Implement justified telemetry/webhook/API extension only after settling `D04`/`D06` (and `D05` if counts change). | Accepted D04 and D06 via T01; D05 if counts/attribution change; affected T03 contracts; stable core workflow | Orchestrator scopes; executor implements | Accepted contract, authorization, replay/idempotency behavior, integration evidence |
| T09 | **planned** | Close milestone and hand over next bounded task. | Required scope passes T07 on final revision | Orchestrator | Updated current docs, change entry, disclosed out-of-scope work |

T08 is not a prerequisite for releasing the core refactor unless an accepted product requirement makes it one. Avoid introducing a queue, broker, new service, or new database simply to satisfy a proposed diagram.

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

## 6. Conditional telemetry and API work

T08 starts with a capability check against the deployed CVAT version and accepted architecture. Compare supported API/export ingestion, an explicit extension hosted with CVAT, and an external API gateway only when a real gap remains.

The current reference specification says no CVAT fork/patch. A native CVAT extension therefore needs that architecture decision updated before it becomes the chosen implementation. Direct CVAT PostgreSQL/NAS access remains outside the stated boundary; direct ClickHouse access is not implicitly authorized by this plan.

Keep best-effort activity signals separate from immutable QC snapshots and business audit records. Publish metric provenance and missing-data states; do not present elapsed workflow time as measured active time.

## 7. Definition of completion

A milestone is complete when its accepted scope is implemented, its affected contract and UI agree, applicable required gates pass on the final integrated revision, and relevant documentation reflects the result. A documented exception counts only when the existing repository policy permits it. Keep implemented work with failed, blocked, or unrun required gates open and report that verification status. An unfinished optional telemetry task does not block unrelated core work when it is outside the accepted milestone scope.

For schema changes, include migration/roll-forward evidence and distinguish database rollback from code rollback. For remote writes, explain any persistent external effects. Do not imply that reverting a commit reverses invitations, assignments, notifications, or data migrations.

## 8. Active handoff

| Field | Current value (`0beace7`) |
| --- | --- |
| Task | Next bounded slices after completing Ant Design 6 removal (all 13 files migrated to React Aria / Untitled UI, `antd` uninstalled, 37/37 Headless Chrome pass): (1) `D05` resolution & slice for frame-level `CL02`/`CL05`/`CL11` + pre-label `S0` / manual `object_count` lock, (2) `T03` OpenAPI contract generation (`drf-spectacular` → `docs/api/openapi.yaml`), (3) remaining FE↔BE parity UI screens (Project Settings, Activity Log, `Qc1ReviewPanel`/`AnnotatorJobDrawer` `is_voided` & structured chips), (4) `T06` production deploy/TLS settings. |
| Worktree / revision | `/media/bang/Work/projects/vanohub`, branch `feature/issue-logger`, HEAD `0beace78eebc8d2bfac3db06ca203f2e6ac35819` (`0beace7`) |
| Files owned | Reconciled `docs/refactoring/*`, `docs/api/contracts.md`, `docs/ui/verification.md`, `docs/operations/security-and-verification.md`, synced product/rule docs, `T06`/`T07` backend/CI hardening, and full React Aria / Untitled UI migration (`antd` uninstalled); assign single-writer ownership per next slice |
| Established evidence | [baseline.md](baseline.md), [decisions.md](decisions.md) (`D01`–`D03` accepted; `D04`–`D06` open), [contracts.md](../api/contracts.md), [ui/verification.md](../ui/verification.md), [security-and-verification.md](../operations/security-and-verification.md), [changes.md](changes.md) |
| Checks / outcomes | Backend: `ruff check ../backend` (0), `pyright -p ../pyproject.toml` (0), `manage.py check` (0), `makemigrations --check --dry-run` (0), `manage.py test --noinput` (`208/208` OK in `198.134s` on PostgreSQL 17). Frontend: `0` `antd` refs, `tsc -b --noEmit` (0), `npm run lint` (0), `npm test` (`4` files / `13` tests OK), `npm run build` (`vite build` `513ms`, zero AntD chunks), and Headless Chrome CDP multi-role suite (`37/37` passed, `0` console/JS/unexpected HTTP errors). `manage.py check --deploy` shows 6 expected `DJANGO_DEBUG=True` items. |
| Next action / blocker | Settle `D05` product rules before modifying `CL02`/`CL05`/`CL11`, `S0`, or `submit` `object_count`; execute `T03` OpenAPI setup or FE↔BE parity screens independently. |

Replace this handoff when the active task changes. Preserve only durable outcomes in the change log.
