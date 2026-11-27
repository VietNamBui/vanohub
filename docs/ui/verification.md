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

## 6. Reconciled frontend baseline (`0beace7`)

- **UI terminology & route guards:** `frontend/src/app/router.tsx` guards routes via `RequireCap` matching backend `Cap` values; UI surfaces use CVAT-aligned Organization → Project → Task → Job labels (verified across `ProjectListPage.tsx`, `DatasetsPage.tsx`, `BatchesPage.tsx`, `ProjectLayout.tsx`).
- **Hybrid A2 `confirm-qc2` wiring:** `frontend/src/features/projects/pages/BatchesPage.tsx` renders `ConfirmQc2Dialog` (gated by `b.ready_for_qc2_confirm` and `can('manage_data')`) calling `confirmBatchQc2` (`POST /api/projects/{id}/batches/{batchId}/confirm-qc2/`).
- **Structured `ReviewError` inputs:** Both `frontend/src/features/quality/qc1/Qc1ReviewPanel.tsx` and `frontend/src/features/quality/qc2/ReviewPanel.tsx` submit `verdict` (`fail` | `edge`), `is_missing_object`, `frame_number`, and `cvat_object_id` (enforcing `verdict='fail'` and `cvat_object_id=null` when `is_missing_object` is checked; `ReviewPanel.tsx` also provides quick-fill buttons from `sample.frames`).
- **Pending-definition analytics rendering:** `frontend/src/shared/components/ui/MetricCard.tsx` displays `"Chưa chốt công thức"` when `status === 'pending_definition'` (`CL02`/`CL05`/`CL11`, `NS04`, `DB02`/`DB03`).
- **Remaining `antd` footprint (0 files — completed):** All 13 remaining Ant Design 6 files were migrated to React Aria (`react-aria-components`) + Untitled UI primitives (`ToastProvider`/`useToast`, `Slideover`, rewritten `StateView`, `ProjectSwitcher`, `MemberSelect`, `CvatSyncButton`, `JobStatusTag`, `AssigneeSelect`, `AssignModal`, `JobDetailDrawer`, `QueuePage`, `JobsPage`, `AuditsPage`), legacy `.page`/`.page-header` CSS and `vite.config.ts` AntD chunk groups were removed, and `antd` / `@ant-design/icons` were uninstalled (`rg -n "antd|@ant-design" frontend/src frontend/vite.config.ts frontend/package.json` returns zero matches).
- **Vitest unit test baseline (`cd frontend && npm test` — 4 files, 13 tests passing):**
  - `frontend/src/features/jobs/constants.test.ts` — 3 tests (9 lifecycle statuses + `STAGE_LABELS`, `batch.confirm_qc2` + Project/Task labels, `formatDeadlineCountdown`)
  - `frontend/src/shared/types/rbac.test.ts` — 2 tests (flat 4-role model + `GRANTABLE_ROLES`, 16 backend capabilities)
  - `frontend/src/shared/utils/format.test.ts` — 6 tests (`APP_TIME_ZONE='Asia/Ho_Chi_Minh'`, UTC+7 midnight formatting, date-only strings, datetime-local round-trip, CSV timestamps, null/invalid handling)
  - `frontend/src/shared/api/errors.test.ts` — 2 tests (HTTP/network classification, DRF detail/field/HTML error extraction)
- **Typecheck, lint, build & live browser check:** `npx tsc -b --noEmit`, `npm run lint`, `npm test`, and `npm run build` (`vite build` in `513ms`, zero AntD chunks) all pass. Strict multi-role Headless Chrome CDP verification across `pm_demo`, `qc2_demo`, `qc1_demo`, and `ann1_demo` passed **37/37 checks** with zero JS exceptions, zero console errors (including zero AntD deprecation warnings), and interactive checks on `confirm-qc2`, `AuditWorkPage` QC2 Pass, `JobsPage`/`JobDetailDrawer` Slideover, `QueuePage`, `AuditsPage` Slideover, `404` isolation, and `RequireCap` guards; live end-to-end checks with a real linked CVAT server (`NT02`) remain pending.
