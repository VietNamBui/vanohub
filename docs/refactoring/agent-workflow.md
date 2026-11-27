# Agent workflow

## Purpose and authority

Coordinate ongoing refactoring with compact, reviewable handoffs. Read [the package overview](./README.md), [plan](./plan.md), and [baseline](./baseline.md) when onboarding or after a rebase; on later tasks, read the active handoff in [plan.md](./plan.md) and relevant changed sections rather than reloading the entire document set.

The installed repository's `AGENTS.md`, scoped `.agents/rules/`, and CI remain binding. `docs/platform-spec.md` remains the product authority. This workflow neither replaces those rules nor creates a blanket approval requirement. Record contradictions in [decisions](./decisions.md). Stop only the affected scope when a domain decision is unresolved; continue independent work.

## Roles and ownership

Retain the user-reported configuration: **Neon Extra High as orchestrator; Hydrogen Extra High as executor**. Default to one orchestrator and one executor. These are role assignments, not claims about model capabilities, context limits, speed, or token savings.

The orchestrator selects a bounded unit, identifies contract and domain risks, assigns ownership, and reviews evidence. The executor confirms current source, edits owned files, runs relevant checks, and returns a compact result. Add parallel work only for independently owned scopes with a clear integration point.

Pass the executor its task and selected source/specification references, not the entire orchestration conversation. Keep durable decisions and outcomes in versioned docs. If MCP can expose those records, use references to the same content instead of maintaining a competing copy. Review the diff and new evidence; reopen analysis only when something material changed.

Assign one writer at a time to shared contracts, migrations, generated schemas, and shared documentation. Readers may review concurrently. Transfer ownership explicitly before another agent edits the same file. Avoid overlapping implementation and speculative redesign.

## Establish the working context

Before each new unit, record the worktree root, branch or detached-HEAD state, HEAD SHA, relevant dirty files and diff identity, and available index metadata. A branch name or HEAD alone cannot identify uncommitted source. Keep secrets and unrelated diffs out of handoffs.

The local `codebase-memory-mcp` project `media-bang-Work-projects-vanohub` indexes the repository (`generation 2026-11-27T04:48:39Z`; see [baseline.md](./baseline.md)). Subagents without MCP tools must not claim MCP access and must read exact files directly from disk using supplied paths and targeted text searches.

Compare the index's reported repository/worktree, revision, indexed scope, and update information with the working context. Use a reported index identity or fingerprint when available; do not invent one or treat a timestamp alone as proof of freshness. Confirm whether uncommitted changes are included. If freshness cannot be established, use indexed results as leads and confirm relevant current files directly.

Recheck context after branch switches, worktree changes, rebases, generated-file updates, or edits affecting the task. Refresh only the stale scope when the installed tool supports it. Do not rescan or reindex the entire repository every turn. A full refresh needs a concrete coverage or correctness reason.

## Retrieve and implement narrowly

Start from the task's symbols, routes, state transitions, and contract identifiers. Retrieve a bounded graph neighborhood or focused snippets sufficient to trace producer, consumer, authorization, and tests. Inspect current source before relying on a result. Expand only to resolve a specific missing dependency or contradiction; do not paste the full repository into either agent's context.

For generated code, dynamic references, registrations, or uncertain graph coverage, use narrow path/text searches and inspect generators or registration points. Lack of an indexed edge is not proof that a caller does not exist. There are no hard token quotas: retain the evidence necessary for correctness and omit repeated discovery transcripts.

Decisions `D01`–`D03` (CVAT Org→`Project` / Project→`Dataset` / Task→`Batch` / Job→`Job`, Hybrid A2 `confirm-qc2` + frame-level QC2, `CvatAccount` + `schedule_assignee_push`) are accepted in [decisions.md](./decisions.md). Link open decisions (`D04`–`D06`) rather than guessing unresolved metrics or semantics.

Consume CVAT through its API. Do not introduce direct CVAT PostgreSQL or NAS access. Preserve the repository's four-role model, four-eyes restrictions, project isolation, workflow ownership, locks, audit trail, and notification rules. Track API compatibility in [contracts](../api/contracts.md), visible behavior in [UI verification](../ui/verification.md), and operational checks in [security and verification](../operations/security-and-verification.md). New telemetry or API designs remain proposals until implemented and evidenced.

## Six-field handoffs

Use references and short statements; include neither private reasoning nor tool-call transcripts.

```text
TASK
1. Outcome: bounded objective and acceptance criteria.
2. Context: worktree, branch, HEAD, dirty scope, index freshness.
3. Evidence: relevant source, specification, and decision references.
4. Ownership: executor, writable files, shared-file owner.
5. Constraints: domain rules, contracts, dependencies, exclusions.
6. Checks: required evidence and expected return point.

RESULT
1. Status: planned / in progress / implemented / blocked / closed; outcome.
2. Context: worktree, branch, HEAD, dirty scope, index changes.
3. Changes: owned files, logical effect, change-entry reference.
4. Compatibility: API/UI/domain/data impact and unresolved decisions.
5. Verification: commands or observations, results, unrun checks.
6. Handoff: risks, next action, ownership transfer, commit or none.
```

## Verification and completion

During editing, run targeted checks that address the changed behavior. Before concluding a task in the application repository, follow its existing AGENTS/CI gates; confirm their current commands from the checkout. The supplied snapshot requires:

- `backend/` (local Pipenv; CI runs from repo root after `pipenv install --dev --system`): `pipenv run ruff check ../backend` and `pipenv run pyright -p ../pyproject.toml` *(bare global `pyright` outside Pipenv fails with missing imports)*.
- `backend/`, with PostgreSQL 17: `pipenv run python manage.py check`, `pipenv run python manage.py makemigrations --check --dry-run`, and `pipenv run python manage.py test`.
- `frontend/`: `npm test` (Vitest unit tests), `npx tsc -b --noEmit`, `npm run lint`, and `npm run build`.
- Relevant roles in a live browser when routes, capability guards, forms, drawers, or workflow transitions change.

Report failed, blocked, and unrun checks explicitly. A targeted pass does not imply full gates passed. Keep implementation status separate from verification. Record each meaningful refactor/UI/API unit once in the [change log](./changes.md), including compatibility and evidence. Follow existing commit/push authorization rules; this package authorizes neither.
