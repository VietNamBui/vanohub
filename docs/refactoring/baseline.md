# Evidence baseline

Captured: 2026-11-27, Asia/Ho_Chi_Minh. Repository: [VietNamBui/vanohub](https://github.com/VietNamBui/vanohub).

## 1. Evidence boundaries

This package used the conversation, the attached conversation log, and read-only GitHub inspection. The branch list and selected source files were refreshed during preparation. No connection to the user's active local checkout, deployed CVAT, or local codebase-memory-mcp server was available.

The attached log contains evolving recommendations and some branch attribution errors. Treat it as design history. Use the pinned source below for remote implementation claims, and T00 for current local claims. In particular, do not carry forward a statement that the repository is only a scaffold, that every branch has the latest PM changes, or that a proposed telemetry service already exists.

## 2. Remote revisions

| Branch | Observed HEAD |
| --- | --- |
| `main` | `3e21fa11e9250b28af7a9b75e23b63c54ffe2da5` |
| `feature/project-manager` | `24ca99c728c97d924b97c5a913533cfba36bee3b` |
| `annotator-qclv1` | `25bd5f2f998152c4daf4dcc387063af8e7bade44` |
| `feature/issue-logger` | `99027769c86536807d31808ff666e9a424505aea` |

These are snapshots, not a recommended merge base. No automatic branch merge or application migration is part of this documentation package.

## 3. Observations that affect the plan

| Area | Source observation | Meaning for the refactor | Verification |
| --- | --- | --- | --- |
| Entity mapping | PM sync maps CVAT Organization → Project and CVAT Project → Dataset; issue-logger's specification maps CVAT Project → Project | Resolve D01 before schema, route, or UI naming changes | Source inspected [S2], [S3]; no runtime check |
| QC transition | PM sync maps validation complete/acceptance into `PENDING_QC2`; issue-logger caps those at `QC1_PASSED` and preserves PM confirmation | Resolve D02; do not silently substitute states | Source inspected [S3], [S4] |
| Identity and remote writes | PM branch has linked CVAT account references and code to push assignees and invite organization members | Decide identity migration and allowed write scope; this is not a uniformly GET-only integration | Source inspected [S3], [S5] |
| Scheduling | PM assignee push is registered with `transaction.on_commit` | Running after commit does not by itself provide durable queueing, retries, or worker isolation | Source inspected [S5] |
| Current HTTP surfaces | Issue-logger registers `/api/cvat/status/` and `/api/cvat/tasks/` | Use these as branch-specific observations, not as the whole platform API | Source inspected [S6], [S7] |
| API documentation tooling | Inspected URL configuration has no schema/docs registration; inspected Pipfile has no named schema-generator dependency | T00 must check the local branch before choosing or adding tooling | Source inspected [S6], [S8]; not an exhaustive dependency/runtime audit |
| Product boundary | Reference spec says original CVAT without fork/patch and VanoHub-owned business workflow | Preserve the boundary while resolving proposed extensions explicitly | Spec [S2] |
| Telemetry | Spec marks plugin hooks, telemetry events, ingestion, and webhook endpoints as backlog | Candidate contracts must remain proposals until implemented | Spec [S2], backlog B1–B5 |
| Productivity | NS01/NS03 are provisional; NS04 and NS09 contain unresolved definitions | Preserve provenance and unknown values; telemetry does not automatically settle semantics | Spec [S2], NS rows |
| Existing operating rules | Root instructions link scoped rules and CI gates; UI copy remains Vietnamese | Extend those instructions through links and targeted additions | [S1], [S9] |

The existing `docs/mvp-checklist.md` includes statements about an older commit plus uncommitted local changes, numerical progress estimates, and claimed failures. Those are historical reports. This package does not claim that those failures or percentages describe the present local refactor.

## 4. User requirements and planning defaults

| Item | Classification | Treatment |
| --- | --- | --- |
| Local refactor already underway | User-reported | Resume it; capture local evidence before changing status |
| Most code indexed in codebase-memory-mcp | User-reported | Reuse relevant index results; validate freshness and root |
| Neon Extra High orchestrator / Hydrogen Extra High executor | User-reported configuration | Keep a small two-role workflow; no capability or cost claims |
| Avoid unnecessary token use | User objective | Compact handoffs, narrow retrieval, reuse evidence, no tool-by-tool diary |
| Document refactor, UI, and API changes | Requested deliverable | One logical change record per reviewable unit |
| CVAT API boundary; no direct CVAT PostgreSQL/NAS reads | User constraint from the discussion | Carry into implementation scope |
| API-mediated telemetry as the initial design boundary | Conservative planning default | Resolve D04 before introducing a new data connection or service |

## 5. Local baseline record — T00 (`0beace7`)

| Field | Value |
| --- | --- |
| Repository root / worktree | `/media/bang/Work/projects/vanohub` |
| Branch / HEAD | `feature/issue-logger` @ `0beace78eebc8d2bfac3db06ca203f2e6ac35819` (`0beace7`), after merge `8d66adc` (`annotator-qclv1 @ 6384711` + `feature/project-manager @ 24ca99c`) |
| Relevant staged, unstaged, and untracked changes | Pre-existing staged starter archive (`A`): `VanoHub-Docs-and-Plan-2026-11-27.zip`, `vanohub-docs-starter/*`. Clean baseline `0beace7` (before this T00/T06 workspace pass) had zero unstaged code diff. Current workspace adds: 9 adopted/reconciled docs under `docs/{api,operations,refactoring,ui}/`, synced product/rule docs (`docs/{platform-spec,mvp-checklist,ui-spec-traceability}.md`, `ARCHITECTURE.md`, `AGENTS.md`, `.agents/rules/domain-invariants.md`), `T06` `CvatClient` URL/`CVAT_REQUIRE_HTTPS` hardening (`backend/cvat_integration/{client,tests}.py`, `backend/config/settings.py`, `backend/.env.example`), and `npm test` in `.github/workflows/ci.yml`. |
| Current instruction files and accepted local decisions | `AGENTS.md`, `ARCHITECTURE.md`, `.agents/rules/{domain-invariants,backend,frontend}.md`, `.agents/skills/verify-vanohub/SKILL.md`, `docs/platform-spec.md`, `docs/mvp-checklist.md`. `D01`–`D03` accepted/implemented in `8d66adc`; `D04`–`D06` remain open ([decisions.md](decisions.md)). |
| MCP implementation/version and indexed project/root | `codebase-memory-mcp` project `media-bang-Work-projects-vanohub` (2995 nodes, 11555 edges). |
| Index freshness or revision evidence | Generation `2026-11-27T04:48:39Z` (Verify Tier 2; `check_index_coverage`: `metadata_match` / `no_recorded_issue` on `backend/config/{settings,urls}.py`, `backend/projects/models.py`, `backend/jobs/models.py`, `backend/quality/models.py`, `backend/cvat_integration/{client,sync,assignee,tests}.py`, `backend/analytics/views.py`); claims verified directly against source files on disk. |
| Deployed CVAT version and schema source | Local CVAT stack running (`CVAT_URL` / `CVAT_PUBLIC_URL` in `backend/.env`); exact deployed CVAT schema/version snapshot not yet pinned in docs. |
| Existing OpenAPI artifact and generator | None: `drf-spectacular` is absent from `backend/Pipfile` and `backend/Pipfile.lock`, and no OpenAPI route or artifact exists in `backend/config/urls.py` or `docs/api/`. |
| Current baseline checks and environment | PostgreSQL 17 (`vanohub-db-1`), Python 3.14 (Pipenv), Node 20 / Vite 8 / Vitest 4. Passing on `0beace7`: `cd backend && pipenv run ruff check ../backend`, `cd backend && pipenv run pyright -p ../pyproject.toml` (0 errors/warnings; bare global `pyright` outside Pipenv fails on missing imports), `manage.py check` (0 issues), `manage.py makemigrations --check --dry-run` (No changes detected), `manage.py test` (205 Django tests OK against PostgreSQL 17 in orchestrator baseline; local run discovered `Found 205 test(s)` and exited cleanly without dropping pre-existing `test_vanohub`), `cd frontend && npm test` (4 Vitest files / 13 tests OK), `npx tsc -b --noEmit` (0), `npm run lint` (0), `npm run build` (OK). `manage.py check --deploy` shows 6 expected dev issues (`mail.E001`, `security.W004/W008/W012/W016/W018`) when `DJANGO_DEBUG=True`. `backend/config/settings.py:34-41` already parses `DJANGO_ALLOWED_HOSTS` from environment (`localhost,127.0.0.1` when `DEBUG=True`, empty when `DEBUG=False`). |
| Tasks already completed locally | `T00` (captured/reconciled on `0beace7`), `T01` partial (`D01`–`D03` accepted in `8d66adc`; `D04`–`D06` open), `T02` (green runnable baseline), plus partial `T04`/`T05` via `8d66adc`. Remaining `antd` footprint in `frontend/src`: 13 files (`main.tsx`, `shared/components/StateView.tsx`, `shared/hooks/useAction.ts`, `features/projects/components/ProjectSwitcher.tsx`, `features/projects/components/MemberSelect.tsx`, `features/projects/components/CvatSyncButton.tsx`, `features/quality/qc2/AuditsPage.tsx`, `features/jobs/components/AssignModal.tsx`, `features/jobs/components/AssigneeSelect.tsx`, `features/jobs/components/JobDetailDrawer.tsx`, `features/jobs/components/JobStatusTag.tsx`, `features/jobs/pages/JobsPage.tsx`, `features/jobs/pages/QueuePage.tsx`). |

Preserve Section 2 historical remote snapshots when adding newer local baselines.

## 6. Pinned sources

- [S1: existing AGENTS.md](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/AGENTS.md)
- [S2: platform specification](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/docs/platform-spec.md)
- [S3: PM branch CVAT sync](https://github.com/VietNamBui/vanohub/blob/24ca99c728c97d924b97c5a913533cfba36bee3b/backend/cvat_integration/sync.py)
- [S4: issue-logger CVAT sync](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/backend/cvat_integration/sync.py)
- [S5: PM assignee and invitation behavior](https://github.com/VietNamBui/vanohub/blob/24ca99c728c97d924b97c5a913533cfba36bee3b/backend/cvat_integration/assignee.py)
- [S6: platform URL configuration](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/backend/config/urls.py)
- [S7: CVAT integration URLs](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/backend/cvat_integration/urls.py) and [views](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/backend/cvat_integration/views.py)
- [S8: backend dependency declaration](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/backend/Pipfile)
- [S9: CI workflow](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/.github/workflows/ci.yml), [domain rules](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/.agents/rules/domain-invariants.md), and [frontend rules](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/.agents/rules/frontend.md)
- [S10: historical MVP checklist](https://github.com/VietNamBui/vanohub/blob/99027769c86536807d31808ff666e9a424505aea/docs/mvp-checklist.md)

External implementation references belong near the relevant guidance, such as the [security document](../operations/security-and-verification.md). This source list establishes what was read; it does not certify the application.
