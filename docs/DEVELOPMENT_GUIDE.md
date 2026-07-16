# DEVELOPMENT GUIDE — UPeU Internado 360

## 1. Prerequisites

- Python **3.11+** (tested on 3.13).
- Windows, macOS or Linux. Commands below show Windows first.

## 2. Setup

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

macOS/Linux:
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt && cp .env.example .env
```

## 3. Create the schema (Alembic migrations)

The schema is managed by Alembic; the app no longer drops/recreates tables on
startup.

```bat
alembic upgrade head                             :: apply all migrations
alembic revision --autogenerate -m "message"     :: new migration from model changes
alembic downgrade -1                             :: revert the last migration
alembic current                                  :: show current revision
alembic history                                  :: list migrations
```

The database URL comes from `app.config` (`.env` `DATABASE_URL`); it is not
hardcoded in `alembic.ini` (see `migrations/env.py`).

## 3b. Seed the demo database

```bat
python -m app.seed            :: SAFE: seeds only when the database is empty
python -m app.seed --reset    :: DESTRUCTIVE: drop + recreate + reseed (demo reset)
```

Normal `python -m app.seed` is **non-destructive** — it populates an empty
(migrated) database and refuses to overwrite existing data. Use `--reset` only
to rebuild the demo dataset. Startup never drops data.

Typical first run:

```bat
alembic upgrade head
python -m app.seed
```

## 4. Run

```bat
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. API docs (debug only): `/api-docs`.

Change the port: `uvicorn app.main:app --reload --port 8001`.

## 5. Project conventions

- Layer order: **model → repository → service → route → template**.
- Business logic in services; queries in repositories; no logic in templates.
- Type hints + docstrings on public functions/classes.
- Use `get_logger(__name__)`; never `print`.
- Configuration only through `app/config.py` / `.env`.

## 6. How to add a new module (recipe)

1. **Model** — add a class in `app/models/…`, export it in
   `app/models/__init__.py`.
2. **Repository** — add a repository (or method) in
   `app/repositories/repositories.py`.
3. **Service** — put business logic in `app/services/…`.
4. **Route** — add a controller in `app/routes/…`; register the router in
   `app/main.py`.
5. **Template** — add a Jinja2 template extending `base.html`.
6. **Navigation** — add a `NavItem` in `app/services/navigation.py` with the
   roles that may see it.
7. **Docs** — update `DATA_DICTIONARY.md` and `CHANGELOG.md`.

## 7. Adding an agent

Implement `BaseAgent.run`, return an `AgentResponse`, and register it in
`AgentOrchestrator.__init__`. See AGENT_ARCHITECTURE.md §6.

## 8. Adding a deterministic rule

Add a function `(repos, today) -> list[AgentFinding]` in
`app/agents/rule_engine.py` and register it in the `RULES` dict. If it should
raise alerts, map its finding `code` to an alert category.

## 8b. Automated tests

```bat
python -m pytest
```

Runs against a **temporary** SQLite database (never the demo database) built
fresh each session by `tests/conftest.py`. Currently 118 tests covering
authentication, authorization/scope, students, sedes, coordinators, tutors,
rotations (incl. conflict detection), activity tracking (catalog, entry
workflow, tutor verification, progress math, monitoring, alerts), and the
evaluation workflow (criteria/scoring, area/final-score correctness, role
scope, status transitions, dashboard scoping) — all with CSRF and audit checks.

## 9. Manual test checklist

- [ ] `python -m app.seed` completes and prints the summary.
- [ ] Server starts without errors.
- [ ] Login works for all five demo accounts; wrong password is rejected.
- [ ] Admin dashboard shows 8 stat cards, both charts, ending-soon table,
      alerts and quick actions.
- [ ] Non-admin roles see the shared role dashboard and a filtered sidebar.
- [ ] `/agents` → "Ejecutar todos" creates executions visible in
      `/agent-executions`.
- [ ] `/alerts` shows the four seeded alerts.
- [ ] A random URL renders the styled 404 page.
- [ ] Logout returns to the login page.

## 10. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: app` | Run from the project root; ensure venv active. |
| Empty dashboard | Run `python -m app.seed` first. |
| Charts/icons missing | CDN blocked/offline — content still works; assets are optional. |
| Port in use | Use `--port 8001`. |
| DB looks stale | Re-run `python -m app.seed` (it recreates tables). |

## 11. Future tooling (Parts 2 & 3)

- Alembic migrations for schema evolution and the PostgreSQL move.
- `pytest` suite (unit tests for services/rules; route smoke tests).
- Linting/formatting (ruff/black) and pre-commit hooks.

---

## Batch 2E — running documents/incidents/reports

New runtime dependencies (already in `requirements.txt`): `openpyxl`, `fpdf2`
(pure-Python; pulls Pillow + fonttools). Install with `pip install -r requirements.txt`.

Migration: `alembic upgrade head` (revision `b2e4d9c17a05`). Rebuild demo data:
`python -m app.seed --reset`.

Attachment storage dir (`var/attachments/`, outside `app/static`) is created on
first upload; configurable via `ATTACHMENT_STORAGE_DIR` / `ATTACHMENT_MAX_MB`.

Key modules: `app/services/{document,incident,attachment,report,export}_service.py`,
`app/services/numbering.py`, `app/routes/{document,incident,report}_routes.py`,
`app/agents/incident_monitoring_agent.py`.

Tests: `pytest tests/test_documents.py tests/test_attachments.py
tests/test_incidents.py tests/test_reports.py tests/test_2e_security.py`.

---

## Batch 2F — bulk import & grades

Runtime deps unchanged (`openpyxl` already present; `.xlsm` read via openpyxl).
Migration: `alembic upgrade head` (revision `c3f7a1b9d2e6`). Rebuild demo data:
`python -m app.seed --reset`.

Config: `IMPORT_MAX_MB` (8), `IMPORT_MAX_ROWS` (2000), `IMPORT_STORAGE_DIR`
(`var/imports`, outside static), `IMPORT_RETAIN_FILES` (false).

Key modules: `app/services/{excel_reader,import_profiles,import_service,grade_service,numbering}.py`,
`app/routes/{import,grade}_routes.py`, models `app/models/{imports,grades}.py`.

Tests: `pytest tests/test_imports.py tests/test_grade_imports.py`.

Extending: add an import profile by subclassing `ImportProfile` in
`import_profiles.py` (declare `fields`, `unique_field`, `allowed_roles`, and
implement `resolve/find_existing/validate/apply`) and register it in
`_MASTER_PROFILES` (or via `get_profile` for domain profiles). Reuse an existing
service `_validate` in `validate()` so business rules stay authoritative.
