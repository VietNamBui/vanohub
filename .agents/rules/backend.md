---
trigger: glob
globs: "**/backend/**/*.py, **/backend/Pipfile, **/pyproject.toml"
description: "Backend rules for Django 6, DRF, PostgreSQL 17 locking, 4-layer validation, migrations, and typing."
---

# Backend Engineering Rules (Django / DRF / PostgreSQL)

- **Transactions & PostgreSQL row locking:**
  - Wrap multi-record mutations, state transitions, and bulk actions in `transaction.atomic()`.
  - When locking `Job` or models using `select_related()` over nullable foreign keys, always use `select_for_update(of=("self",))` — PostgreSQL rejects plain `select_for_update()` on the nullable side of an outer join. Use `select_for_update(skip_locked=True)` for queue claims.
- **4-layer validation:**
  1. **API boundary:** Validate request payloads with DRF serializers and extract narrowed `dict[str, Any]` data via `accounts.validation.validated_dict(serializer)`.
  2. **Model invariants:** Enforce cross-field and cross-project ownership checks in `Model.clean()` (e.g., `batch.dataset.project_id == project_id`).
  3. **Database integrity:** Back numeric bounds, positive external IDs, uniqueness, and required state combinations (e.g., completed `Audit` requires non-empty `decision`) with PostgreSQL `CheckConstraint` / `UniqueConstraint` in `Meta.constraints`.
  4. **External CVAT contracts:** Parse all CVAT REST responses and sync outputs through strict Pydantic v2 models (`ConfigDict(strict=True, ...)`) in `backend/cvat_integration/schemas.py`.
- **Migrations:**
  - Always generate a migration for model, field, index, or constraint changes; `python manage.py makemigrations --check --dry-run` must pass clean.
  - Never modify already-committed migrations.
- **Delete protection:** Preserve `on_delete=models.RESTRICT` on `ReviewError.category` and `on_delete=models.PROTECT` on `Delivery.batch` so referenced catalogs and delivered batches cannot be deleted individually while keeping project cascade intact where intended.
- **Typing & linting (`pyproject.toml`):**
  - Keep `ruff check backend` (`py312`, line-length `120`, `E/F/I/UP/B/SIM/PERF`) and `pyright` (`standard` mode) clean.
  - Declare Django reverse relations, `_id` attributes, and `get_*_display()` signatures inside `if TYPE_CHECKING:` blocks instead of `# type: ignore`.
- **Testing:**
  - Tests run on PostgreSQL 17 — never rely on SQLite behavior.
  - Reuse `accounts.testing.ProjectFixture` and cover RBAC (`404` vs `403`), four-eyes conflicts, atomic transitions, and DB `IntegrityError` constraints (`backend/projects/test_integrity.py`).
