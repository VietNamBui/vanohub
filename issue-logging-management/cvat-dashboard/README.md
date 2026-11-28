# CVAT Internal QA/QC Data Cycle Dashboard

Standalone internal QA/QC operations dashboard built on the same tech stack as CVAT (**Django + DRF + PostgreSQL/SQLite + ClickHouse + React + TypeScript + Ant Design**).

Designed to keep **CVAT completely hidden from customers/external viewers** while solving full-lifecycle visibility across:
`Job -> Annotation -> QC1 -> QC2 -> Deliver`

## Key Capabilities
- **Data Cycle Funnel & Bottleneck**: Live WIP per stage, Avg/P95 stage lead time, SLA breach alerts, and `QC1 -> Annotation` / `QC2 -> QC1` rework loops.
- **Daily Output & Productivity**: Per-day, per-user, per-role throughput (jobs submitted/accepted/returned, frames/cuboids, working hours, items/hour) via ClickHouse + webhook transitions.
- **QA/QC Accuracy & Red-Flag Scorecard**:
  - QA/QC reviewers: `Precision = TP/(TP+FP)` with Wilson 95% CI, `L1 -> L2 Escape Rate`, `Made Worse`, `Reviewer Drift`, `Ruling Agreement`, `Sampling Compliance`.
  - Annotators & anti-gaming red flags:
    1. Low touch / low effort (`source_box_touch_rate`, `effort_score`, `rubber_stamping`)
    2. Missing attributes / occlusion edits (`attr_edit_rate`, `CLS-ATTR`)
    3. Unfixed issues / rubber-stamping (`rubber_stamp_suspect`, `qa_override_rate`, `reopen_rate`)
    4. S0 pre-label deletion anti-gaming (`s0_deleted_count`, `suspicious_deletion_count`)
    5. Track ID switches (`track_continuity_ratio`, `track_id_switch_count`)
- **Defect Pareto & Root Cause**: `E1`–`E6` Pareto distribution, Wilson 95% CI upper bound, root-cause breakdown (metadata-only, zero CVAT links).
- **Deliver Gate & Batches**: Bundle `completed` jobs into delivery batches with automated quality gate verification and manifest export.

## Quick Start (Local Dev)

### 1. Backend
```bash
cd backend
python3 manage.py migrate
python3 manage.py seed_demo_data
python3 manage.py runserver 0.0.0.0:8010
```
Demo login created by `seed_demo_data`: `qa_manager` / `dashboard123` (staff) and `qc_lead` / `dashboard123`.

### 2. Frontend Build
If working alongside `../cvat-base`, you can link `frontend/node_modules -> ../../cvat-base/node_modules` (or run `npm install` in `frontend/`):
```bash
cd frontend
ln -s ../../cvat-base/node_modules node_modules
npm run build
```
Then open `http://localhost:8010/`.

### 3. Tests
```bash
cd backend
python3 manage.py test dashboard --no-input
```

### 4. Sync from Private CVAT Instance
Configure `.env` (or environment variables):
- `CVAT_BASE_URL=http://cvat-server.internal:8080`
- `CVAT_SERVICE_TOKEN=<staff_api_token>`
- `CVAT_WEBHOOK_SECRET=<hmac_secret>`
- Optional ClickHouse: `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_DB`, `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`

Run initial pull:
```bash
python3 manage.py sync_cvat --days=30
```
And configure outbound webhook `stage.*` in CVAT (`cvat_ext`) pointing to `http://<dashboard-internal-host>/api/webhooks/cvat-stage/` with the same HMAC secret.
