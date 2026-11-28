# Analytics, ClickHouse, Vector & Grafana Architecture and Security Audit

## 1. End-to-End Architecture (`cvat-base`)

When `CVAT_ANALYTICS=1` is enabled, CVAT runs a three-service observability pipeline alongside Django (`cvat_server`) and RQ workers (`cvat_worker_*`):

```
[Browser / UI] ──POST /api/events──► [CVAT Server (uvicorn) / RQ Workers]
                                            │
                       vlogger (HttpTransport + SQLite buffer: events_NNN.db)
                                            │
                                            ▼
                                   [Vector (:8282)]
                                            │
                                  HTTP Basic Auth (:8123)
                                            │
                                            ▼
                                 [ClickHouse (cvat.events)]
                                     ▲                ▲
            clickhouse_connect (:8123)                │ grafana-clickhouse-datasource (:8123)
                                     │                │
                        [cvat_worker_export]     [Grafana (:3000)]
                     (POST /api/events/export)        ▲
                                                      │ Traefik (/analytics)
                                                      ├─► ForwardAuth ──► cvat_server/analytics (OPA check)
```

### 1.1. Event Producer (`vlogger` → Vector `:8282`)
- **Logger definition**: `vlogger = logging.getLogger("vector")` (`cvat/apps/engine/log.py`).
- **Handler configuration** (`cvat/settings/base.py`):
  - **In `uvicorn` web workers (`supervisord/server.conf`)**: Uses `logstash_async.handler.AsynchronousLogstashHandler` with `HttpTransport` pointing to `DJANGO_LOG_SERVER_HOST:DJANGO_LOG_SERVER_PORT` (`vector:8282`). Each worker shards its SQLite buffer file via `CVAT_EVENTS_LOCAL_DB_FILENAME="events_%(process_num)03d.db"` under `/home/django/events/` to avoid cross-process SQLite lock contention, flushing queued batches every `2.0` seconds.
  - **In `rqworker` / `rqscheduler` (`supervisord/worker*.conf`)**: Overrides `VECTOR_EVENT_HANDLER="SynchronousLogstashHandler"` because `os.fork()` in RQ workers breaks background flush threads and inherited SQLite file descriptors. Events from RQ workers are sent via synchronous HTTP `POST` directly to `http://vector:8282`.
- **Transactional deferral in `cvat-base`**: `record_server_event(..., on_commit=True)` in `cvat/apps/events/event.py` uses `transaction.on_commit(lambda: vlogger.info(rendered_data), robust=True)` so rolled-back PostgreSQL transactions do not emit phantom events.

### 1.2. Ingestion Router (`cvat_vector`)
- Configured in `components/analytics/vector/vector.toml`:
  - **`[sources.http-events]`**: Unauthenticated `http_server` listening on `0.0.0.0:8282` (`encoding = "json"`).
  - **`[sinks.clickhouse]`**: Batches and forwards events to `http://${CLICKHOUSE_HOST}:${CLICKHOUSE_PORT}` (`table = "events"`, `database = "${CLICKHOUSE_DB}"`).
  - **`encoding.only_fields`**: Explicitly whitelists the 19 columns of `cvat.events` (`scope`, `obj_name`, `obj_id`, `obj_val`, `source`, `timestamp`, `count`, `duration`, `project_id`, `task_id`, `job_id`, `user_id`, `user_name`, `user_email`, `org_id`, `org_slug`, `payload`, `access_token_id`, `remote_addr`), stripping Logstash/Vector envelope metadata (`@timestamp`, `host`, `source_type`).

### 1.3. OLAP Storage (`cvat_clickhouse`)
- Initialized on every `cvat_server` container start via `backend_entrypoint.sh` → `components/analytics/clickhouse/init.py`.
- Single `MergeTree` table `cvat.events`, partitioned by `toYYYYMM(timestamp)` and ordered by `(timestamp)`.
- Read directly via `clickhouse_connect` by:
  - `cvat/apps/events/export.py` (`POST /api/events/export` CSV download on `cvat_worker_export`).
  - `cvat-di-ext/backend/cvat_ext/qc_analytics.py` (`GET /api/server/qc-activity-analytics`).

### 1.4. Visualization & Proxy Auth (`cvat_grafana` + Traefik + OPA)
- `cvat_grafana` provisions `grafana-clickhouse-datasource` and loads `all_events.json`, `management.json`, and `monitoring.json`.
- Traefik (`components/analytics/grafana_conf.yml`) intercepts `PathPrefix(/analytics)`, runs `ForwardAuth` against `http://cvat_server:8080/analytics` (`LogViewerAccessViewSet`), strips `/analytics`, and proxies to `grafana:3000`.

---

## 2. Security & Transactional Gaps Identified

