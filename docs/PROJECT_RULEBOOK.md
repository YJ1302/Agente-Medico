# PROJECT RULEBOOK — UPeU Internado 360

Authoritative rules for the project. When any other document or code conflicts
with this rulebook, this rulebook wins (except where a more recent 2026 source
document changes a business fact — see §Business Priority).

## 1. Project objective

Build an agentic institutional platform for the planning, monitoring and
evaluation of the ~365‑day medical internship of Universidad Peruana Unión
students (cycles 13 and 14) across MINSA and EsSalud teaching sites (*sedes*).

## 2. Scope of Phase 1 (this deliverable — Part 1)

- Foundation: modular monolithic FastAPI application, runnable locally.
- Data model for the full future system (professionally designed, expandable).
- Authentication mockup with seeded accounts (5 roles), bcrypt hashing.
- Institutional UI shell: login, layout, collapsible sidebar, top bar,
  notifications, user menu, responsive mobile navigation, empty/loading/error
  states, 404/500 pages.
- Fully styled **administrator dashboard** with stats, charts, tables, agent
  panel and quick actions.
- Placeholder pages for every future module.
- **Agent-ready architecture**: base agent, orchestrator, deterministic rule
  engine, and four mock agents returning structured responses.
- Rulebook and full documentation set.

## 3. Out of scope (Part 1)

- Full CRUD for every module (Parts 2 & 3).
- File uploads (architecture reserved, not implemented).
- External AI API integration (agents are deterministic mocks).
- Public registration, password reset, email delivery.
- Production deployment, PostgreSQL migration execution.
- Real integrations with MINSA/EsSalud/university systems.

## 4. Naming conventions

- **Python:** modules & functions `snake_case`; classes `PascalCase`;
  constants `UPPER_SNAKE_CASE`.
- **Database tables:** plural `snake_case` (e.g. `rotation_assignments`).
- **Routes/URLs:** kebab or single-word lowercase (e.g. `/agent-executions`).
- **Templates:** `snake_case.html`; partials under `templates/partials/`.
- **Roles codes:** fixed constants in `app/models/user.py`
  (`admin`, `university_coordinator`, `sede_coordinator`, `tutor`, `student`).

## 5. Folder conventions

Follow the layout in the README. New code goes in the layer that matches its
responsibility: models → schemas → repositories → services → routes →
templates. Agents live under `app/agents/`.

## 6. Coding standards

- Type hints and docstrings on public functions and classes.
- Business logic lives in **services**, never in routes or templates.
- Data-access/query construction lives only in **repositories**.
- Centralized configuration via `app/config.py` (no scattered `os.getenv`).
- Use the shared logger (`app.logging_config.get_logger`) — no `print`.
- Handle errors explicitly; never leave a route able to 500 on expected input.
- No dead code, no `TODO` standing in for required functionality in Part 1.

## 7. Database rules

- Every table has `created_at` and `updated_at`.
- Use soft-delete (`is_deleted`, `deleted_at`) and `is_active` instead of
  physical deletes where history matters.
- Consistent integer surrogate primary keys in Part 1 (see DECISIONS_LOG.md on
  the UUID trade-off). Relationships via foreign keys; avoid duplicated data.
- SQLite-compatible types only; keep the schema PostgreSQL-portable.
- Schema changes must be reflected in `DATA_DICTIONARY.md`.

## 8. UI rules

- Follow `UI_DESIGN_SYSTEM.md` (palette, spacing, components).
- Light, clean, medical-academic; never an excessively dark interface.
- Responsive for laptop, tablet and mobile.
- No business logic in templates — only presentation and simple iteration.
- Reuse partials/components; do not duplicate markup.

## 9. Security rules

- Passwords stored only as bcrypt hashes.
- Session cookie signed with `SECRET_KEY`; http-only, same-site lax.
- Role-based access control enforced in dependencies/services.
- No hardcoded production secrets; configuration via `.env`.
- See `SECURITY_AND_PRIVACY_RULES.md` for the complete policy.

## 10. Validation rules

- Validate and normalize all user input (login form, future forms).
- Server-side validation is authoritative; client-side is convenience only.
- Reject rather than coerce ambiguous input.

## 11. Documentation rules

- Documentation in `/docs` must stay consistent with the code.
- Any architectural or business-rule decision is recorded in
  `DECISIONS_LOG.md`; user-facing changes in `CHANGELOG.md`.

## 12. Git workflow recommendations

- Trunk-based with short-lived feature branches: `feat/…`, `fix/…`, `docs/…`.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `refactor:`…).
- One logical change per commit; keep the seed/data separate from code changes.
- PRs reference the affected docs and update them in the same change.

## 13. Change-control process

1. Propose the change (issue/ticket) with rationale.
2. If it alters business workflow or data model, record it in `DECISIONS_LOG.md`
   **before** implementation.
3. Implement with tests/verification.
4. Update `/docs` and `CHANGELOG.md`.
5. Review and merge.

## 14. Non-negotiable rules

- **R1 — No real patient data.** No identifiable patient clinical information
  may ever be stored. Seed and demo data must be fictional/anonymized.
- **R2 — 2026 documents take priority** over 2024 documents when business facts
  differ (Business Priority).
- **R3 — No business logic in templates.**
- **R4 — Auditability.** All important actions must eventually support audit
  logging (`AuditLog` schema is provided in Part 1).
- **R5 — Human-in-the-loop AI.** AI-generated recommendations require human
  approval. No agent sends a final institutional communication autonomously.

---

## Batch 2E addendum — Documents, Incidents, Reports

- Do not rebuild completed modules; Batch 2E adds documents, incidents, secure
  attachments, reports/exports on top of the existing architecture.
- Every mutation is POST + CSRF-protected; GET never mutates state.
- Human approval is always required; agents only detect and recommend.
- Confidentiality and record-level scope are enforced server-side and audited.
- Excel bulk import and external AI are intentionally **not** implemented yet.
- See `DOCUMENT_WORKFLOW.md`, `INCIDENT_WORKFLOW.md`, `REPORT_CATALOG.md`,
  `FILE_UPLOAD_SECURITY.md`.
