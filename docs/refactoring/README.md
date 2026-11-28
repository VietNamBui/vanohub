# VanoHub refactoring documentation

Prepared: 2026-11-27 (reconciled 2026-11-28), Asia/Ho_Chi_Minh. Status: adopted and reconciled on `feature/annotator-qclv1` (`T00`/`T02` closed; `T05` Ant Design migration complete; `D01`–`D04` accepted — `D04` strict stock CVAT API-only with `PV04` intact and external CVAT extensions decoupled; `D05`–`D06` open with Dec 4 MVP defaults proposed).

This documentation supports the refactor already in progress. Start from the active local checkout and reuse completed work. The remote snapshots in [baseline.md](baseline.md) are reference evidence, not a replacement for the local working tree.

## Start here

1. Read the repository's existing `AGENTS.md` and the relevant scoped rules.
2. Read [plan.md](plan.md), then execute T00 to identify the active revision and work in progress.
3. Resolve only the decisions that affect the next task using [decisions.md](decisions.md).
4. Send one bounded assignment using [agent-workflow.md](agent-workflow.md).
5. Record one logical outcome in [changes.md](changes.md), with actual verification evidence.

## Document ownership

| Document | What it owns | Update trigger |
| --- | --- | --- |
| Existing `docs/platform-spec.md` | Product behavior, roles, workflow, KPI definitions | An accepted product decision changes |
| Existing `ARCHITECTURE.md` | Current system structure and entry points | Implemented boundaries or dependencies change |
| Existing `docs/mvp-checklist.md` | Product delivery status | An outcome is implemented and its evidence is known |
| Existing `AGENTS.md` and scoped rules | Repository execution rules and required gates | The operating policy changes |
| [plan.md](plan.md) | Task order, dependencies, acceptance, active handoff | Work starts, completes, or encounters a blocker |
| [baseline.md](baseline.md) | Revision-specific evidence and local adoption record | A new baseline is captured |
| [decisions.md](decisions.md) | Cross-cutting choices and their rationale | A decision is accepted or superseded |
| [agent-workflow.md](agent-workflow.md) | Model roles, retrieval, handoffs, file ownership | Coordination needs change |
| [changes.md](changes.md) | Meaningful refactor, UI, and API changes | A logical change is ready for review |
| [API contracts](../api/contracts.md) | Contract inventory, change procedure, proposal boundaries | An API surface or consumer expectation changes |
| [UI verification](../ui/verification.md) | Role, interaction, state, and API parity checks | A UI slice changes |
| [Security and verification](../operations/security-and-verification.md) | Transport policy and evidence requirements | Deployment boundaries or checks change |

The documents have different responsibilities. Keep full business formulas in the product specification; link to them from tasks and contracts. Git contains the exact patch. The change log explains intent, behavior, and evidence.

## Status vocabulary

- **Task:** planned, in progress, blocked, implemented, or closed.
- **Decision:** open, accepted, or superseded.
- **Evidence:** source observed, check passed, check failed, or not run.

A task can be implemented while verification remains incomplete. A historical source observation does not establish the state of the current local checkout. Close a task only when its acceptance criteria are met and applicable required gates pass, except for documented exceptions already allowed by repository policy. Failed, blocked, or unrun required checks keep the task open.

## Small addition to the existing AGENTS.md

Merge this paragraph into the existing documentation section after adopting the files:

> For the current refactor, use `docs/refactoring/README.md` and `docs/refactoring/plan.md`. Follow `docs/refactoring/agent-workflow.md` for compact handoffs and branch-aware retrieval. Record meaningful changes in `docs/refactoring/changes.md`. Preserve the existing product specification, scoped rules, and verification gates.

Do not replace the existing `AGENTS.md` with the entire plan. Add a new file only when a document's size, independent ownership, or lifecycle makes a split useful.

## First assignment for the local orchestrator *(completed on `0beace7`)*

> T00 captured the active worktree (`feature/issue-logger @ 0beace7`) in [baseline.md](baseline.md), resolved `D01`–`D03` from `8d66adc` in [decisions.md](decisions.md), synced [API contracts](../api/contracts.md), [UI verification](../ui/verification.md), and [security/verification](../operations/security-and-verification.md), and updated the active handoff in [plan.md](plan.md). Continue from Section 8 of [plan.md](plan.md).