### 2.1. Upstream `cvat-base` Gaps (Introduced around PR #8509 / v2.21.2)
1. **Global Unscoped Access via `/analytics` (`has_analytics_access`)**:
   - In PR #8509, upstream replaced `utils.is_admin` in `cvat/apps/log_viewer/rules/analytics.rego` with `input.auth.user.has_analytics_access`.
   - However, `cvat_grafana` runs with `GF_AUTH_ANONYMOUS_ENABLED: true` and `GF_AUTH_ANONYMOUS_ORG_ROLE: Admin` using a single global ClickHouse database user.
   - Any user with `profile.has_analytics_access = True` who opens `https://<host>/analytics/` gets **full Grafana Admin** permissions across **all users, all tasks, and all organizations**, including raw SQL query access via Grafana Explore.
2. **One-Way Signal Ratchet on User Demotion (`cvat/apps/engine/signals.py`)**:
   - `__save_user_handler` and `__m2m_user_groups_change_handler` set `profile.has_analytics_access = True` when a user is an admin/superuser, but **never reset it to `False`** when admin privileges are removed (e.g., when an account is demoted or repurposed as an annotator).
3. **OPA Rule Mismatch in `cvat/apps/events/rules/events.rego`**:
   - `allow` permits `DUMP_EVENTS` for `utils.has_perm(utils.WORKER)`, but the organization `filter` branch checks `utils.has_perm(utils.USER)`, leaving organization workers unmatched by the filter rule.
4. **Unconditional "View analytics" UI Links**:
   - `cvat-ui` renders `View analytics` (`/projects/:pid/analytics`, `/tasks/:tid/analytics`, `/tasks/:tid/jobs/:jid/analytics`) in Project, Task, and Job action menus for all users regardless of role.

### 2.2. `cvat-di-ext` Gaps
1. **Non-Transactional `append_qc_event` (`backend/cvat_ext/qc_event_log.py`)**:
   - `append_qc_event` writes immediately to `<DATA_ROOT>/cvat_ext/logs/job_<id>/qc_events.jsonl` and calls `_forward_to_analytics` (`vlogger.info`) without `transaction.on_commit`. If an enclosing `transaction.atomic()` block rolls back, phantom events remain in JSONL and ClickHouse.
2. **Client-Spoofable L2 Escalation (`backend/cvat_ext/issue_gate.py`)**:
   - `JobQcEventsView.post` prefixes client-submitted event types with `client_`, but `is_job_selected_for_l2_qc` checks `params.get("action") == "escalate_l2"` without excluding `client_*` events.
3. **Unrestricted `/qc-dashboard` Route**:
   - `HeaderQcNavItem` hides the navbar button for annotators, but the `/qc-dashboard` React route and `GET /api/server/qc-dashboard-summary` allow annotators to view QC reviewer roster identities and sampling policies.

### 2.3. `cvat-dashboard` (`ecvat-dashboard`) Staged Changes Hardening
To eliminate non-transactional drift and unauthorized access in `cvat-dashboard`, the staged workflow & `QcEvent` implementation enforces:
1. **ACID Transactional `QcEvent` Ledger (`dashboard/qc_events.py`, `dashboard/workflow_service.py`)**:
   - Replaces fire-and-forget JSONL/ClickHouse writes with `QcEvent` persisted inside `transaction.atomic()` using `select_for_update()` row locking.
   - Idempotent ingestion via `idempotency_key` (and deterministic SHA-256 `bf_<hash>` keys for JSONL backfills).
   - Stage transitions, defect mutations, and daily KPI credits commit atomically with the event or roll back together.
2. **HMAC Header Compatibility & Webhook Idempotency (`dashboard/views.py`, `dashboard/workflow_views.py`)**:
   - Accepts both `X-Signature-256` and `X-CVAT-Signature-256` (matching `cvat-di-ext`'s `sign_payload_hmac`), and deduplicates `StageTransition` rows by `event_id` (`X-CVAT-Delivery` / `payload["event_id"]`) with `IntegrityError` handling.
3. **Strict Role-Based Access Control (RBAC) Across All Views (`dashboard/workflow_views.py`, `dashboard/views.py`, `dashboard/workflow_service.py`)**:
   - **No Admin/PM Fallback**: Unmapped authenticated users are provisioned with least-privilege `annotator` role (never falling back to an existing `pm` or `admin` profile).
   - **Role Enforcement on Mutations**:
     - `assign_job`, `reassign_job`, `start_qc1`, `qc1_pass`, `qc1_return`: Require QC1 / Lead / PM / Admin (annotators cannot self-assign or pass/return QC1).
     - `start_qc2`, `qc2_pass`, `qc2_return_to_qc1`, `qc2_return_to_anno`, `create_audit`, `audit_job_pass`, `audit_job_return`, `close_audit`: Require QC2 / Audit permission (`pm`, `admin`, `lead`, or `is_qc` in a `can_qa` team).
     - `distribute_jobs`, `reassign_batch`, `release_batch`, `set_auto_lock`, `mark_delivered`, `create_team`, `update_team`, `delete_team`, `add_team_member`, `remove_team_member`, `update_user`, `update_data_type`: Require `pm` or `admin` (or team `lead` for team member management).
   - **Analytics & Scorecard Scoping**:
     - Annotators cannot access global anti-gaming red flags (`QualityScorecardView`), global delivery batch mutations (`DeliveryBatchViewSet`), or raw event backfills (`QcEventsBackfillView`), and only see their own scoped metrics/events.
