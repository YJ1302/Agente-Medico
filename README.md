# UPeU Internado 360

**Agentic platform for the planning, monitoring and evaluation of the Medical Internship.**
Universidad Peruana Unión — Escuela Profesional de Medicina Humana.

> **Phase 1 · Part 1** — Foundation, rulebook, data model, authentication
> mockup, dashboard shell and agent-ready architecture.

---

## What this is

A professional, runnable prototype of the platform that will manage the ~365‑day
medical internship of UPeU students (cycles 13 and 14) across MINSA and EsSalud
teaching sites (*sedes*). This deliverable establishes the foundation: data
model, roles, authentication, the institutional UI shell, a fully working
administrator dashboard, and a deterministic **agent-ready** architecture.

> ⚠️ **Privacy:** This prototype contains **fictional demonstration data only**.
> It must **not** be used to store identifiable patient clinical information.

## Tech stack

| Layer     | Technology |
|-----------|------------|
| Backend   | Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic, Jinja2 |
| Database  | SQLite (prototype) — designed for a future PostgreSQL migration |
| Frontend  | HTML5, modern CSS, vanilla JavaScript, Bootstrap Icons, Chart.js (CDN) |
| Auth      | Session cookie (signed), bcrypt password hashing |
| Agents    | Internal deterministic agents (no external AI API in Part 1) |

## Project layout

```
Roger Agent/
├─ app/
│  ├─ main.py               # FastAPI app factory & entry point
│  ├─ config.py             # Centralized settings (.env)
│  ├─ database.py           # Engine, session, Base, init_db
│  ├─ security.py           # bcrypt hashing
│  ├─ dependencies.py       # Auth guards / session identity
│  ├─ templating.py         # Jinja2 env + shared render()
│  ├─ seed.py               # Fictional demo data seeder
│  ├─ models/               # SQLAlchemy models
│  ├─ schemas/              # (reserved for Pydantic API schemas)
│  ├─ repositories/         # Data-access layer
│  ├─ services/             # Business logic
│  ├─ agents/               # Agent-ready architecture + rule engine
│  ├─ routes/               # HTTP controllers
│  ├─ templates/            # Jinja2 templates
│  └─ static/               # CSS / JS / images
├─ docs/                    # Project rulebook & documentation
├─ requirements.txt
├─ .env.example
└─ README.md
```

## Quick start (Windows)

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
alembic upgrade head          :: create/upgrade the schema via migrations
python -m app.seed            :: load demo data (only if the DB is empty)
uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000>.

> On macOS/Linux use `source venv/bin/activate` and `cp .env.example .env`.

### Database migrations (Alembic)

The schema is managed by Alembic — the app no longer drops/recreates tables on
startup.

```bat
alembic upgrade head                             :: apply all migrations
alembic revision --autogenerate -m "message"     :: new migration from model changes
alembic downgrade -1                             :: revert the last migration
alembic current                                  :: show current revision
```

Current head: `c3f7a1b9d2e6` (Batch 2F — bulk import & academic grade
foundation), on top of `b2e4d9c17a05` (Batch 2E), `ca5acdae8455` (Batch 2D),
`e6118382e890` (Batch 2C), `0e5f841e0967` (Batch 2B), `7fb2a9a545a7` (Batch 2A)
and baseline `407858b8a29f`.

Operational modules implemented so far in Part 2: **Internos**, **Sedes**,
**Coordinadores de Sede**, **Tutores**, **Rotaciones** (list + timeline +
conflict-validated CRUD + status workflow + tutor assignment + automatic pending
evaluation), **Actividades** (official catalog from the 4 specialty documents +
student entry log + tutor verification + progress tracking + coordinator
monitoring), **Evaluaciones** (full 15-criterion scoring workflow with
tutor→coordinator approval and server-authoritative totals), **role-specific
dashboards** for all 5 roles, and **Batch 2E — Documentos, Incidencias y
Reportes**: formal document lifecycle (13 types, server-generated `DOC-YYYY-NNNN`
codes, templates, formal PDF), incident management (13 types, 4 severities,
critical alerts), secure local **attachments** (extension+MIME+magic-byte
validated, stored outside the public folder), **14 reports** with Excel/PDF
exports and a consolidated **student internship summary**, plus visibility levels
(normal/restricted/confidential), and **Batch 2F — Importación masiva y notas
académicas**: a safe Excel (.xlsx/.xlsm) bulk-import wizard (upload → sheet →
column mapping → validate → preview → confirm → transactional import) for
students, sedes, tutors, coordinators, rotations and grade components — with
duplicate detection, import modes (incl. all-or-nothing), downloadable error
reports and import history — plus the academic **grade foundation** (configurable
schemes; **no final grade until weights are confirmed**; blank kept distinct from
zero) — all role-scoped, audited and CSRF-protected.

