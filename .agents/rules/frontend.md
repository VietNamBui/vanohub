---
trigger: glob
globs: "**/frontend/**/*.ts, **/frontend/**/*.tsx, **/frontend/eslint.config.js, **/frontend/package.json"
description: "Frontend rules for React 19, TypeScript 6, capability parity, apiClient, hooks, and module boundaries."
---

# Frontend Engineering Rules (React / TypeScript / Vite)

- **Backend contract parity:**
  - Keep `frontend/src/shared/types/capabilities.ts` strictly synchronized with `backend/accounts/permissions.py:Cap`.
  - Keep `frontend/src/shared/types/roles.ts` strictly synchronized with `backend/accounts/models.py:Role` and `GRANTABLE_ROLES`.
  - Wrap every project route in `frontend/src/app/router.tsx` with `RequireCap` matching backend capabilities. Treat frontend guards as UX only; backend permissions remain authoritative.
- **HTTP & async hooks:**
  - Send all API requests through `frontend/src/shared/api/client.ts` (`apiClient`) to preserve Bearer token injection and single-flight `401` token refresh. Never call raw `axios` except inside `refreshAccessToken()`.
  - Use `useRequest` (`shared/hooks/useRequest.ts`) for reads, `useAction` (`shared/hooks/useAction.ts`) for mutations, and `getErrorMessage` (`shared/api/errors.ts`) so Vietnamese domain errors from DRF surface verbatim.
- **React 19 state hygiene:**
  - Never reset local state inside `useEffect` when entity IDs or props change; render a keyed subcomponent (`key={...}`) or compute derived state during render.
  - Keep `npx tsc -b --noEmit`, `npm run lint`, and `npm run build` completely clean.
- **Directory boundaries:**
  - Keep `frontend/src/components/` reserved for CLI-copied Untitled UI primitives (imported via `@/components/...`); do not embed VanoHub business logic there.
  - Place feature pages, drawers, and API wrappers under `frontend/src/features/<domain>/`, and shared cross-feature utilities under `frontend/src/shared/`.
- **Environment & copy:**
  - Never place secrets in `VITE_*` variables (`frontend/.env.example`); all `VITE_*` values are bundled into browser assets.
  - Keep user-facing UI labels, empty/error states, and status badges in Vietnamese consistent with `docs/platform-spec.md`.
