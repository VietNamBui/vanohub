# Transport, integration boundaries, and verification

Prepared: 2026-11-27. This is a proposed operational checklist to reconcile with the real local/deployed topology during T00 and T06. It is not evidence that production settings have been changed.

## 1. Connection policy

| Connection | Production policy | Development / exception |
| --- | --- | --- |
| Browser → VanoHub | HTTPS for authenticated application and admin traffic | Localhost HTTP can remain for development |
| Browser → CVAT | HTTPS for the user-facing CVAT URL | Localhost HTTP can remain for development |
| VanoHub backend → CVAT API | Verified HTTPS across hosts or untrusted/shared network boundaries | Plain HTTP may be an explicit exception on a same-host private network with controlled reachability |
| VanoHub → its own PostgreSQL | Private reachability and least privilege; use TLS with certificate/hostname verification across hosts | Same-host private development setup as configured |
| VanoHub → CVAT telemetry & export APIs | Explicit dedicated `read_only=True` PAT, project/org scope, verified HTTPS across network boundaries, and `allow_redirects=False` | Apply accepted `D04` hybrid boundary (`POST /api/events/export` + `GET /api/requests/{rq_id}` + `result_url`); no direct CVAT DB, ClickHouse, Vector, or NAS connection |
| VanoHub → CVAT PostgreSQL / NAS | Outside the stated integration boundary | No exception introduced by this plan |

Do not automatically equate “internal network” with a trusted transport. Record the endpoints and trust boundary without storing credentials. A same-host HTTP exception must be explicit; an unconditional HTTPS requirement plus an undocumented exception is an inconsistent configuration.

## 2. Django and proxy configuration

For production, evaluate secure cookies, HTTPS redirection, HSTS rollout, allowed hosts, and the actual proxy path. Configure `SECURE_PROXY_SSL_HEADER` only when the trusted proxy strips untrusted incoming values and sets the header correctly. Same-origin admin traffic does not inherently require extra `CSRF_TRUSTED_ORIGINS`; add trusted cross-origin origins only when the deployment needs them. CORS and CSRF serve different purposes.