A top-bar **Traducir** button toggles the interface chrome between Spanish
(default) and English, fully offline.

**Seeding vs. resetting** (destructive reset is separated from normal use):

```bat
python -m app.seed            :: safe: seeds only when the database is empty
python -m app.seed --reset    :: DESTRUCTIVE: rebuilds demo data from scratch
```

## Demo credentials

Shown on the login page when `DEMO_MODE=true`. Password for all: **`Demo123!`**

| Role                    | Email |
|-------------------------|-------|
| Administrator           | `admin@internado360.demo` |
| University Coordinator  | `coordinator@internado360.demo` |
| Sede Coordinator        | `sede@internado360.demo` |
| Tutor                   | `tutor@internado360.demo` |
| Intern Student          | `student@internado360.demo` |

## Documentation

All project documentation lives in [`/docs`](docs/):

- [PROJECT_RULEBOOK.md](docs/PROJECT_RULEBOOK.md)
- [BUSINESS_RULES.md](docs/BUSINESS_RULES.md)
- [USER_ROLES_AND_PERMISSIONS.md](docs/USER_ROLES_AND_PERMISSIONS.md)
- [DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md)
- [ACTIVITY_CATALOG_SOURCE_MAP.md](docs/ACTIVITY_CATALOG_SOURCE_MAP.md)
- [ACTIVITY_WORKFLOW.md](docs/ACTIVITY_WORKFLOW.md)
- [SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md)
- [AGENT_ARCHITECTURE.md](docs/AGENT_ARCHITECTURE.md)
- [UI_DESIGN_SYSTEM.md](docs/UI_DESIGN_SYSTEM.md)
- [SECURITY_AND_PRIVACY_RULES.md](docs/SECURITY_AND_PRIVACY_RULES.md)
- [DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md)
- [DEMO_GUIDE.md](docs/DEMO_GUIDE.md)
- [DOCUMENT_WORKFLOW.md](docs/DOCUMENT_WORKFLOW.md)
- [INCIDENT_WORKFLOW.md](docs/INCIDENT_WORKFLOW.md)
- [REPORT_CATALOG.md](docs/REPORT_CATALOG.md)
- [FILE_UPLOAD_SECURITY.md](docs/FILE_UPLOAD_SECURITY.md)
- [EXCEL_IMPORT_WORKFLOW.md](docs/EXCEL_IMPORT_WORKFLOW.md)
- [IMPORT_PROFILE_CATALOG.md](docs/IMPORT_PROFILE_CATALOG.md)
- [GRADE_COMPONENT_MODEL.md](docs/GRADE_COMPONENT_MODEL.md)
- [GRADE_IMPORT_RULES.md](docs/GRADE_IMPORT_RULES.md)
- [CHANGELOG.md](docs/CHANGELOG.md)
- [DECISIONS_LOG.md](docs/DECISIONS_LOG.md)

## Testing

```bat
python -m app.seed          # rebuild demo DB
uvicorn app.main:app --reload
python -m pytest -q          # automated suite — 198 tests
```

Then verify: login for each role, the admin dashboard cards/charts, the Agents
page ("Ejecutar todos"), the Alerts page, and the Batch 2E **Documentos**,
**Incidencias** and **Reportes** modules. See
[DEMO_GUIDE.md](docs/DEMO_GUIDE.md) for the full script.

## License / status

Internal prototype deliverable for Universidad Peruana Unión. Not for production
use as-is. © 2026.
