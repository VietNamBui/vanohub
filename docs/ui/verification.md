# UI change and verification guide

Prepared: 2026-11-27. Use for T05 and affected T07 checks. This guide extends the active frontend rules; it does not replace the product specification or redesign every screen.

## 1. Define a screen-sized change

Before implementation, record the route/screen, affected roles, intended interaction, API contract ID, and the baseline revision or screenshot. Describe observable before/after behavior separately from component restructuring.

Reuse the active design system and feature boundaries. If migrating a screen from Ant Design to Untitled UI, preserve its accepted behavior while checking form, focus, validation, keyboard, and async-state behavior. Avoid a simultaneous whole-application redesign.

The active [frontend rules](../../.agents/rules/frontend.md) require Vietnamese UI copy, shared API handling (`apiClient`, `useRequest`, `useAction`, `getErrorMessage`), capability parity (`RequireCap` in `frontend/src/app/router.tsx`), and entity-keyed state resets.

## 2. Role and workflow coverage

| Role/surface | Main scenario | Negative or boundary scenario |
| --- | --- | --- |
| PM | Sync orgs/CVAT tree (`cvat-sync`), assign jobs, configure workflow, confirm eligible task to QC2 (`confirm-qc2`), reassign QC2 sample auditor, deliver (`Delivery` auto-closes open audits) | Ineligible task (`qc1_passed_count != job_count` or locked job), missing CVAT source, unauthorized org (`404`), locked/delivered job, failed remote action |
| Annotator | Claim/start/open CVAT, submit, inspect rework & dispute errors | WIP limit, concurrent claim, wrong assignee, stale job state, pending count if supported |
| QC1 | Open assigned/pool work, record structured `ReviewError` (`verdict`, `frame_number`, `cvat_object_id`, `is_missing_object`), pass (`QC1_PASSED` vs post-confirmation `PENDING_QC2`) or reject | Self-review/four-eyes conflict, missing required fields, duplicate submit, stale status |
| QC2 | Open assigned frame sample (`AuditSample.frames`), record pass or structured reject | Historical four-eyes conflict, wrong project/sample, closed audit |
| Multi-role user | Switch organization and permitted role context | State/data retained from another organization, incorrect implied role (`PM -> QC2` one-way), stale capability cache |
| Analytics | Read metric value, units, window and provenance; drill down | `pending_definition` shown as `"Chưa chốt công thức"` (never `0`), denominator missing, filter/window lost in navigation |

Use only scenarios touched by the slice, then cover the required end-to-end path at the milestone boundary. Do not invent available routes or actions for features still marked as proposals.

## 3. Per-screen checklist

- [ ] Route guard matches the relevant backend capability; backend authorization remains authoritative.
- [ ] API wrapper, request fields, response types, errors, and status enums match the accepted contract.
- [ ] Vietnamese labels reflect the actual transition: for example, “Đạt QC1” and “Chờ QC2” are not interchangeable.
- [ ] Loading, empty, error, retry, permission-denied, and stale-data states are handled where applicable.
- [ ] Mutations prevent accidental double submission and show actual server outcomes.
- [ ] Switching project/entity resets the correct form, selection, modal, and query state.
- [ ] Row actions, filters, URL parameters, and drill-down links preserve intended context.
- [ ] Dates and workday boundaries use the accepted project timezone/cutoff, not an incidental browser timezone.
- [ ] Metric labels distinguish estimates, unavailable values, and observed data; units and denominators are visible when needed.
- [ ] Relevant keyboard/focus behavior, form labels/errors, and the actual target viewport are checked.
- [ ] No credentials, private upstream payloads, or unauthorized project details appear in the UI or browser bundle.

For QC forms, check the locally accepted handling of frame/object identifiers, verdict, missing-object flags, and voided errors. The old checklist's claims of missing fields are investigation leads; reproduce them before treating them as present defects.

## 4. Evidence format

Use one concise table per changed screen or coherent group:

| Route / role / state | Action and expected result | Actual result | Evidence / revision |
| --- | --- | --- | --- |
| Fill from the local implementation | Include the relevant API interaction | Passed / failed / not run, with reason | Screenshot or test/log reference and exact revision |

