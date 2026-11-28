# Refactor decisions

Prepared: 2026-11-27 (reconciled 2026-11-28). Status on `feature/annotator-qclv1`: **D01–D04 are accepted** (`D01`–`D03` implemented; `D04` updated 2026-11-28 to strict stock CVAT API-only consumption with `PV04` intact and external CVAT extensions completely decoupled); **D05–D06 remain open** with Dec 4 MVP defaults proposed.

Use this file for the small number of choices that cross data, API, workflow, and UI boundaries. Split an individual record into an ADR only when its size or independent lifecycle warrants it. Link to the product specification rather than duplicating its full rules.

## Decision index

| ID | Decision | Status | Blocks only |
| --- | --- | --- | --- |
| D01 | CVAT hierarchy and tenant identity | Accepted (`8d66adc`) | Related migrations, identifiers, routes, and navigation |
| D02 | QC1-to-QC2 gate and sampling unit | Accepted (`8d66adc`) | Related transition, audit, and review UI changes |
| D03 | Identity linking and CVAT write scope | Accepted with reliability gap (`8d66adc`) | Account migration, assignee push, invitations, unlink behavior |
| D04 | Telemetry source and API extension placement | Accepted (stock CVAT API only; `PV04` intact) | Stock CVAT export ingestion (`T08`); zero CVAT extension dependency |
| D05 | Object counts, baseline snapshots, and output attribution | Open (Dec 4 defaults proposed) | Changes to counting, productivity, quality denominators |
| D06 | Time, provenance, and missing-data semantics | Open (Dec 4 defaults proposed) | New time-based metrics and their UI/API contracts |

## D01 — CVAT hierarchy and tenant identity

**Evidence:** [baseline S2–S4](baseline.md). The PM branch maps CVAT Organization → VanoHub Project and CVAT Project → Dataset. The issue-logger specification maps CVAT Project → VanoHub Project with local Dataset grouping.

**Recommendation:** preserve the active accepted local model during structural refactoring. If organization-based tenancy is the chosen target, treat it as a data and authorization migration with an explicit conversion plan.

Before accepting, record:

- Canonical entity names, external identifiers, uniqueness scope, and tenant boundary.
- Whether organizations, personal workspaces, or multiple CVAT instances are supported.
- Which existing Project/Dataset/Batch rows map to the target; how ambiguous or duplicate external IDs are handled.
- API path/query meanings, authorization implications, and frontend label changes.
- Whether existing links, saved filters, audit references, and deliveries remain valid.

Do not equate changing the UI label “Project” with changing the identity or security scope of the Project model. Do not use one ambiguous `project_id` for both VanoHub and CVAT IDs without a documented boundary.

**Acceptance:** one mapping table in the current product/architecture documentation; affected contracts updated; migration checks and tenant-isolation scenarios identified.

### Resolution (D01)

