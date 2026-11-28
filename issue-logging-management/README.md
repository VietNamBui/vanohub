# `issue-logging-management` Snapshot (Reference Sources)

Copied into `feature/annotator-qclv1` strictly as reference material for folding analytics/dashboard patterns into VanoHub (see [fold-issue-logging-management-plan.md](../docs/refactoring/fold-issue-logging-management-plan.md)).

## Provenance

| Directory | Source Repository | Branch | HEAD | Excluded Paths |
| --- | --- | --- | --- | --- |
| `cvat-dashboard/` | `../cvat-dashboard` | `feature/issue-logging-management` | `6091115` | `.git`, `node_modules`, `dist`, `db.sqlite3`, `.env`, caches, `tsconfig.tsbuildinfo` |

## Usage Guardrail

- External CVAT extensions are **intentionally excluded and kept completely decoupled** from VanoHub (`PV04` — stock `cvat-base` REST APIs only). Do **not** vendor or import external CVAT extension code into this repository.
- Do **not** wire `cvat-dashboard` directly into `backend/` or `frontend/` imports, Ant Design, or the conflicting 5-tier workflow state machine (`qc1 -> qc2` skip, `DEPT_HEAD`, `verify_gate`, `recall_from_annotator`).
- Keep all reference code outside `backend/` and `frontend/` until folded cleanly per the implementation plan.