If the screen cannot be exercised, state the missing dependency. A successful TypeScript build does not establish browser behavior.

Attach before/after screenshots when visual changes need comparison; exclude credentials and personal data. Retain only useful evidence rather than a screenshot of every click.

## 5. Completion

Update [changes.md](../refactoring/changes.md) with the screen, interaction change, contract impact, actual checks, and remaining issues. Update the existing product checklist only when its status is supported. Keep detailed product behavior in the existing specification and detailed API shapes in the canonical contract.

Relevant tasks and dependencies: [plan.md](../refactoring/plan.md). Contract procedure: [contracts.md](../api/contracts.md).

## 6. Reconciled frontend baseline (`feature/annotator-qclv1` @ `b37b0b2` + working tree `2026-11-28`)

- **UI terminology, route guards & management screens:** `frontend/src/app/router.tsx` guards **29** project-scoped `guarded(...)` routes (`overview`, `team-ranking`, `datasets`, `batches`, `jobs`, `queue`, `teams`, `teams/:teamId`, `workload`, `audits`, `qc2/strategy`, `qc2/work`, `qc2/dashboard`, `qc1/dashboard`, `qc1/work`, `annotator/dashboard`, `annotator/analytics`, `annotator/jobs`, `annotator/jobs/:jobId`, `annotator/rework`, `annotator/requests`, `error-categories`, `delivery`, `settings`, `activity`, `guidelines`, `cvat-link`, `announcements`, `account/settings`) via `RequireCap` matching backend `Cap` values (with noted nuances: `qc2/dashboard` checks `perform_audit` while `Qc2SummaryView` accepts `[perform_audit, view_dashboard]` — equivalent via `PM -> QC2`; `BatchesPage` calls `listTeams` requiring `[manage_team, view_dashboard]`, both held by `PM` alongside `view_jobs`). Added `/settings` (`ProjectSettingsPage.tsx`, `manage_settings`, all 9 editable fields), `/activity` (`ActivityLogPage.tsx`, `view_activity`, filters + pagination + Slideover detail), and internal Organization create/edit (`pm_ids`) on `ProjectListPage.tsx` (gated by `user.is_pm`), wired into `ProjectLayout.tsx` and `QuickSearchModal.tsx`.
- **Hybrid A2 & Delivery parity:** `OverviewPage.tsx` renders `pending_decisions` (`"Việc cần quyết định (TD13)"`, including `batches_ready_for_qc2_confirm` with `locked_jobs == 0`), `"Phân bố lỗi QC (CL04)"`, `overdue_batches`, and `delivery_on_time_rate` (`DH07`). `BatchesPage.tsx` renders `ConfirmQc2Dialog` (`confirmBatchQc2`), `last_sync_error` badges/messages, and `?org=` CVAT Task links (`cvatTaskUrl`). `Qc1DashboardPage.tsx` and `Qc1WorkPage.tsx` use `"Đạt QC1"` copy and honor `EscalationPolicy.WARN_ONLY`. `DeliveryPage.tsx` renders the `DH07` banner (`computeDeliveryDh07Summary`), candidate `deadline`/`DueStateBadge`/`pending_qc2_samples`/`in_progress_audits`/lock reasons, history `deadline`/`is_on_time`, and edits `recipient`, `output_path`, `client_feedback`, and `note` via `FeedbackDialog`.
- **Structured `ReviewError`, action guards & CVAT links:** Shared `ReviewErrorChips` and `splitActiveErrors` (`max(total_rework_rounds, rework_round) - 1`) are wired across `JobDetailDrawer.tsx`, `Qc1ReviewPanel.tsx`, `Qc1DashboardPage.tsx`, `AnnotatorJobDrawer.tsx`, `AnnotatorJobDetailPage.tsx`, `AnnotatorReworkPage.tsx` (using `?include_errors=1`), and `AnnotatorDashboardPage.tsx`. `Qc1ReviewPanel.tsx` and `ReviewPanel.tsx` submit structured `verdict`, `is_missing_object`, `frame_number`, and `cvat_object_id` (and `ReviewPanel.tsx` uses `cvatFrameUrl` preserving `?org=`). `AnnotatorJobDetailPage.tsx` disables manual `object_count` on CVAT-linked jobs (`cvat_job_id != null`) and restricts `canReportDataIssue` from `approved`/`delivered`; `JobDetailDrawer.tsx` disables Lock on `delivered` and Assign post-QC1 (`getJobLockReason`). `CvatSyncButton.tsx` exposes `"Đếm lại object"` (`countObjects` toggle), and `DatasetsPage.tsx`/`BatchesPage.tsx` append `?org=` and check `getCvatStatus()`.
- **Notifications, Account, Deadlines & D06 Analytics:** `NotificationBell.tsx` uses server `all_count` / `unread_count` totals, `sortUnifiedNotifications`, category filter pills, and skips `due-*` IDs in `markProjectNotificationsRead`. `OverviewPage.tsx` displays `project.cvat_synced_at` (`CS08`) and `Qc2DashboardPage.tsx` renders `errors_by_severity`. `CurrentUser` includes `is_pm` and `projects`, `AccountSettingsPage.tsx` renders multi-org roles, and dead `teamLeaderName`/`team_leader_name` state was removed across shell and annotator views. `AnnotatorDashboardPage.tsx` and `AnnotatorJobsPage.tsx` split `?overdue=1` vs `?due_soon=1`. `AnnotatorAnalyticsPage.tsx` + `analyticsHelpers.ts` handle `previous_rank == null`, label hours provisionally (`"giờ phiên ước tính"`), align subtitle with `measured_objects ÷ total_hours`, and use `buildContiguousRateRuns` (`null` points break chart lines). `MetricCard.tsx` displays `"Chưa chốt công thức"` for `pending_definition` metrics (`CL02`, `CL05`, `CL11`, `NS04`, `DB02`/`DB03`).
- **Remaining UI parity gaps:** `getPermissionMatrix` / `updateDataset` / `bulk-move-batch` have no UI, and `NotificationBell.tsx` still polls every `60s`.
- **Zero `antd` footprint:** All 13 prior Ant Design 6 files were migrated to React Aria (`react-aria-components`) + Untitled UI primitives (`antd` and `@ant-design/icons` uninstalled; zero `antd` / `@ant-design` references in `frontend/src`, `frontend/package.json`, or `frontend/vite.config.ts`).
- **Vitest unit test baseline (`cd frontend && npm test` — 10 files, 48 tests passing in `1.08s`):**
  - `frontend/src/features/jobs/constants.test.ts`, `frontend/src/features/jobs/jobs.test.tsx`, `frontend/src/features/projects/projects.test.ts`, `frontend/src/shared/api/errors.test.ts`, `frontend/src/shared/api/tokenStorage.test.ts`, `frontend/src/shared/architecture.test.ts`, `frontend/src/shared/components/ui/uiPrimitives.test.tsx`, `frontend/src/shared/types/rbac.test.ts`, `frontend/src/shared/utils/cvat.test.ts`, `frontend/src/shared/utils/format.test.ts`.