```text
Status and date: Accepted and implemented in 8d66adc (reconciled 2026-11-27 on 0beace7).
Selected option and reason: Map CVAT Organization -> VanoHub Project (UI: "Organization"), CVAT Project -> Dataset (UI: "Project"), CVAT Task -> Batch (UI: "Task"), and CVAT Job -> Job (UI: "Job"). Preserves existing Django model names and /api/projects/<project_id>/ tenant isolation while matching CVAT's organization hierarchy (personal workspace CVAT projects outside an org are excluded).
Authority/evidence: backend/projects/models.py (Project, Dataset, Batch docstrings), backend/projects/migrations/0007_org_structure_prepare.py, 0008_org_structure_finish.py, 0011_batch_last_sync_error_batch_last_sync_status_and_more.py, backend/jobs/migrations/0004_job_dataset.py-0007_job_batch_required.py, backend/cvat_integration/sync.py, and UI labels in frontend/src/features/projects/.
Affected code, data, API, and UI:
  - Project: cvat_org_id (unique, nullable), cvat_org_slug, cvat_synced_at.
  - Dataset: project FK -> Project, cvat_project_id (unique, nullable, constraint dataset_cvat_project_id_positive), last_synced_at.
  - Batch: project FK -> Project, dataset FK -> Dataset, cvat_task_id (unique, nullable, constraint batch_cvat_task_id_positive), source_missing, last_synced_at, last_sync_status, last_sync_error, qc2_confirmed_by, qc2_confirmed_at.
  - Job: project, dataset, batch FKs (validated in Job.clean()), cvat_job_id (unique, nullable, constraint job_cvat_job_id_positive), cvat_task_id (constraint job_cvat_task_id_positive), cvat_start_frame, cvat_stage, cvat_state, source_missing, cvat_assignee_id.
  - API & UI: POST /api/cvat/sync-organizations/ and POST /api/projects/{id}/cvat-sync/; UI displays Organization -> Project -> Task -> Job while API paths remain /api/projects/{id}/datasets|batches|jobs/.
Migration/compatibility and external effects: Implemented via projects/0007-0011 and jobs/0004-0007; makemigrations --check --dry-run passes clean on 0beace7. Follow-up doc sync needed for older DL01/DL02 wording in docs/platform-spec.md.
Verification required and evidence: Passing 205-test Django suite on PostgreSQL 17 (orchestrator baseline on 0beace7) + makemigrations --check --dry-run (No changes detected); cross-org/foreign project & task checks in backend/cvat_integration/sync.py and tests.py.
Supersedes / superseded by: Supersedes earlier CVAT Project -> VanoHub Project branch mapping (feature/issue-logger pre-8d66adc).
```

## D02 — QC transition and sampling

**Evidence:** [baseline S2–S4](baseline.md). The reference product specification requires QC1 success to become `qc1_passed`, followed by PM confirmation of the eligible batch into QC2. Another branch's sync maps CVAT validation completion/acceptance to `pending_qc2`.

**Recommendation:** retain the current accepted PM confirmation gate unless a product decision explicitly changes it. Resolve sampling separately: job sampling and frame sampling have different populations, denominators, and review UI.

Record the transition table, actor capability, batch preconditions, interaction with locks/escalation, and handling of concurrent sync. Identify the authoritative stage/state separately from CVAT's native stage/state.

**Acceptance:** the backend transition, UI label/action, notifications, audit record, and API response describe the same event. Include tests for ineligible batches, four-eyes conflicts, and sync attempts after QC2/approval/delivery.

### Resolution (D02)