Reference: [Django settings](https://docs.djangoproject.com/en/6.0/ref/settings/).

Run `manage.py check --deploy` against the intended production settings, and verify the external route for redirect loops, cookie behavior, and host handling. The command supplements deployment inspection; it does not validate the entire proxy/network setup.

Reference: [Django deployment checklist](https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/).

Avoid disabling certificate verification to make HTTPS work. Configure a trusted certificate chain instead. For the CVAT client, validate the configured scheme/host before transmitting credentials and use controlled redirect behavior. Disabling redirects does not prevent credentials being sent to an incorrectly configured original HTTP URL.

### Reconciled `0beace7` configuration & hardening status

- **`ALLOWED_HOSTS` already env-configured:** `backend/config/settings.py:34-41` parses `DJANGO_ALLOWED_HOSTS` from environment (defaulting to `localhost,127.0.0.1` when `DEBUG=True`, and `[]` when `DEBUG=False` — production deployments must set `DJANGO_ALLOWED_HOSTS`).
- **CVAT client transport validation (implemented in workspace post-`0beace7`):** `_validate_base_url()` (`backend/cvat_integration/client.py:41-58,74`) validates `http`/`https` scheme and hostname and rejects embedded URL credentials, query strings, or fragments before session/header initialization; when `CVAT_REQUIRE_HTTPS=True` (`backend/config/settings.py:200`, documented in `backend/.env.example`), non-HTTPS `CVAT_URL` values are rejected. `CvatClient._request()` (`backend/cvat_integration/client.py:107-114`) keeps `allow_redirects=False` and rejects HTTP 3xx responses (tested in `backend/cvat_integration/tests.py:219-258`).
- **Deploy checklist status (`manage.py check --deploy`):** `backend/config/settings.py` now reads `DJANGO_EMAIL_BACKEND` (`smtp.EmailBackend` when `DEBUG=False`, resolving `mail.E001`), `POSTGRES_SSLMODE`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_SECURE_PROXY_SSL_HEADER`, `DJANGO_SECURE_SSL_REDIRECT`, `DJANGO_SECURE_HSTS_SECONDS` (`31536000` when `DEBUG=False`), `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS`, `DJANGO_THROTTLE_ANON`, and `DJANGO_THROTTLE_USER` (all documented in `backend/.env.example`), enforces `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE`, and disables `SessionAuthentication`, `BrowsableAPIRenderer`, and localhost CORS defaults when `DJANGO_DEBUG=False`. Production deployments must provide a strong `DJANGO_SECRET_KEY`, populate `DJANGO_ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS`, set `CVAT_REQUIRE_HTTPS=True`, and run `PIPENV_DONT_LOAD_ENV=1 DJANGO_DEBUG=False DJANGO_ALLOWED_HOSTS=<host> pipenv run python manage.py check --deploy` (or `pipenv run env DJANGO_DEBUG=False ...`, since `pipenv run` loads `backend/.env` with `override=True` while `settings.py` loads `.env` with `override=False`).

## 3. Integration and authorization checks

- Bind every imported/read job to the intended CVAT instance, organization/project, and VanoHub scope.
- Verify project authorization independently of knowing an external object ID or holding a service token.
- Preserve the accepted capability/four-eyes/locked-state rules on backend mutations.
- Set request deadlines and bounded pagination/input sizes; do not introduce a generic arbitrary-query endpoint.
- Redact PATs, Authorization headers, passwords, webhook secrets, and unnecessary annotation payloads from errors/logs.
- Verify remote payloads outside long local transactions; recheck mutable local state while applying changes.
- Specify partial failure and retry outcomes. A durable external-write workflow needs explicit persistence/retry design if required; `on_commit` alone does not supply it.
- For webhook/telemetry work, verify the deployed protocol, signature, scope, deduplication, late delivery, and acknowledgment semantics before enabling it.

### CVAT telemetry & export controls (`cvat-event-pipeline-v2`)

- **Dedicated least-privilege token:** Provision a separate CVAT service account with global privilege `user`, org role `maintainer` or `owner` (not `supervisor`/`worker`, which scope OPA exports to self, and not global `worker`, which triggers an undefined OPA filter in `events.rego`), and a `read_only=True` Bearer PAT. Never reuse VanoHub's write `CVAT_ACCESS_TOKEN` for event exports.
- **Header/query mutual exclusion & origin validation:** Never send `X-Organization` or `org` alongside `?org_id=` on `POST /api/events/export` (CVAT `iam/middleware.py` rejects combinations with HTTP `400`). Validate `result_url` scheme, host/port (accounting for `CVAT_HOST_HEADER` when set), and `/api/...` path before attaching Bearer credentials, keeping `allow_redirects=False` and `CVAT_REQUIRE_HTTPS`.
- **Tenant, PII, and provenance quarantine:** Reject or quarantine `org_id=null` (personal workspaces) and foreign-org rows; enforce `ProjectScopedViewMixin` (`404` isolation) on all VanoHub telemetry read endpoints. Stream-redact `create:comment` `obj_name` (raw message text) and `user_email` prior to persistence. Keep `origin="client"` (`qc:client_*`) quarantined from `SL*`/`KPI*`/`CL*` metrics and workflow/sampling gates.
- **CVAT-side durability & typing:** Require persistent mounts for `/home/django/events` (`EVENTS_LOCAL_DB_FILE`) and `/vector-data-dir` plus Vector disk buffering/acknowledgements, lower `CVAT_EXPORT_CACHE_TTL` (e.g., `3600`) to avoid `cvat_data/cache/export/` bloat, and enforce strict outer ClickHouse types (`UInt32` non-null `duration`, `UInt16` `count`, epoch-seconds `timestamp`) to prevent non-retryable `400` batch drops.

These checks apply to changed boundaries. Do not add a new service, authentication framework, broker, or audit subsystem to a documentation-only task.

## 4. Repository verification gates

The active local [AGENTS.md](../../AGENTS.md), scoped rules, and [CI workflow](../../.github/workflows/ci.yml) remain authoritative:

| Working directory | CI command (`.github/workflows/ci.yml`) | Local Pipenv / CLI command (`0beace7`) | Purpose |
| --- | --- | --- | --- |
| `backend/` (CI: repo root) | `ruff check backend` | `cd backend && pipenv run ruff check ../backend` | Backend lint |
| `backend/` (CI: repo root) | `pyright` | `cd backend && pipenv run pyright -p ../pyproject.toml` | Static typing *(bare global `pyright` outside Pipenv fails with missing imports)* |
| `backend/` | `python manage.py check` | `cd backend && pipenv run python manage.py check` | Django system checks |
| `backend/` | `python manage.py makemigrations --check --dry-run` | `cd backend && pipenv run python manage.py makemigrations --check --dry-run` | Missing migrations |
| `backend/` | `python manage.py test` | `cd backend && pipenv run python manage.py test` | Backend tests with PostgreSQL 17 |
| `frontend/` | `npx tsc -b --noEmit` | `cd frontend && npx tsc -b --noEmit` | Type checking |
| `frontend/` | `npm run lint` | `cd frontend && npm run lint` | Frontend lint |
| `frontend/` | `npm test` | `cd frontend && npm test` | Vitest unit tests (4 files / 13 tests, added at `.github/workflows/ci.yml:88-89`) |
| `frontend/` | `npm run build` | `cd frontend && npm run build` | Production build |

Use the project's Pipenv environment locally when tools are not installed globally. Do not treat `manage.py check --deploy` under `DJANGO_DEBUG=True` as a production sign-off.

Run targeted checks during the edit loop, then the gates required by the existing instructions at task completion. Do not use a graph-selected test subset to silently bypass a required gate. If a check cannot run, record that limitation and its impact.

## 5. Risk-focused scenarios

Choose scenarios based on the changed behavior:

| Change | Useful evidence |
| --- | --- |
| Structural backend refactor | Representative behavior parity, imports, focused regression tests, relevant required gates |
| Hierarchy/identity migration | Data mapping fixtures, duplicate/unknown ID cases, permissions after migration, rollback or roll-forward limits |
| Workflow/locking | Concurrent claims/confirmation, four-eyes cases, protected state, retry after stale reads; PostgreSQL behavior |
| Counting/pre-label logic | Outside intervals, sparse tracks, frame step, empty vs missing frame filters, deleted frames, baseline absence, reassignment/rework |
| API contract | Schema validity, actual examples/errors, authorization, null/enum/unit handling, consumer compatibility |
| UI | Relevant role/state browser checks, keyboard/forms, stale/error behavior, actual contract parity |
| Telemetry/webhook | Duplicate/reordered/late events, invalid signatures, cross-project IDs, partial failures, duration units and unknown coverage |
| Deployment transport | Verified certificates, proxy trust, no redirect loop, no cleartext cross-host credential path |

Do not label a count algorithm correct merely because it handles named flags; verify representative payloads from the actual supported CVAT version. Do not substitute SQLite for PostgreSQL locking evidence.

## 6. Evidence and release record

For each required check record: command or scenario, working directory, revision and relevant dirty diff, environment, result, and an artifact/log pointer. Separate pre-existing failures from introduced failures only when the baseline supports that distinction.

Documentation-package checks are limited to document consistency, links, patch applicability, and archive integrity. They do not establish application correctness.

Before a release or migration, record the rollout order, meaningful rollback/roll-forward path, and persistent external effects. Update [changes.md](../refactoring/changes.md), the affected current documents, and [the plan](../refactoring/plan.md). Do not use this checklist to create a new blanket approval gate.
