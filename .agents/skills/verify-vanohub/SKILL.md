---
name: verify-vanohub
description: >-
  Runs VanoHub CI-parity verification gates across backend (Ruff, Pyright,
  Django check, migrations, PostgreSQL tests), frontend (TypeScript, ESLint,
  Vite build), capability/role parity, and live multi-role browser checks. Use
  before finishing backend, frontend, or cross-stack changes.
---

# Verify VanoHub

Run the checks matching the scope of your changes before concluding work.

## 1. Contract Parity Check (Cross-Stack Changes)

When capabilities, roles, or routes changed, verify exact alignment between:

- `backend/accounts/permissions.py` (`Cap`) ↔ `frontend/src/shared/types/capabilities.ts` (`Capability`)
- `backend/accounts/models.py` (`Role`) + `backend/projects/views.py` (`GRANTABLE_ROLES`) ↔ `frontend/src/shared/types/roles.ts`
- `backend/*/views.py` (`required_capabilities`) ↔ `frontend/src/app/router.tsx` (`guarded(...)`)

## 2. Backend Gates (Requires PostgreSQL 17 Running)

Ensure PostgreSQL 17 is up (`docker compose up -d db`), then run from the repository root using the `backend` Pipenv environment:

```bash
cd backend && pipenv run ruff check ../backend && pipenv run pyright .. && pipenv run python manage.py check && pipenv run python manage.py makemigrations --check --dry-run && pipenv run python manage.py test
```

All 5 steps must exit `0` with zero pending migrations and zero test failures.

## 3. Frontend Gates

Run from `frontend/`:

```bash
cd frontend && npx tsc -b --noEmit && npm run lint && npm run build
```

## 4. Live Multi-Role Browser Verification (UI / Workflow Changes)

Because `frontend/src` has no automated component or E2E test suite yet, verify UI or workflow edits against running local dev servers (`:8000` and `:5173`) using the `browser` subagent (`/browser`):

1. Seed demo accounts if needed: `cd backend && pipenv run python manage.py seed_demo`.
2. Exercise affected screens under the relevant roles (`PM`, `QC2`, `QC1`, `Annotator`).
3. Confirm zero uncaught console errors, expected capability gating, and proper `404` / error toast handling.