```text
Status and date: Accepted and implemented in 8d66adc (reconciled 2026-11-27 on 0beace7).
Selected option and reason: Hybrid A2 PM gate once per Task (Batch) combined with deterministic frame-level QC2 sampling across every job. First-pass QC1 approval stops at JobStatus.QC1_PASSED while batch.qc2_confirmed_at is null; PM confirms the Task once via confirm-qc2 when 100% of jobs have passed QC1 and none are locked. Post-QC2 rework bypasses confirm-qc2 straight from qc1_pass to PENDING_QC2 to prevent deadlock.
Authority/evidence: backend/quality/views.py (qc1_pass), backend/projects/views.py (BatchViewSet.confirm_qc2, DeliveryViewSet.perform_create), backend/quality/qc2.py (pick_frames, ensure_qc2_sample, pick_auditor, four_eyes_conflicts, get_stage_history), backend/quality/models.py (Audit, AuditSample, migrations quality/0003_qc2_frame_sampling.py, 0004, 0005), backend/cvat_integration/sync.py (SYNCABLE_STATUSES, POST_QC1_CVAT_STATES, _map_cvat_status).
Affected code, data, API, and UI:
  - QC1 -> QC2 gate: qc1_pass sets QC1_PASSED (pre-confirmation) or PENDING_QC2 + ensure_qc2_sample (when batch.qc2_confirmed_at is set). POST /api/projects/{id}/batches/{pk}/confirm-qc2/ locks Batch + Jobs, requires DataStatus.ACTIVE and all jobs in QC2_NON_BLOCKING_STATUSES with 0 locked, transitions QC1_PASSED -> PENDING_QC2, creates AuditSample rows, logs batch.confirm_qc2, notifies QC2/PM, and schedules assignee push.
  - CVAT sync boundary: sync.py updates only SYNCABLE_STATUSES (annotation + qc1) and maps validation/completed + acceptance/* to QC1_PASSED unless batch.qc2_confirmed_at is set; never overwrites PENDING_QC2, APPROVED, or DELIVERED.
  - Frame-level QC2 & read-only Audits: quality/qc2.py deterministically samples project.sampling_rate % frames seeded by f"{job.pk}:{job.rework_round}" (offset by job.cvat_start_frame) and auto-creates Audit (in_progress) + AuditSample (frames, rework_round, auditor via pick_auditor). Project.sampling_method / stratify_by and Audit.method / seed / eligible_* remain legacy columns populated with defaults. AuditViewSet is strictly read-only (no manual create, preview, accept, reject, or partial_reject); AuditSampleViewSet exposes pass/, reject/, and assign/.
  - Delivery closure: DeliveryViewSet.perform_create requires all batch jobs APPROVED, 0 locked, and 0 pending AuditSample rows, transitions jobs + batch to DELIVERED, and closes open Audit rows to Audit.Status.COMPLETED.
  - UI: BatchesPage.tsx (confirmBatchQc2), AuditsPage.tsx (read-only audit progress + auditor assignment), AuditWorkPage.tsx + ReviewPanel.tsx (frame-level QC2 pass/reject), AuditStrategyPage.tsx (sampling_rate display/history).
Migration/compatibility and external effects: Implemented in quality/0003-0005 and projects/0011; confirm-qc2 sends UserNotification and triggers best-effort CVAT assignee push on commit.
Verification required and evidence: Passing 205-test Django suite on PostgreSQL 17 (orchestrator baseline on 0beace7) covering Hybrid A2 confirm-qc2, post-QC2 rework bypass, four-eyes conflicts, CVAT sync protection in backend/cvat_integration/tests.py, quality/tests.py, and projects/tests.py; frontend Vitest confirms batch.confirm_qc2 and all 9 JobStatus values (constants.test.ts).
Supersedes / superseded by: Supersedes job-level Audit sampling and manual Audit accept/reject/partial_reject workflow.
```

## D03 — Identity linking and outward CVAT writes

**Evidence:** [baseline S3–S5](baseline.md). One branch uses linked numeric CVAT account references and implements assignee push/invitations; another uses username-oriented lookup and one-way sync.

**Recommendation:** choose the identity model and write policy explicitly. Preserve already accepted functionality; do not enable invitation or assignment side effects merely by importing a helper from another branch.

Record:

- External user identity and its CVAT instance/organization scope; migration from username references and handling of renamed/unlinked accounts.
- Service identity versus user-delegated operations; credential storage, redaction, and minimum access.
- Allowed outbound operations, their initiating VanoHub actor, and their audit trail.
- Source of truth for assignment conflicts; behavior on unlink, revocation, missing membership, or partial failure.
- Whether retries are synchronous, scheduled, or durably queued. A post-commit callback alone is not a queue.

**Acceptance:** contract and UI expose the actual outcome; remote failure does not masquerade as success. Rollback notes account for remote assignments or invitations that a code revert cannot undo.

### Resolution (D03)

