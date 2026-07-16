# SYSTEM ARCHITECTURE — UPeU Internado 360

## 1. Style: modular monolith

A single FastAPI application organized into clear layers. This keeps the
prototype lightweight and easy to run while enforcing separation of concerns so
modules can later be extracted if needed.

```
                    ┌──────────────────────────────┐
  Browser  ───────► │  Routes (thin controllers)    │
                    └──────────────┬───────────────┘
                                   │ depends on
                    ┌──────────────▼───────────────┐
                    │  Services (business logic)    │
                    └───────┬──────────────┬────────┘
                            │              │
              depends on    │              │  uses
                    ┌───────▼──────┐  ┌────▼─────────────┐
                    │ Repositories │  │ Agents /         │
                    │ (data access)│  │ Rule engine      │
                    └───────┬──────┘  └────┬─────────────┘
                            │              │
                    ┌───────▼──────────────▼───────┐
                    │  Models (SQLAlchemy ORM)      │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  Database (SQLite → Postgres) │
                    └──────────────────────────────┘
```

## 2. Layers and responsibilities

| Layer | Location | Responsibility |
|-------|----------|----------------|
| Config | `app/config.py` | Centralized typed settings from `.env`. |
| Templating | `app/templating.py` | Jinja2 env + shared render context. |
| Routes | `app/routes/` | HTTP controllers; parse request, call a service, return a template/redirect. No business logic. |
| Services | `app/services/` | Business logic and orchestration (auth, dashboard, alerts, navigation, students, sedes, staff, rotations, rotation conflicts, evaluation catalog, **activity catalog**, **student activity workflow**, **privacy validation**, audit). |
| Reference data | `app/data/` | Static domain data as code — `activity_catalog.py` is the single source of truth for the official activity/procedure catalog (read by both the seed script and the admin import-preview page). |
| i18n | `app/i18n.py` | Session language toggle; translates the interface chrome (ES default / EN). |
| Repositories | `app/repositories/` | The only place SQL/ORM queries are built. |
| Models | `app/models/` | ORM schema, mixins, enums. |
| Agents | `app/agents/` | Base agent, orchestrator, rule engine, mock agents. |
| Security | `app/security.py` | Password hashing/verification. |
| Dependencies | `app/dependencies.py` | Auth guards & session identity. |

## 3. Request lifecycle (example: dashboard)

1. `GET /dashboard` hits `dashboard_routes.dashboard`.
2. `require_identity` dependency reads the signed session cookie (else redirect
   to `/login`).
3. `AlertService.refresh_from_rules()` runs the deterministic rules and creates
   any new alerts.
4. `DashboardService.build_admin_dashboard()` assembles stats, chart series,
   tables via repositories.
5. The route serializes chart data to JSON and calls `render(...)`.
6. `render` injects shared context (app metadata, role-filtered navigation,
   identity) and returns the Jinja2 `TemplateResponse`.

## 4. Data layer

- SQLAlchemy 2.0 declarative models on a shared `Base`.
- Engine/session in `app/database.py`; `get_db` yields a request-scoped session.
- SQLite for the prototype; the URL-driven engine makes PostgreSQL a
  configuration change. Types and mixins are chosen to be portable.
- `init_db()` creates all tables on startup; `app/seed.py` loads demo data.

## 5. Cross-cutting concerns

- **Configuration:** one `Settings` object (pydantic-settings), cached.
- **Logging:** `app/logging_config.py`, structured, level-controlled.
- **Sessions:** Starlette `SessionMiddleware`, signed with `SECRET_KEY`.
- **Errors:** global handlers for auth redirect, 404 and 500 render styled
  pages.
- **Static assets:** served from `app/static`; icons/charts via optional CDN.

## 6. Extensibility & production readiness

- **New module:** add model → repository → service → route → template.
- **PostgreSQL:** change `DATABASE_URL`; introduce Alembic migrations (Part 2).
- **AI agents:** implement `BaseAgent` with an LLM call; register in the
  orchestrator. No caller changes required (see AGENT_ARCHITECTURE.md).
- **API surface:** FastAPI can expose JSON endpoints alongside the HTML app for
  a future SPA or integrations; Pydantic schemas belong in `app/schemas/`.

## 7. Deployment notes (future)

- Run under `uvicorn`/`gunicorn` with multiple workers behind a reverse proxy.
- Set `APP_ENV=production`, `DEBUG=false`, a strong `SECRET_KEY`, `https_only`
  cookies (already enabled when `is_production`).
- Move secrets to a managed secret store; enable centralized logging and DB
  backups.

---

## Batch 2E — Documents, Incidents & Reports layer

Same layered pattern (routes → services → repositories → models):

- **Models** (`operations.py`): extended `DocumentRecord` / `Incident`; new
  polymorphic `Attachment` and `StatusHistory`; `DocumentTemplate`;
  `DocumentSequence` (numbering).
- **Services**: `document_service.py`, `incident_service.py` (guard-clause
  transitions, record-level scope, append-only history, alert refresh),
  `attachment_service.py` (secure storage), `report_service.py` (14 reports,
  scope-first), `export_service.py` (openpyxl + fpdf2 primitives, formal PDF),
  `numbering.py` (concurrency-safe codes).
- **Routes**: `document_routes.py`, `incident_routes.py`, `report_routes.py`
  (thin controllers; POST+CSRF mutations only; the `/documents /incidents
  /reports` Part 1 placeholders were removed).
- **Agents**: enhanced deterministic `DocumentAgent`; new
  `IncidentMonitoringAgent`; 8 new rule-engine rules feeding `AlertService`.
- **Migration**: `b2e4d9c17a05`.

Files stored under `var/attachments/` (outside `app/static`), served only via
authorized routes.

---

## Batch 2F — Bulk import & grade foundation layer

Same layered pattern:

- **Models**: `imports.py` (`ImportBatch`, `ImportRow`), `grades.py` (`GradeScheme`,
  `GradeComponentDefinition`, `StudentGradeComponent`, `GradeComponentHistory`).
- **Services**: `excel_reader.py` (safe workbook reading/validation),
  `import_profiles.py` (6 profiles reusing existing validators + rotation conflict
  engine), `import_service.py` (upload→map→validate→confirm, single-transaction,
  modes, stale/duplicate-confirmation guards, error report), `grade_service.py`
  (grade-import profile + scheme viewing/approval; never computes a final grade
  without confirmed weights), `numbering.py` (`IMP-YYYY-NNNN`).
- **Routes**: `import_routes.py` (wizard), `grade_routes.py` (scheme matrix + approve).
- **Migration**: `c3f7a1b9d2e6`.

Uploaded files live under `var/imports/` (outside `app/static`), deleted after
import. Grade imports flow through the generic `ImportBatch`/`ImportRow` pipeline
(D-035) while the grade domain tables hold the persisted scores + history.
