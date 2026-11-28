# Port Plan (v2 — Hardened): Issue Logging & Management + Custom Vector Events

Prepared: 2026-11-28. Branch: `feature/annotator-qclv1`.  
Status: **Revised after 5-agent audit (`3/3 REVISE`) and 16-scenario defect-lifecycle dry-run (`16/16 PASS`). Slices 1–2 ready to implement; Slice 3 decoupled behind Gate 0 (`D06`, CVAT Compose durability; stock CVAT API only — `PV04` intact).**

Narrows [fold-issue-logging-management-plan.md](./fold-issue-logging-management-plan.md): only issue logging/management (Slices 1–2) and stock CVAT event-export telemetry (Slice 3) are in scope. Scorecards, funnel, ETA, Pareto, 3D diff, `S0` baseline, and `RulingPrecedent` remain out of scope.

Reference specs: [platform-spec.md](../platform-spec.md), [decisions.md](./decisions.md), [fold-issue-logging-management-plan.md](./fold-issue-logging-management-plan.md).

---

## 1. Authoritative Boundaries & Threat Model

1. **VanoHub owns workflow state, RBAC, four-eyes, and adjudication; CVAT is read-only for issues.**
   - Zero new outbound CVAT writes (`backend/cvat_integration/assignee.py` remains strictly limited to `PATCH /api/jobs/{id}` assignee and `POST /api/invitations?org=<slug>`).
   - `CvatClient` reads issues via `GET /api/issues?job_id=X&sort=id` and comments via `GET /api/comments?job_id=X&sort=id` (stock CVAT `IssueReadSerializer.comments` returns only `{url, count}` and both views default to `ordering="-id"`; `sort="id"` eliminates offset shift skips/duplicates).