```text
Status and date: Accepted and implemented in 8d66adc with known reliability gap (reconciled 2026-11-27 on 0beace7).
Selected option and reason: Personal CVAT identity linking via CvatAccount (cvat_user_id, cvat_username) verified once via PAT without storing the token, combined with system-credential outbound writes strictly scoped to organization invitations (invite_to_org) and job assignee sync (set_job_assignee).
Authority/evidence: backend/cvat_integration/models.py (CvatAccount, migration 0001_cvataccount.py), backend/cvat_integration/views.py (link, sync_organizations_view), backend/cvat_integration/assignee.py (current_holder, _OrgMembers.ensure, push_assignees, push_assignees_quietly, schedule_assignee_push), backend/cvat_integration/client.py (invite_to_org, set_job_assignee), frontend/src/features/cvat/pages/CvatLinkPage.tsx.
Affected code, data, API, and UI:
  - Identity linking: GET/POST/DELETE /api/cvat/link/ validates PAT via CvatClient(token=...).get_self(), stores only cvat_user_id + cvat_username, pushes held-job assignees, and quietly syncs orgs; DELETE unlinks and clears CVAT assignees on held jobs.
  - Outbound CVAT writes: _OrgMembers.ensure invites unmembered linked users to the CVAT org via invite_to_org(..., role="worker") when email is present; current_holder maps annotation -> annotator, active QC1 -> qc1_reviewer, PENDING_QC2 -> sample.auditor, and treats QC1_PASSED/APPROVED/DELIVERED as _NOT_MANAGED.
  - Known reliability gap (open follow-up): job/QC1/QC2/confirm-qc2 mutations invoke schedule_assignee_push(...) which calls push_assignees_quietly(...) inside transaction.on_commit(...). On CvatError, it logs a warning only — there is no durable retry queue, persisted failed-push state, or failure alert UI (only synchronous link and cvat-sync responses return sync.error / assignee_error / membership_warnings).
Migration/compatibility and external effects: Remote CVAT org invitations and PATCH /api/jobs/{id} assignee changes persist externally and cannot be undone by code rollback.
Verification required and evidence: Covered by CvatLinkTests, AssigneePushTests, and AutoOrgMembershipTests in backend/cvat_integration/tests.py (within the 205-test Django baseline on 0beace7). Hardening durable retry/visibility remains a follow-up item.
Supersedes / superseded by: Supersedes username-only CVAT lookup without CvatAccount or outbound assignee sync.
```

## D04 — Telemetry source and extension placement *(Open)*

**Evidence:** [baseline S2](baseline.md), PV04 and backlog B1–B5. The reference architecture does not fork or patch CVAT. The discussion also considered a CVAT-native extension and a separate GET gateway.

**Planning boundary:** VanoHub consumes CVAT data through APIs. Direct CVAT PostgreSQL/NAS access is outside scope. No direct ClickHouse connection is added by this plan.

| Candidate | Evaluate when | Required decision |
| --- | --- | --- |
| Existing supported CVAT API/export → VanoHub adapter | It exposes the required signals at acceptable freshness | Pin the deployed version, actual operation/schema, processing semantics, and limits |
| A native CVAT API extension | A demonstrated gap remains and modifying the CVAT deployment is acceptable | Reconcile no-patch policy, ownership, upgrade testing, schema registration, authorization, and resource limits |
| A separate API gateway for missing telemetry | A real trust/deployment boundary or reusable consumer need justifies it | Define narrow operations, service ownership, authentication, object scope, capacity, and failure handling |

A gateway is not automatically secure because it accepts only GET. Each operation still needs authorization and bounded input. Keep arbitrary SQL and raw database-table access out of public contracts. Keep Vector out of the application query path.

Extending “API docs” has two meanings: documenting existing routes or implementing a new route and documenting it. Record which is intended. Django's presence does not establish that an OpenAPI generator or docs UI is already configured.

**Acceptance:** name the requirement that existing APIs cannot satisfy, the selected source, hosting/maintenance owner, and contract. Do not implement all historical proposed endpoints by default.

### Resolution (D04)