- **Typecheck, lint, build & live browser status:** `npx tsc -b --noEmit`, `npm run lint`, `npm test` (`10` files / `48` tests), and `npm run build` (`2796` modules transformed, `542ms`, zero AntD chunks) all pass on the current working tree. Live 4-role Headless Chrome CDP verification (`Chrome/158.0.8127.88 --headless=new`, `seed_demo` org `#8`, `pm_demo` / `qc2_demo` / `qc1_demo` / `ann1_demo`) passed **25/25 checks** (`0` console errors, `0` uncaught JS exceptions, `0` unexpected HTTP `>= 400` responses), covering `ProjectSettingsPage` (all 9 fields + live `PATCH 200`), `ActivityLogPage`, `ProjectListPage` (`is_pm` gating), `OverviewPage` (`TD13`/`DH07`), `DatasetsPage`/`BatchesPage`, `DeliveryPage`, `JobsPage`/`JobDetailDrawer` Slideover, `Qc2DashboardPage` (`errors_by_severity`), `NotificationBell` (tabs + category filter), `AccountSettingsPage`, `RequireCap` blocking on `/settings` & `/activity`, `Qc1DashboardPage`/`Qc1WorkPage`, `Annotator*` views, and `404` isolation. Real CVAT-linked E2E checks (`NT02`) remain pending.
