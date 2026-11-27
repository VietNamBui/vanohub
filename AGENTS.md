# AGENTS.md

Agent operating guide for **VanoHub** (`main`) — a data-annotation operations platform integrating with CVAT.

## Documentation & Customizations

Read relevant specs before changing workflows, permissions, or KPIs:

- [ARCHITECTURE.md](./ARCHITECTURE.md) — system architecture diagram and key entrypoints.
- [docs/platform-spec.md](./docs/platform-spec.md) & [docs/mvp-checklist.md](./docs/mvp-checklist.md) — authoritative Vietnamese functional specification (4-role RBAC matrix, workflows, notification matrix, KPI formulas).
- `.agents/rules/` — modular rules loaded automatically by scope:
  - [.agents/rules/domain-invariants.md](./.agents/rules/domain-invariants.md) (`always_on`) — 4-role RBAC, four-eyes rule, `404` isolation, workflow & CVAT boundaries.
  - [.agents/rules/backend.md](./.agents/rules/backend.md) (`glob` on `backend/**`) — Django/DRF/PostgreSQL locking, 4-layer validation, migrations, tests.
  - [.agents/rules/frontend.md](./.agents/rules/frontend.md) (`glob` on `frontend/**`) — React/TypeScript parity, `apiClient`, data hooks, keyed state resets.
- [.agents/skills/verify-vanohub/SKILL.md](./.agents/skills/verify-vanohub/SKILL.md) (`/verify-vanohub`) — full CI-parity verification & multi-role browser checklist.
- [.agents/agents/spec-auditor.md](./.agents/agents/spec-auditor.md) — read-only subagent for auditing changes against `docs/platform-spec.md` and project invariants.

For the current refactor, use [docs/refactoring/README.md](./docs/refactoring/README.md), [docs/refactoring/plan.md](./docs/refactoring/plan.md), [docs/refactoring/decisions.md](./docs/refactoring/decisions.md), and [docs/refactoring/baseline.md](./docs/refactoring/baseline.md). Follow [docs/refactoring/agent-workflow.md](./docs/refactoring/agent-workflow.md) for compact handoffs and branch-aware retrieval, and record meaningful changes in [docs/refactoring/changes.md](./docs/refactoring/changes.md). Preserve the existing product specification, scoped rules, and verification gates.

## Tech Stack

- **Backend:** Python 3.14 (Pipenv), Django 6, Django REST Framework, SimpleJWT, Pydantic v2, PostgreSQL 17.
- **Frontend:** React 19, TypeScript 6, Vite 8, React Router 8, Tailwind CSS 4, Untitled UI (React Aria), Axios.
- **External integration:** CVAT REST API (`backend/cvat_integration/`).

## Repository Map

- `backend/` — Django project (`config/`) and 7 domain apps:
  - `accounts/` — `User`, `Role`, `RoleAssignment`, `IMPLIED_ROLES`, `Cap`, `ProjectScopedViewMixin`, `HasProjectCapability`, `validated_dict`, `ProjectFixture`.
  - `projects/` — `Project`, `Dataset`, `Batch`, `Delivery`, `Guideline`, `Announcement`, `ActivityLog`, `UserNotification`, `seed_demo`.
  - `teams/` — `Team`, `TeamMember` (capacity, workload, transfers).
  - `jobs/` — `Job` lifecycle, queue, claim/start/submit, `AnnotatorRequest`, quick search.
  - `quality/` — `ErrorCategory`, `Audit`, `AuditSample`, `ReviewError`, frame-level QC2 sampling & historical four-eyes (`qc2.py`), QC1/QC2 review views.
  - `analytics/` — project overview, team ranking, member performance, QC1/QC2/annotator summaries.
  - `cvat_integration/` — `CvatClient`, `CvatAccount` (`/api/cvat/link/`), strict Pydantic v2 contracts (`schemas.py`), org/project/task/job sync (`sync.py`), outbound job assignee push & org invitations (`assignee.py`), and `sync_cvat` management command (`management/commands/sync_cvat.py`).
- `frontend/src/` — React SPA:
  - `app/router.tsx` — capability-guarded route table.
  - `layouts/` — shell (`MainLayout`, notifications, quick search).
  - `features/` — domain modules (`accounts`, `analytics`, `auth`, `cvat`, `jobs`, `projects`, `quality`, `teams`).
  - `shared/` — `api/` (`apiClient`, `errors`, `tokenStorage`), `hooks/` (`useRequest`, `useAction`), `types/` (`capabilities`, `roles`), shared components.
  - `components/` — Untitled UI CLI primitives imported via `@/components/...`.
- `docker-compose.yml` — local PostgreSQL 17 (`:5432`).
- `pyproject.toml` — `pyright` and `ruff` configuration.
- `.github/workflows/ci.yml` — authoritative CI checks for `main`.

## Local Development Setup

```bash
# 1. Start PostgreSQL 17
docker compose up -d db

# 2. Configure environment files (once)
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# 3. Backend dependencies, migrations, optional demo seed, server (:8000)
cd backend
pipenv install --dev
pipenv run python manage.py migrate
pipenv run python manage.py seed_demo
pipenv run python manage.py runserver

# 4. Frontend dependencies and dev server (:5173)
cd frontend
npm ci
npm run dev
```

## Verification Gates

Mirror [.github/workflows/ci.yml](./.github/workflows/ci.yml) before concluding any task (or invoke `/verify-vanohub`):

- **Backend (PostgreSQL 17 running):**
  - `backend/`: `pipenv run ruff check . && pipenv run pyright -p ../pyproject.toml` (CI runs `ruff check backend && pyright` from repo root)
  - `backend/`: `pipenv run python manage.py check && pipenv run python manage.py makemigrations --check --dry-run && pipenv run python manage.py test`
- **Frontend (`frontend/`):**
  - `npm test && npx tsc -b --noEmit && npm run lint && npm run build`
- **Live UI (Vitest `npm test` covers unit tests for shared helpers/types only — no component/E2E suite):** When modifying routes, `RequireCap` guards, forms, drawers, or workflow transitions, verify affected views live in a browser across relevant roles (`PM`, `QC2`, `QC1`, `Annotator`).

## Git & Safety Rules

- Keep changes scoped; do not add `# noqa`, `# type: ignore`, or `eslint-disable` without an inline justification.
- Never commit `.env`, secrets, `.vscode/diagnostics*.json`, `dist/`, or cache directories.
- Do not commit, push, or rewrite Git history unless explicitly instructed.