```text
Status and date: Accepted (supersedes 2026-11-27 hybrid extension resolution), updated 2026-11-28.
Selected option and reason: Strict stock CVAT API-only integration (`PV04` preserved intact — no CVAT fork, patch, or in-process CVAT extension owned by or coupled to VanoHub). VanoHub remains the sole workflow/RBAC/QC SSoT and consumes stock CVAT REST endpoints only (`GET /api/issues`, `GET /api/comments`, `POST /api/events/export` -> `GET /api/requests/{rq_id}` -> streamed CSV download using a dedicated `read_only=True` PAT with global privilege `user` + org role `maintainer`/`owner`, plus existing sync/assignee/invitation APIs). Direct CVAT PostgreSQL, ClickHouse, Vector, and NAS access remain prohibited. Any external CVAT extension (such as `cvat-di-ext`) is kept strictly outside VanoHub's repository, roadmap, and deployment boundary; optional structured CVAT comment prefixes or future plug-in inputs (`B1`–`B5`) degrade cleanly to plain stock CVAT when absent.
Authority/evidence: User architectural decision (2026-11-28: keep `cvat-di-ext` completely decoupled from VanoHub), `docs/platform-spec.md` (`PV04` and Backlog `B1`–`B5`), and `backend/cvat_integration/{client,sync,assignee,schemas}.py`.
Affected code, data, API, and UI:
  - Spec invariant: `PV04` in `docs/platform-spec.md` ("không fork/patch CVAT") remains intact with zero amendment required.
  - VanoHub (`backend/cvat_integration/`, `backend/analytics/`): add dedicated read-only export token config, org-header-free `create_events_export` (`CvatClient(organization=org_slug)`, never combining `X-Organization` with `?org_id=`), `CVAT_HOST_HEADER`-aware `stream_download(result_url)` (`allow_redirects=False`), `CvatSyncScope`/`CvatExportBatch`/`CvatEventLedger`/`CvatWorkingTimeEvent`/`CvatEventQuarantine` tables, and `manage.py ingest_cvat_events` (stock `send:working_time` allowlisted by default; optional generic external plugin scopes strictly behind `B1`–`B5` contracts).
  - Boundary invariants: ingested CVAT events never mutate `Job.status`, `rework_round`, `AuditSample`, `Delivery`, `ReviewError`, `AnnotatorRequest`, or write into `ActivityLog` four-eyes history; actors resolve strictly via `CvatAccount.cvat_user_id`; `org_id=null` / foreign-org rows are dropped/quarantined; telemetry reads enforce `ProjectScopedViewMixin` (`404` isolation); VanoHub issues no CVAT plugin role tokens and vendors no external CVAT extension code.
Migration/compatibility and external effects: Preserves existing VanoHub APIs, `SYNCABLE_STATUSES`, and Hybrid A2 invariants; requires CVAT Compose durability hardening (persistent `/home/django/events` and `/vector-data-dir`, Vector disk buffer/ack, `CVAT_EXPORT_CACHE_TTL=3600`) before enabling `ingest_cvat_events`.
Verification required and evidence: Stock CVAT export ingestion tests, decoupling guardrail test in `backend/projects/test_integrity.py`, live stock CVAT E2E (`NT02`), and full VanoHub CI gates.
Supersedes / superseded by: Supersedes the 2026-11-27 `D04` hybrid in-process CVAT extension resolution; aligns fully with `PV04`.
```

## D05 — Counting, snapshots, and attribution *(Open)*

**Evidence:** [baseline S2 and S4](baseline.md), `backend/analytics/views.py` (`_pending_quality_cl`, `_pending_defect_error_rate`, `_pending_defect_rate_by_severity`), `backend/quality/models.py` (`AuditSample.checked_object_count`, `AuditSample.frames`), `backend/quality/views.py` (`AuditSampleViewSet._finish`), and `backend/jobs/views.py` (`submit_annotation`).

**Current `0beace7` state:**

- Because QC2 moved to frame-level sampling (`AuditSample.frames`, `quality/qc2.py`), `AuditSample.checked_object_count` stays `None` on review completion (`quality/views.py:198-206`), and `CL02` (`defect_error_rate` / `error_percent_in_job`), `CL05` (`defect_rate_by_severity`), and `CL11` (`quality_cl`) in `backend/analytics/views.py` currently return `value=None` with `status="pending_definition"` (rendered as `"Chưa chốt công thức"` in `MetricCard.tsx`).
- Pre-label baseline `S0` capture at import, locking manual `object_count` submission on `cvat_job_id`-linked jobs (`AnnotatorSubmitSerializer` / `submit_annotation` still accept optional manual `object_count`), `NS09` (`qa_to_annotation_ratio`) / `NS10`, and 2-axis evaluation (pairing quality CL thresholds with productivity/rework) remain open product/design items.

**Recommendation:** maintain separate definitions for visible object-frames, credited production, and the checked quality population. Do not replace them with a shape/track row count or a count of user interactions.

Before changing behavior, settle:

- Frame-scoped cuboid denominator counting (`checked_object_count` over `AuditSample.frames` vs full job) to unblock `CL02`, `CL05`, and `CL11`.
- Valid frame selection, frame numbering, step, deleted/included frames, outside intervals, and sparse tracks for the deployed CVAT version.
- Baseline `S0` capture timing, locking manual `object_count` on CVAT-linked jobs, and treatment of pre-labels, splits/merges, reassignment, rework, partial completion, and repeated imports/submits.
- The still-proposed per-frame credited-output formula `max(visible_S1, visible_S0)`; do not silently make it an implemented rule.
- Quality denominator and missing-object treatment (`is_missing_object`, `verdict = fail | edge`), `NS09`/`NS10` definitions, and 2-axis evaluation / 3-tier threshold rules.
- Whether aggregate counts are enough or full immutable annotation/meta snapshots are needed for reproducible QC.

Aggregate baseline counts cannot reconstruct original geometry. A checksum is not itself an immutable snapshot. When several upstream reads form a snapshot, record its consistency rule and version evidence; do not claim atomic consistency across CVAT state and asynchronously ingested events.

**Feasibility note (2026-11-27):** `CvatAnnotationsPayload.count_object_frames(..., included_frames=...)` (`backend/cvat_integration/schemas.py:160-249`) already supports frame-scoped `AuditSample.checked_object_count` computation directly via `CvatClient.count_job_objects` without a CVAT sidecar; `quality/qc2.py:pick_frames` (`112-118`) still needs alignment for `frame_step > 1` and `deleted_frames`. `/media/bang/Work/projects/cvat-docs/cvat-event-pipeline-v2/docs/03-qc-kpi-and-identity-policy.md` provides candidate `Quality CL = (pass + edge) / checked` (`Fail > Edge > Pass`, distinct assessed eligible instances) rules for Dec 4 sign-off.

**Acceptance:** examples with expected results, safe attribution to the correct worker/round, retry/deduplication behavior, and migration treatment for records without an original baseline.

## D06 — Time and metric semantics *(Open)*

**Evidence:** [baseline S2](baseline.md), `NS01`–`NS09`, and `backend/analytics/views.py` (`NS04` `audit_speed` in `Qc2SummaryView` and `DB02`/`DB03` `estimated_completion` in `ProjectOverviewView` currently return `status="pending_definition"` / `value=None`). Existing/proposed metrics mix provisional workflow timing with possible activity signals.

**Recommendation:** retain clear provenance. An elapsed workflow interval, a browser activity signal, and a verified business event represent different things.

Record timestamp format, duration unit, aggregation window, project display timezone, workday cutoff, actor mapping, cross-midnight behavior, duplicate/overlapping sessions, late events, and missing coverage. A workday cutoff is a separate business decision from timezone selection.

Do not assume upstream duration units. Normalize them explicitly. Do not silently substitute zero for unknown activity or calculate a rate from unavailable/zero denominators.

For QA/annotation ratios, choose comparable numerator and denominator semantics. An elapsed QA interval divided by active annotation time needs an explicit label and justification; it must not be presented as a comparable work-effort ratio by default.

**Feasibility note (2026-11-27):** CVAT `send:working_time` events lack `audit_sample_id`, so feeding `NS04` (`audit_speed`) requires window-based attribution (`(job_id, user_id)` inside `AuditSample` `[created_at, reviewed_at]` with ms -> hours unit normalization and explicit `status="unavailable"` when events are absent). `qc:client_*` telemetry remains strictly excluded from all KPI/SLA/CL calculations and workflow/sampling gates.

**Acceptance:** the API and Vietnamese UI distinguish estimated, unavailable, and observed values using an agreed representation, with the same time window and units.

## Recording resolution

For each accepted or superseded record, append:

~~~text
Status and date:
Selected option and reason:
Authority/evidence: current spec, user decision, or accepted local ADR
Affected code, data, API, and UI:
Migration/compatibility and external effects:
Verification required and evidence:
Supersedes / superseded by:
~~~

Updating a record does not update the application. Link its implementation task and completed change entry.