2. **Stock CVAT OPA tamper defense (addresses `issues.rego:189-194` & `comments.rego:198-203`):**
   - During `ANNOTATING`/`REWORK`, CVAT sets `job.assignee = annotator` (`backend/cvat_integration/assignee.py:71-74`), which grants the annotator OPA `UPDATE` on every issue (`resolved`, `position`) and `UPDATE` + `DELETE` on every comment (including QC's opening comment).
   - During `QC1_REVIEWING`/`PENDING_QC2`, `job.assignee` is the QC reviewer/auditor, so QC creates & imports issues before Reject returns `job.assignee` to the annotator.
   - **Hardened VanoHub defenses:**
     - **Immutable initial envelope:** On first valid import, lock `first_comment_id`, `defect_code`, `primary_category`, `severity`, `source`, `is_clarification`, `track_id`, `shape_id`, `position`. Subsequent re-imports **never** downgrade `severity`, clear `is_clarification`, drop an existing `JobIssue` via injected `[REF:preqc:...]`, or wipe 3D binding — instead they set `tampered=True` + `tamper_reason`.
     - **Per-comment author authority:** Bare `issue.resolved=True` in CVAT is mirrored in `cvat_resolved` ONLY and **never** closes `JobIssue.status`. Every CVAT lifecycle comment is authorized by `comment.owner` -> `CvatAccount` -> project role + four-eyes (§2.2).
     - **Monotonic comment floors:** Track `last_applied_lifecycle_comment_id` and `reopened_after_comment_id`. Deleting a QC `[REOPENED]` comment in CVAT cannot revert `status` back to `addressed`, and plain non-lifecycle comments never regress VanoHub `status`.
3. **Strict CVAT plugin decoupling (`PV04`):**
   - VanoHub targets stock `cvat-base` REST APIs only. VanoHub issues **no** CVAT plugin role tokens, requires **no** CVAT fork/patch/in-process extension, and owns **no** custom CVAT-side endpoints. Any external CVAT UI helper or script is strictly untrusted and outside VanoHub's repository and deployment boundary; real authority lives strictly in VanoHub import + backend endpoints.
   - *Pool QC1 note:* Under stock CVAT `issues.rego`, an org `worker` cannot list/create CVAT issues on unassigned `PENDING_QC1` pool jobs until `start_qc1` pushes `job.assignee` via `CvatAssigneeOutbox`.

---

## 2. Defect Lifecycle Pipeline (State Machine & Authority)

### 2.1 Issue Ingestion & Stage-Aware Initial Authority

Parse opening comment (`comments[0]`, sorted by `id ASC`) with `NEW_ISSUE_PREFIX_RE` (`[CODE][severity]?[REF:...]?`) + `[PARAMS:...]` + `[FRAMES:a-b]` (`backend/quality/issue_envelope.py`):
- **Skip filter (new issues only):** Skip if `ref` starts with `preqc:`, `preqc_external:`, `auto:`, or (`ref` and `params.get("tool")`).
- **Severity floor & untyped issues:** Untyped vanilla CVAT issues (no `[CODE]` prefix) import as `defect_code=""`, `severity="minor"` (non-blocking). Typed issues missing `[severity]` or below taxonomy floor inherit the taxonomy floor (`CLS-UNK`/`CLS-UNCL`/`EXI-MISS`/`E1`–`E3`/`E5`–`E6` ≥ `major`, `E4` ≥ `minor`).
- **3D position & bounds:** Accept any non-empty finite `list[float]` (reject `NaN`/`Inf`/`bool`); decode `(track_id, shape_id)` only when `len(pos) == 16`, slots `12..15 == 0`, at most one of slots 10–11 is set, and `1 <= id <= PG_INT32_MAX` (else `(None, None)`). Allow nullable `owner`, `assignee`, `created_date`, `updated_date`.
- **Stage-aware author check** using `get_stage_history(job)` → `(annotator_ids, qc1_ids, qc2_ids)` (`backend/quality/qc2.py:33-97`) and `user.get_project_roles(project)` (`expand_roles()`):
  1. `eff_code in ("CLS-UNK", "CLS-UNCL")` AND (`user.id in annotator_ids` or `user.id == job.annotator_id`) → `authority_status="valid"`, `author_stage="annotator"`, initial `status="unclear"` (creates pinned PM `UserNotification(DISPUTE)`).
  2. `Role.QC2 in roles` AND `user.id not in (annotator_ids | qc1_ids)` AND (`job.status in (PENDING_QC2, APPROVED, DELIVERED)` or `Role.QC1 not in roles`) → `authority_status="valid"`, `author_stage="qc2"`, initial `status="open"`.
  3. `Role.QC1 in roles` AND `user.id not in (annotator_ids | qc2_ids)` AND (`job.qc1_reviewer_id in (None, user.id)`) → `authority_status="valid"`, `author_stage="qc1"`, initial `status="open"`.
  4. Otherwise (null/unmapped owner, annotator logging non-clarification defect, four-eyes conflict) → `authority_status="rejected_author"` (excluded from gates, Reject materialization, and `get_stage_history`).
- **Four-eyes propagation & reassignment resilience:**
  - Valid `author_stage="qc1"` feeds `qc1_ids` and valid `author_stage="qc2"` feeds `qc2_ids` in `get_stage_history`, `_exclude_four_eyes_conflicts`, and `AnnotatorJobViewSet.claim`.
  - Valid `author_stage="annotator"` and `ActivityLog(action="issue.ruling")` NEVER feed QC1/QC2 four-eyes history.
  - Once imported as `valid`, later job reassignment never revokes `authority_status`.
- **Vanished CVAT issues:** Mark `source_missing=True` ONLY after error-free full pagination (`sort="id"`, deduped by `id`) AND ONLY for rows with `created_at < fetched_at` and `cvat_synced_at < fetched_at` (prevents stale concurrent fetches from hiding newly created issues).

### 2.2 Per-Comment & VanoHub Transition Matrix

Only process CVAT comments with `comment.id != first_comment_id` and `comment.id > max(last_applied_lifecycle_comment_id, reopened_after_comment_id)`:

| Trigger / Source | Allowed Actor | Guard | `JobIssue.status` Transition | Side Effects |
| --- | --- | --- | --- | --- |
| CVAT `[ADDRESSED]` or VanoHub `POST .../issues/{id}/address/` | Job annotator (`Cap.ANNOTATE_JOBS`, `job.annotator_id == user.id` or `user.id in annotator_ids` for CVAT) | Reject if `is_clarification and ruled_at is None`; VanoHub requires `status in (open, reopened)` & active annotator job | `open \| reopened → addressed` | Advance `last_applied_lifecycle_comment_id`; `ActivityLog("issue.address")`. If CVAT body matches `Dispute:`, also run Dispute side effects below. |
| VanoHub `POST .../issues/{id}/dispute/` or CVAT `[ADDRESSED] Dispute:` | Job annotator (`Cap.ANNOTATE_JOBS`) | Active editable job (`job.status not in (APPROVED, DELIVERED)`) | `open \| reopened \| addressed → unclear` | Sets `is_disputed=True`, creates/links `AnnotatorRequest(error_dispute, job_issue=ji, review_error=latest_active_err)` + pinned PM `UserNotification(DISPUTE)` + `ActivityLog("issue.dispute")`. |
| CVAT `[UNCLEAR]` | Job annotator or authorized non-conflicted QC/PM | `status not in (not_an_issue, resolved)` | `open \| reopened \| addressed → unclear` | Pin PM `UserNotification(DISPUTE)`. |
| CVAT `[REOPENED]` or VanoHub `POST .../issues/{id}/reopen/` | Authorized non-conflicted QC1/QC2/PM | If `status == not_an_issue`: **PM wins** (set `cvat_reopen_drift=True`, keep `not_an_issue`) | `open \| addressed \| resolved \| unclear → reopened` | Set `reopened_after_comment_id = max(reopened_after_comment_id, cvat_last_comment_id)`. |
| CVAT `[RESOLVED]` / `[QC-FIXED]` or VanoHub `POST .../issues/{id}/resolve/` | Authorized non-conflicted QC1/QC2/PM (`Cap.PERFORM_QC1` / `PERFORM_AUDIT` / `MANAGE_JOBS`) | `status != not_an_issue`; job not `DELIVERED` | `open \| addressed \| reopened \| unclear → resolved` | `ActivityLog("issue.resolve")`. |
| VanoHub Reject (`qc1_reject`, `AuditSample.reject`) with `job_issue` items | Rejecting QC1 / QC2 (stage-matched; QC2 blocks `author_stage="qc1"` & out-of-`sample.frames`) | Valid same-job issue, `status != not_an_issue` | Forces `→ reopened` | Creates `ReviewError(job_issue=ji, reported_by=request.user)` idempotent per `(job, stage, rework_round, cvat_issue_id)`; sets `reopened_after_comment_id = max(reopened_after_comment_id, cvat_last_comment_id)`. |
| VanoHub PM `rule(decision="ruling")` (`Cap.MANAGE_JOBS`) | PM (never from CVAT comments) | Job not `DELIVERED` (`BG03`) | `unclear \| open \| reopened → open` (preserves `ruling_*` on future re-imports) | Sets `ruling_label`/`ruling_attributes`/`ruling_note`/`ruled_by`/`ruled_at`, `reopened_after_comment_id = cvat_last_comment_id`, `ActivityLog("issue.ruling")` (excluded from four-eyes), unpins PM + notifies annotator/QC1. If `dispute_outcome="rejected"`, rejects linked `AnnotatorRequest(error_dispute)` and clears `is_disputed`. |
| VanoHub PM `rule(decision="not_an_issue")` (`Cap.MANAGE_JOBS`) | PM, **blocked if `user.id in annotator_ids`** (no self-void) | Job not `DELIVERED` | `any → not_an_issue` (terminal against CVAT re-import) | Voids **all** linked non-voided `ReviewError`s (`is_voided=True`), resolves linked `PENDING_PM` `AnnotatorRequest(error_dispute)` (updating `CL09`, notifications, `ActivityLog("annotator.request_resolve")`), logs `ActivityLog("issue.ruling")`. |
| VanoHub PM `rule(decision="resolved")` (`Cap.MANAGE_JOBS`) | PM | Job not `DELIVERED` | `any (except not_an_issue) → resolved` | Clears `is_disputed`, sets `ruled_by`/`ruled_at`, unpins PM notification, logs `ActivityLog("issue.ruling")`. |
| VanoHub `AnnotatorRequestViewSet.resolve` (`error_dispute`) | PM (`Cap.MANAGE_JOBS`) | Shared atomic service with `rule` | `RESOLVED` → `not_an_issue` + void `ReviewError`; `REJECTED` → `is_disputed=False`, `unclear → reopened` | Guarantees 100% `CL09` (`dispute_overturn_rate`) and rework-credit parity. |

### 2.3 Two-Gate Architecture (`Project.issue_gate_enabled`, default `False`)

Separating **Submit Gate** from **Acceptance Gate** prevents both `GV02` (`annotator_wip_limit=2`) / `TG05` (no SLA pause) deadlocks on `CLS-UNK`/disputes AND unverified closures entering QC2/Delivery:

1. **Submit Gate** (enforced in `submit_annotation` AND **every** `sync.py` transition into `PENDING_QC1`: `PENDING_ANNOTATION → PENDING_QC1`, `ANNOTATING → PENDING_QC1`, `_new_job`, `sync_batch`, `import_task_jobs`):
   - **Predicate:** Blocks if any `JobIssue` on the job has `authority_status="valid"`, `source_missing=False`, `status in ("open", "reopened")`, and (`severity in ("critical", "major")` OR `ruled_at is not None`).
   - **Does NOT block on `status == "unclear"`** (unruled `CLS-UNK`/`CLS-UNCL` or pending PM dispute) so annotators are never WIP-deadlocked waiting for PM.
   - **Outage policy (`VH04` — `docs/platform-spec.md:145, 375`):**
     - `submit_annotation` removes outer `@transaction.atomic`, checks unlocked preconditions first, runs CVAT issue refresh with interactive budget (`timeout=5s, max_duration_seconds=10s`), and on `CvatError` **fails open to cached local `JobIssue` rows** (still blocking on known local open blockers; returns `issue_sync_warning=True` rather than HTTP 500).
     - `sync.py` catches per-job `CvatError` without aborting org sync and **fails closed** (holds job status + drift indicator) whenever `issue_gate_enabled=True` and prefetch failed.
2. **Acceptance Gate** (enforced in `qc1_pass`, `sync.py` `POST_QC1_CVAT_STATES`, `BatchViewSet.confirm_qc2`, `AuditSampleViewSet.pass_`, and `DeliveryViewSet.perform_create`):
   - **Predicate:** Blocks if any `JobIssue` on target job(s) has `authority_status="valid"`, `source_missing=False`, and EITHER `status == "unclear"` OR (`status in ("open", "reopened", "addressed")` AND (`severity in ("critical", "major")` OR `ruled_at is not None`)).
   - Ensures zero unruled `CLS-UNK` holds, zero unresolved disputes, and zero unverified `addressed` blockers ever pass QC1, enter QC2, get `approved`, or lock into `DELIVERED`.

### 2.4 Canonical PostgreSQL Lock Order (Deadlock-Free)

Every mutator touching jobs/issues/errors/requests MUST acquire `select_for_update(of=("self",))` strictly in this order:
```
Dataset → Batch → AuditSample → Job → JobIssue (order_by id) → ReviewError (order_by id) → AnnotatorRequest (order_by id)
```
- Both `JobIssueViewSet.{address,dispute,resolve,reopen,rule}` and `AnnotatorRequestViewSet.resolve` read `job_id` unlocked, acquire `lock_job(project, job_id)` first, then lock child rows in ascending `id` order.
- Per-job CVAT issue import acquires a PostgreSQL advisory lock (`_try_advisory_lock` keyed on `job.pk`) around fetch+upsert and captures `fetched_at` *before* HTTP I/O.

---

## 3. Dry-Run Verification of the Defect Lifecycle Pipeline

Executed via standalone state-machine simulation (`scratch/dry_run_defect_lifecycle.py`) covering 16 end-to-end and adversarial scenarios — **16/16 PASSED**:

| ID | Scenario Dry-Run | Result |
| --- | --- | --- |
| S01 | Happy path: QC1 issue → import → Reject → CVAT `[ADDRESSED]` → Submit → QC1 resolve & pass → QC2 pass | PASS |
| S02 | Multi-round reopen of same CVAT issue `#501` across rounds 0→1 + comment floor + QC2 anti-laundering (`#502`) | PASS |
| S03 | Attack A: Annotator flips `issue.resolved=True` + posts `[RESOLVED]`/`[NOT-AN-ISSUE]`/`[RULING]` in CVAT | BLOCKED |
| S04 | Attack B: Annotator edits QC comment `#0` (`critical → minor`, `[REF:preqc:]`) + wipes 3D `position` | BLOCKED + `tampered=True` |
| S05 | Attack C: Annotator deletes QC `[REOPENED]` comment in CVAT | BLOCKED |
| S06+S07 | `CLS-UNK` hold: anti-self-address + annotator submits without WIP deadlock + `qc1_pass` blocked + PM `RULING` preserved after post-ruling `[ADDRESSED]` | PASS |
| S08 | Job reassignment (Annotator A → B) preserves A's open `CLS-UNCL` hold (`valid`); B addresses post-ruling | PASS |
| S09 | Plain non-lifecycle CVAT comment after VanoHub `address` does not regress status to `open` | PASS |
| S10 | Stage-aware four-eyes (QC1 own issue after `start_qc1`, dual QC1+QC2 blocked from QC2 after logging CVAT issue, dual PM+Annotator blocked from self-void) | PASS |
| S11 | Bidirectional Dispute/`CL09` sync (`NOT-AN-ISSUE` voids all linked `ReviewError`s & resolves request = 100%; denied request clears `is_disputed` & reopens = 50%; CVAT reopen after `NOT-AN-ISSUE` sets `cvat_reopen_drift=True`) | PASS |
| S12 | `VH04` outage fallback (`submit_annotation` fail-open to local cache + warning; `sync.py` round-0 fail-closed) + stale-snapshot race does not mark `#509` `source_missing` | PASS |
| S13 | Untyped vanilla issue (`minor`), `preqc:` skip, `EXI-MISS` constraint (`cvat_object_id=None, verdict=fail`), 3D bounds (`0`, `NaN`), deleted mistaken `CLS-UNK` releases hold | PASS |
| S14 | Unauthorized annotator logging non-clarification defect → `rejected_author` (excluded everywhere) | PASS |
| S15 | Reviewer B rejects with Reviewer A's QC1 issue → BOTH A and B enter `get_stage_history` and are blocked from QC2 | PASS |
| S16 | PM `RULING` on `CLS-UNK` during QC1 where existing cuboid matches ruling → QC1 resolves & passes without rework | PASS |
| S17 | `confirm-qc2` and `Delivery` Acceptance Gates block late-imported open blockers; `BG03` blocks ruling after `DELIVERED` | PASS |

---

## 4. Implementation Slices

### Slice 1 — Backend Issue Import, Hardened Lifecycle, Gates & PM Ruling (Ready Now)
- **Pre-code doc alignment:** Update `docs/platform-spec.md` (`DL05`, `L6`–`L7`, `L11`, RBAC & notification matrices), `docs/api/contracts.md`, and `.agents/rules/domain-invariants.md`.
- **`backend/quality/issue_envelope.py`:** Pure VanoHub comment-envelope parser defining VanoHub's optional structured CVAT comment grammar (`NEW_ISSUE_PREFIX_RE`, lifecycle markers, `[FRAMES]`, `[PARAMS]`, `decode_3d_position` finite + `1..PG_INT32_MAX` + mutually exclusive slots; degrades cleanly to plain vanilla CVAT issues when unstructured) + unit tests.
- **`backend/cvat_integration/schemas.py` & `client.py`:** Strict Pydantic v2 `CvatIssuePayload` / `CvatCommentPayload` (nullable `owner`/`assignee`/`created_date`/`updated_date`, finite `list[float]`, IDs `1..PG_INT32_MAX`, `issue.job == cvat_job_id`); `list_job_issues(job_id)` and `list_job_comments(job_id)` passing `sort="id"`, deduping by `id`, honoring interactive timeout overrides.
- **`backend/projects/models.py` & `serializers.py`:** Add `Project.issue_gate_enabled = BooleanField(default=False)` to `Project`, `ProjectDetailSerializer`, and `ProjectSettingsSerializer`.
- **`backend/quality/models.py` + migrations (Django 6 `CheckConstraint(condition=...)` only):**
  - Additive `ErrorCategory.code` (`default=""`) + `primary_category` (`"" | E1..E6`), partial `UniqueConstraint(fields=["project", "code"], condition=~Q(code=""))`, `CheckConstraint` on `primary_category`, data migration backfilling `primary_category` on existing default categories + adding `E6` (`Lỗi liên kết track`), and fix `ErrorCategoryViewSet` `IntegrityError` handling so duplicate `code` is not misreported as duplicate `name`.
  - New `JobIssue` model with all §2.1 fields, `frame_start`/`frame_end` (`CheckConstraint(frame_start <= frame_end)`), `clean()` cross-project/cross-job checks, positive external ID `CheckConstraint`s, mutually exclusive `track_id`/`shape_id` constraint, and `ruled_by IS NULL OR ruled_at IS NOT NULL`.
  - Add `ReviewError.job_issue = ForeignKey(JobIssue, null=True, blank=True, on_delete=SET_NULL, related_name="review_errors")` and `ReviewError.cvat_issue_id = PositiveIntegerField(null=True, blank=True)` with partial `UniqueConstraint(fields=["job", "stage", "rework_round", "cvat_issue_id"], condition=Q(cvat_issue_id__isnull=False))` (1-to-N across rework rounds!).
  - Add `AnnotatorRequest.job_issue = ForeignKey(JobIssue, null=True, blank=True, on_delete=SET_NULL, related_name="disputes")` with `clean()` checking `job_issue.job_id == job_id`.
- **`backend/quality/issues.py`:** Import service, per-comment author authority, tamper detection, `submit_blocking_issues`, `acceptance_blocking_issues`, and shared atomic adjudication/dispute service enforcing §2.4 canonical lock order.
- **`backend/quality/views.py`, `serializers.py`, `urls.py`, `qc2.py`:**
  - `JobIssueViewSet` (`ProjectScopedViewMixin`, `StandardPagination`, `PQ01` role-scoped `get_queryset()`):
    - `list` / `retrieve` / `import`: `[Cap.VIEW_JOBS, Cap.PERFORM_QC1, Cap.PERFORM_AUDIT, Cap.ANNOTATE_JOBS]` (`import` blocks `DELIVERED`/locked/non-CVAT jobs).
    - `address` / `dispute`: `Cap.ANNOTATE_JOBS` (`job.annotator_id == user.id`, active editable job).
    - `resolve` / `reopen`: `[Cap.PERFORM_QC1, Cap.PERFORM_AUDIT, Cap.MANAGE_JOBS]` (stage & four-eyes checked).
    - `rule`: `Cap.MANAGE_JOBS` (non-`DELIVERED`, self-void blocked).
  - Extend `_BaseErrorInputSerializer` with optional `job_issue` ID (explicit validated `category`, enforcing `review_error_missing_object_valid` for `EXI-MISS`, stage-matching & `sample.frames` check on QC2, forcing selected `JobIssue`s to `reopened` + comment floor).
  - Include valid QC `JobIssue` authors in `get_stage_history`, `_exclude_four_eyes_conflicts`, and `AnnotatorJobViewSet.claim`.
  - Enforce Acceptance Gate in `qc1_pass`, `AuditSampleViewSet.pass_`, `BatchViewSet.confirm_qc2`, and `DeliveryViewSet.perform_create`.
- **`backend/jobs/views.py`, `backend/cvat_integration/sync.py`, `backend/analytics/views.py`:**
  - Wire `submit_annotation` (non-decorated atomic block, pre-lock refresh + `VH04` fail-open warning) and all `sync.py` `→ PENDING_QC1` / `POST_QC1_CVAT_STATES` paths (`sync_organization`, `sync_batch`, `import_task_jobs`, `_new_job`) with `_check_deadline()` guards.
  - Refactor `AnnotatorRequestViewSet.resolve` to lock `Job` first and invoke the shared bidirectional dispute/ruling service.
  - Add `pending_issue_rulings` to `ProjectOverviewView.pending_decisions` (`TD13`) and emit pinned `UserNotification` events per §2.2.
- **Tests:** All 16 dry-run scenarios as PostgreSQL 17 integration tests + RBAC (`404` vs `403` + `PQ01`), canonical lock-order/concurrency tests, and DB `IntegrityError` tests in `backend/projects/test_integrity.py`.

### Slice 2 — Frontend (Untitled UI / React Aria)
- `frontend/src/features/quality/qc1/Qc1ReviewPanel.tsx` & `frontend/src/features/quality/qc2/ReviewPanel.tsx`: Job issues panel, on-demand import button, QC `Xác nhận đã sửa` (`resolve`), tamper/drift badges, and one-click Reject prefill (`job_issue` + category).
- `frontend/src/features/jobs/pages/AnnotatorJobDetailPage.tsx`: Annotator `Đã sửa` (`address`) / `Phản hồi` (`dispute`) controls + `issue_sync_warning` notice + CVAT-completed / VanoHub-held drift badge.
- `frontend/src/features/jobs/pages/JobsPage.tsx` & `AnnotatorRequestsPage.tsx`: PM ruling modal (`Phán quyết` / `Không phải lỗi` / `Đã xử lý`, guarded by `manage_jobs`).
- `frontend/src/features/quality/pages/ErrorCategoriesPage.tsx` (`code`, `primary_category` `E1`–`E6`) and `frontend/src/features/projects/pages/ProjectSettingsPage.tsx` (`issue_gate_enabled` toggle wired into keyed `formKey`).
- Vietnamese labels consistent with `docs/platform-spec.md`; `RequireCap` guards matching backend `Cap`.

### Slice 3 — Stock CVAT Event Export Ingestion & `NS04` (DECOUPLED — Blocked on Pre-Slice-3 Gates)

**Hard prerequisites before starting Slice 3:**
1. **Gate 0 (`PV04` / `D04` invariant):** Preserve `PV04` in `docs/platform-spec.md:32` (**stock `cvat-base` only; no fork, patch, or in-process CVAT extension owned by VanoHub**). VanoHub consumes stock CVAT event exports only and stays 100% decoupled from any external CVAT extension.
2. **Gate 0 (`D06`):** Sign off `NS04` in `docs/refactoring/decisions.md:171-185`: add `AuditSample.started_at` for authoritative non-spoofable `NS04` (or explicitly mark `send:working_time`-backed `NS04` as `status="provisional"` with per-event duration clamp + interval merge + `Qc1SummaryView.audit_speed` parity + initial vs re-check decision).
3. **CVAT Compose durability:** Persist `/home/django/events` and `/vector-data-dir` (replace `tmpfs`), enable Vector disk buffer + `acknowledgements.enabled = true`, lower `CVAT_EXPORT_CACHE_TTL` (`3600`), and fix/restrict Grafana `/analytics`.

**Hardened Slice 3 design (stock CVAT API only, once prerequisites pass):**
- **Transport (least-privilege `D04`, never admin):**
  - Dedicated `CVAT_EXPORT_ACCESS_TOKEN` (`read_only=True` PAT, global group `user`, org `maintainer`/`owner` — never global `worker` due to CVAT `events.rego` bug, and register token in `backend/config/settings.py` `SecretRedactionFilter`).
  - Call `POST /api/events/export` using `CvatClient(organization=org_slug)` with **no** `org_id` query param (avoiding `iam/middleware.py:35-39` HTTP 400), bounded time slices (`<= 30m` poll / `<= 6h` backfill), sliding overlap window (`lag = 5m`, `overlap = 30m`), and DB lease column (`CvatSyncScope.locked_until`) instead of session-only `pg_try_advisory_lock`.
  - Poll `GET /api/requests/{rq_id}` (`200 OK` with `status in {queued, started, finished, failed}`), download via `CvatClient.base_url` + `/api/events/download?rq_id=...` (`allow_redirects=False`, streaming CSV parser, fail loudly on `X-Accel-Redirect` empty body).
  - Scope-allowlist (`send:working_time` by default; any future external telemetry scopes strictly behind VanoHub's `B1`–`B5` plug-in contracts and quarantined from workflow/KPI credits) **before** persistence; strip `user_email`, `user_name`, `payload.username`, and never store `create/update/delete:comment` bodies.
  - Dedupe keys: composite `(org_id, user_id, job_id, timestamp_ms, duration, payload.request.id)` for stock `send:working_time` (and optional `payload.event_id` UUID when ingesting allowlisted external plugin events).

---

## 5. Verification Gates

Per slice ([AGENTS.md](../../AGENTS.md), `.github/workflows/ci.yml`):
- **Backend (`backend/`, PostgreSQL 17 running):**
  - `pipenv run ruff check ../backend`
  - `pipenv run pyright -p ../pyproject.toml`
  - `pipenv run python manage.py check`
  - `PIPENV_DONT_LOAD_ENV=1 DJANGO_DEBUG=False DJANGO_ALLOWED_HOSTS=ci.example.com DJANGO_SECURE_SSL_REDIRECT=True pipenv run python manage.py check --deploy`
  - `pipenv run python manage.py makemigrations --check --dry-run`
  - `pipenv run python manage.py test --noinput`
- **Frontend (`frontend/`):**
  - `npm test && npx tsc -b --noEmit && npm run lint && npm run build`
  - Live multi-role browser verification across `PM`, `QC2`, `QC1`, and `Annotator` for Slice 2.
