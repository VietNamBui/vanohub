# Implementation Plan: Fold `feature/issue-logging-management` into `vanohub` (`feature/annotator-qclv1`)

Prepared: 2026-11-28, Asia/Ho_Chi_Minh.  
Target branch: `feature/annotator-qclv1` (HEAD `3fb6b6f`).  
Reference snapshot: [`issue-logging-management/`](../../issue-logging-management/README.md) (`cvat-dashboard` @ `6091115`; any external CVAT extension stays strictly outside and decoupled from VanoHub).

---

## 1. Authoritative Boundary & What NOT to Port

`vanohub` (`feature/annotator-qclv1`) remains the sole workflow, RBAC, and quality SSoT, consuming **stock CVAT REST APIs only** (`PV04`). Never import the broken workflow transitions, role tiers, CVAT-side monkey-patches, or UI stack from legacy `issue-logging-management` branches:

| Pattern in `issue-logging-management` | Source Reference | Why Rejected in `vanohub` |
| --- | --- | --- |
| **`qc1_pass` skips `qc1_passed` straight to `qc2_pending`** | [`cvat-dashboard/backend/dashboard/workflow_service.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/workflow_service.py#L817-L827), [`qc_events.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/qc_events.py#L430-L444) | Breaks Hybrid A2 Task readiness (`confirm-qc2`); `vanohub` holds jobs at `qc1_passed` until 100% of Task jobs pass QC1 (unless `batch.qc2_confirmed_at` is already set). |
| **`recall_from_annotator` & `state=="completed"` skip `L1_QC`** | [`sync_cvat.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/management/commands/sync_cvat.py#L109-L111) | Allows raw CVAT `completed` state or bypass paths to skip QC1 completely. `vanohub` enforces [`SYNCABLE_STATUSES`](../../backend/cvat_integration/sync.py#L72-L78). |
| **Job-level QC2 skipping (`50%` or `100/30/10%` staircase)** | [`workflow_service.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/workflow_service.py#L37) | Contradicts `D02` frame-level QC2 on 100% of jobs ([`backend/quality/qc2.py`](../../backend/quality/qc2.py)). |
| **Redundant `DEPT_HEAD` & `verify_gate` PM layers** | [`cvat-dashboard/backend/dashboard/models.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/models.py#L45-L51), [`views.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/views.py#L568-L610) | Adds extra post-QC2 approval layers (`L2_QC -> DEPT_HEAD -> verify_gate -> DELIVERED`). `vanohub` keeps flat 4-role flow (`QC2 Pass -> APPROVED -> Delivery`). |
| **`Admin` / `Team Lead` tiers, `X-Workflow-User`, `release_batch`** | [`workflow_service.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/workflow_service.py#L62-L113), [`workflow_views.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/workflow_views.py#L123-L140), [`release_batch`](../../issue-logging-management/cvat-dashboard/backend/dashboard/workflow_service.py#L1111-L1132) | Violates flat 4-role RBAC (`PM -> QC2`, `QC1`, `Annotator`), `404` project isolation, four-eyes history, and non-destructive job auditability. |
| **Direct ClickHouse reads from VanoHub & `antd` / `mock/store`** | [`clickhouse_client.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/clickhouse_client.py), [`frontend/CONTRACTS.md`](../../issue-logging-management/cvat-dashboard/frontend/CONTRACTS.md) | Violates `D04` API-only boundary and `T05` Untitled UI / React Aria stack (`antd` is removed in `vanohub`). |

---

## 2. Source-to-Target Fold Map

| Capability to Fold | Reference Source | Target in `vanohub` |
| --- | --- | --- |
| **3D/2D Modality Profiles & `E1`–`E6` Taxonomy** | [`modalities.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/modalities.py), [`metrics.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/metrics.py), [`DefectParetoView`](../../issue-logging-management/cvat-dashboard/backend/dashboard/views.py#L458-L534) | `backend/projects/models.py` (`Dataset` modality), `backend/quality/` (`ErrorCategory`, `ReviewError`), `backend/analytics/views.py` |
| **Pure 3D Geometry, `S0` Baseline & Anti-Gaming Red Flags** | `cvat-dashboard` [`JobQualitySnapshot`](../../issue-logging-management/cvat-dashboard/backend/dashboard/models.py#L194-L259) + [`QualityScorecardView`](../../issue-logging-management/cvat-dashboard/backend/dashboard/views.py#L350-L455) | `backend/cvat_integration/` (`S0` capture + VanoHub-native 3D geometry diff over stock CVAT annotation payloads), `backend/quality/` (`JobQualitySnapshot`, frame `checked_object_count`), `backend/analytics/views.py` (`QualityScorecardView`) |
| **Transactional Event Ledger (`D04` Stock Export Ingestion)** | [`qc_events.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/qc_events.py), [`WebhookCvatStageView`](../../issue-logging-management/cvat-dashboard/backend/dashboard/views.py#L751-L908) | `backend/cvat_integration/` (`CvatSyncScope`, `CvatExportBatch`, `CvatEventLedger`, `CvatWorkingTimeEvent`, `CvatEventQuarantine`, `ingest_cvat_events`, optional HMAC sync trigger) |
| **Funnel WIP, P50/P95 Lead Times, SLA & Batch ETA Forecast** | [`DataCycleFunnelView`](../../issue-logging-management/cvat-dashboard/backend/dashboard/views.py#L121-L253), [`deadline.ts`](../../issue-logging-management/cvat-dashboard/frontend/src/mock/deadline.ts#L126-L160), [`DriftListPage.tsx`](../../issue-logging-management/cvat-dashboard/frontend/src/pages/pm/config/DriftListPage.tsx) | `backend/analytics/views.py` (`DataCycleFunnelView`), `backend/projects/` (`Batch.priority`, `BatchSerializer` forecast, `Delivery` manifest/reopen) |
| **Untitled UI Analytics & Operations Screens** | `cvat-dashboard/frontend/src/pages/` (`DataStatisticPage`, `ProjectOverviewPage`, `DriftListPage`, `DataTypeConfigPage`) | `frontend/src/features/{analytics,projects,quality,jobs}/` (React 19 + Untitled UI / React Aria + Tailwind CSS 4) |

---

## 3. Phased Implementation Plan

### Phase 0 — Spec & Gate Alignment (`D04`, `D05`, `D06`, `PV04`)

1. Preserve `PV04` in [`docs/platform-spec.md`](../platform-spec.md) (**stock `cvat-base` only; no CVAT fork, patch, or in-process extension owned by VanoHub**) per updated `D04` in [`decisions.md`](./decisions.md).
2. Sign off `D05`/`D06` defaults in [`decisions.md`](./decisions.md):
   - `AuditSample.checked_object_count` computed strictly over `AuditSample.frames` (`CL02`/`CL05`/`CL11`),
   - `S0` pre-label baseline captured once before `ANNOTATING`,
   - `NS04` reviewer/annotator speed backed by stock `send:working_time` with explicit `"unavailable"` fallback,
   - Untrusted external client telemetry strictly banned from KPI credits and workflow transitions.
3. Confirm whether Task-level `confirm-qc2` remains as the single PM handoff gate (`D02`) or auto-advances when 100% of Task jobs reach `qc1_passed`.

---

### Phase 1 — Modality Profiles, `E1`–`E6` Taxonomy & Defect Pareto (`projects`, `quality`, `analytics`)

- **Backend models & migrations:**
  - Add `dimension` (`"3d"` | `"2d"`, default `"3d"`) and `annotation_type` (`"cuboid"`, `"bbox"`, etc.) on `Dataset` ([`backend/projects/models.py`](../../backend/projects/models.py)), populated automatically during `sync_organization` when CVAT exposes task/project metadata.
  - Extend `ErrorCategory` ([`backend/quality/models.py`](../../backend/quality/models.py)) with optional `code` (e.g. `E1`–`E6` / sub-code) and `primary_category` (`E1`–`E6`), and add `root_cause` (`CharField(max_length=64, blank=True, default="")`) on `ReviewError` (additive migration, zero breaking change to existing `DEFAULT_ERROR_CATEGORIES`).
- **Analytics & metrics:**
  - Port pure math helpers (`wilson_score_interval`, `percentile`) from [`metrics.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/metrics.py) and modality metadata from [`modalities.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/modalities.py) into `backend/analytics/`.
  - Add `DefectParetoView` (`GET /api/projects/<project_id>/analytics/defect-pareto/`), inheriting `ProjectScopedViewMixin` (`required_capabilities = {"*": Cap.VIEW_DASHBOARD}`, `404` outside membership), aggregating `ReviewError(is_voided=False)` by `primary_category` (`E1`–`E6`), `ErrorCategory`, `root_cause`, and Wilson 95% CI upper bound (`rate_ci_upper`).
- **Tests:** Add Pareto/Wilson CI math tests, `E1`–`E6` filter tests, and `404`/`403` isolation tests in `backend/analytics/tests.py`.

---

### Phase 2 — `S0` Baseline, 3D Geometry Diff & Anti-Gaming Scorecard (`cvat_integration`, `quality`, `analytics`)

- **VanoHub-native 3D geometry & diff engine:**
  - Implement pure-Python/NumPy 3D cuboid diff & continuity helpers directly in `backend/cvat_integration/geometry_3d/` operating over stock CVAT annotation payloads (`GET /api/jobs/{id}/annotations`), with zero vendoring from or coupling to external CVAT extensions.
- **`S0` pre-label baseline & frame-level QC2 denominator (`D05`):**
  - Add `JobBaselineSnapshot` (or JSON/count fields on `Job` / `JobBaseline` keyed `OneToOneField(Job)`): capture `S0` track/box fingerprint & count at first CVAT sync/import while `Job.status == PENDING_ANNOTATION`.
  - Compute and persist `AuditSample.checked_object_count` via existing `CvatClient.count_job_objects(..., included_frames=sample.frames)` (aligning [`quality/qc2.py:pick_frames`](../../backend/quality/qc2.py) for `frame_step` and `deleted_frames`), unblocking `CL02`, `CL05`, and `CL11` from `pending_definition` in [`backend/analytics/views.py`](../../backend/analytics/views.py).
- **Anti-gaming & reviewer quality snapshot:**
  - Add project-scoped `JobQualitySnapshot` (`OneToOneField(Job)` in `backend/quality/models.py`), computed on `submit` / `cvat-sync` / `qc1` / `qc2` transitions (outside DB transaction for CVAT annotation fetches, under `select_for_update()` for DB writes):
    - Annotator anti-gaming signals: `source_box_touch_rate`, `effort_score`, `rubber_stamp_strata_suspect`, `attr_edit_rate`, `attr_missed_count`, `rubber_stamp_suspects`, `qa_override_rate`, `s0_deleted_count`, `suspicious_deletion_count`, `track_continuity_ratio`, `track_id_switch_count`.
    - Reviewer accuracy & drift: `issues_tp`, `issues_fp`, `l1_escape_count`, `made_worse_count`, `mean_center_shift_m`, `mean_abs_yaw_deg`, `mean_dl_m`, `mean_dw_m`, `mean_dh_m`, `drift_warning`, `ruling_agreed_count`, `ruling_disagreed_count`, `geometry_metrics` (`JSONField` for 2D parity).
  - Expose `QualityScorecardView` (`GET /api/projects/<project_id>/analytics/scorecard/`) using `ProjectScopedViewMixin` (`Cap.VIEW_DASHBOARD`), blocking non-PM/non-QC2 callers (`403`) and `404`-isolating across projects.

---

### Phase 3 — Transactional Telemetry Ledger (`D04` Export Ingestion)

- **API-only CVAT export consumer (never direct ClickHouse):**
  - Extend [`CvatClient`](../../backend/cvat_integration/client.py) with a separate `read_only=True` export token (`CVAT_EXPORT_ACCESS_TOKEN`), org-header-free `create_events_export(?org_id=...)`, `get_request_status`, and `CVAT_HOST_HEADER`-safe `stream_download(result_url)` (`allow_redirects=False`).
- **PostgreSQL telemetry models (`backend/cvat_integration/models.py`):**
  - Port the hardened ledger pattern from [`qc_events.py`](../../issue-logging-management/cvat-dashboard/backend/dashboard/qc_events.py): `CvatSyncScope`, `CvatExportBatch`, `CvatEventLedger` (unique `(cvat_instance, event_id)`, nullable `job`/`user` FKs), `CvatWorkingTimeEvent` (`send:working_time`), and `CvatEventQuarantine` (`org_id=null` / foreign-org / malformed rows).
  - Add `manage.py ingest_cvat_events` with `pg_try_advisory_lock`, `create:comment` PII redaction, and hard quarantine: **ingested events never mutate `Job.status`, `ReviewError`, `DailyOutputRecord`, or `ActivityLog` four-eyes history**.
- **Wire `NS04` & optional HMAC webhook:**
  - Feed `CvatWorkingTimeEvent` into `NS04` (`audit_speed` in `Qc1SummaryView` / `Qc2SummaryView`, preserving `"unavailable"` fallback).
  - If real-time push is needed later, port HMAC + `X-CVAT-Timestamp` replay protection from [`WebhookCvatStageView`](../../issue-logging-management/cvat-dashboard/backend/dashboard/views.py#L751-L908) strictly as an enqueue trigger for `sync_organization` / `CvatAssigneeOutbox` — never mutating `Job.status` outside `SYNCABLE_STATUSES`.

---

### Phase 4 — Data Cycle Funnel, Stage Lead Times, SLA Breaches & Batch ETA (`analytics`, `projects`)

- **Funnel & Lead Times (`DataCycleFunnelView`):**
  - Add `GET /api/projects/<project_id>/analytics/funnel/` (`ProjectScopedViewMixin`, `Cap.VIEW_DASHBOARD`) computing over `vanohub`'s 4 real stages (`annotation`, `qc1`, `qc2`, `done` from `STAGE_STATUSES`):
    - Live WIP (`jobs`, `frames`, `object_count`),
    - Avg / P50 / P95 stage lead times derived from `ActivityLog` stage timestamps (`job.status`, `qc1.pass`/`reject`, `qc2.pass`/`reject`),
    - Rework loop counts (`qc1 -> annotation`, `qc2 -> annotation`),
    - Active SLA breach alerts (derived from `Job.deadline` and configurable step buffers).
- **Batch ETA Forecast, Priority & Drift Diagnostic (`projects`):**
  - Port `batchForecast` logic from [`deadline.ts`](../../issue-logging-management/cvat-dashboard/frontend/src/mock/deadline.ts#L126-L160) (`remainingJobs`, 7-day `APPROVED`/`DELIVERED` velocity, `etaAt`, `verdict`: `no_due|done|on_track|at_risk|late`, `daysLate`) onto `BatchSerializer` / `ProjectOverviewView`.
  - Add optional `Batch.priority` (`1..5`, default `3`) + `step_buffer_days` (`JSONField`) if PM scheduling needs per-step deadlines.
  - Add read-only CVAT drift diagnostic (`cvat_stage`/`cvat_state` vs `Job.status` mismatch list in `JobsPage` / `BatchesPage` API) without adding manual fake-resolve toggles.
  - Keep `vanohub` `Delivery` gate unchanged (100% `APPROVED`, 0 locked, 0 pending `AuditSample`), optionally adding JSON manifest export (`GET .../deliveries/<id>/manifest/`) and client-reject reopen (`BG04`) with `Audit` reactivation and `ActivityLog`.

---

### Phase 5 — Frontend Untitled UI Parity (`frontend/src/features/`)

Re-implement only missing capabilities in React 19 + Untitled UI / React Aria + Tailwind CSS 4 (zero `antd`, zero `mock/store.tsx`):

- **`OverviewPage.tsx` & `BatchesPage.tsx`:** Add `BatchForecast` badge/table (`ETA`, `verdict`, `daysLate`), optional `priority` stars (`★1–5`), and stage WIP / P50 / P95 lead-time summary.
- **New `QualityScorecardPage.tsx` & `DefectParetoPage.tsx` (or tabs under `/projects/:projectId/overview` / `/projects/:projectId/audits`):**
  - Guarded by `RequireCap` (`cap="view_dashboard"`),
  - Renders reviewer Wilson 95% CI precision & ruling agreement, `l1_escape_count`, `made_worse_count`, drift metrics, 5 anti-gaming red-flag counters + drilldown table, and `E1`–`E6` Pareto + Wilson CI chart/bars.
- **Data Cycle Funnel & SLA View:** Live 4-stage funnel (`annotation -> qc1 -> qc2 -> done`) + SLA breach alerts + CVAT sync drift table.
- **Modality-aware labels:** Use `Dataset.dimension` (`3D Cuboid` vs `2D Object`) across KPI cards and geometry tooltips.

---

## 4. Verification Gates (Required per Slice)

- **Backend (`backend/`, PostgreSQL 17 running):**
  - `pipenv run ruff check ../backend`
  - `pipenv run pyright -p ../pyproject.toml`
  - `pipenv run python manage.py check`
  - `PIPENV_DONT_LOAD_ENV=1 DJANGO_DEBUG=False DJANGO_ALLOWED_HOSTS=ci.example.com DJANGO_SECURE_SSL_REDIRECT=True pipenv run python manage.py check --deploy`
  - `pipenv run python manage.py makemigrations --check --dry-run`
  - `pipenv run python manage.py test --noinput` (covering workflow isolation, four-eyes, Wilson CI/Pareto math, `S0` anti-gaming, `ingest_cvat_events` quarantine, and `BatchForecast`).
- **Frontend (`frontend/`):**
  - `npm test && npx tsc -b --noEmit && npm run lint && npm run build`
  - Contract parity check (`Cap`, `Role`, `router.tsx` guards) and live multi-role Headless Chrome checks across `PM`, `QC2`, `QC1`, and `Annotator`.
