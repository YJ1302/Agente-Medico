# CHANGELOG — UPeU Internado 360

All notable changes to this project are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/); dates are ISO-8601.

## [0.2.0-alpha.5] — Phase 1 · Part 2 · Batch 2D

**Complete digital evaluation workflow + role-specific dashboards** (complete, verified).

### Role-specific dashboards
Replaced the Part 1 placeholder (`dashboard_role.html`, which leaked global
admin stat cards to every role) with four dedicated builders:
- **Admin / University Coordinator** reuse the existing global
  `DashboardService.build_admin_dashboard()` — both roles have legitimate
  global academic visibility.
- **Sede Coordinator** (`dashboard_sede.html`): own-sede student/tutor/
  rotation counts, own-sede pending/submitted evaluations, own-sede alerts only.
- **Tutor** (`dashboard_tutor.html`): assigned students, active rotations,
  evaluations to complete, activity verification inbox, workload indicator.
- **Student** (`dashboard_student.html`): current rotation, tutor, sede, days
  remaining, next rotation, personal activity progress, own evaluation status,
  personal alerts. **Contains zero global counts** — verified by test
  (`Internos MINSA`/`Internos EsSalud`/`Sedes activas` never appear).

### Evaluation workflow
Full status machine: `pending → in_progress → submitted → approved`;
`submitted → returned_for_correction → in_progress`; `approved → in_progress`
(Administrator-only reopen, mandatory reason). All 15 criteria (Conocimientos,
Desempeño, Actitudinal × 5, scale 0–4) required before submission; area totals
(0–20) and final score (0–20, 2 decimals) are **always recomputed server-side
from the stored criteria** — a forged/tampered browser total is silently
ignored. Live JavaScript totals are convenience-only.

Pages: list (status filter), one adaptive detail page covering the tutor
scoring form / read-only submitted view / coordinator review panel /
returned-for-correction banner / approved view (role- and status-conditional,
same pattern as rotation_detail.html), plus a standalone printable view.

### Roles
Tutor fills/submits only their own assigned-rotation evaluations; Sede
Coordinator approves/returns only own-sede submitted evaluations; University
Coordinator and Admin view all; Student sees only their **own approved**
evaluation (never pending/in-progress/returned).

### Schema (migration `ca5acdae8455`, on top of `e6118382e890`)
`EvaluationStatus` gained `RETURNED_FOR_CORRECTION`. `Evaluation` extended with
`submitted_at/by`, `reviewed_at/by`, `review_comments`, `reopened_at/reason` —
all nullable, plain `ADD COLUMN` (no rebuild needed this time). All 3
pre-existing evaluations preserved; `alembic current` at head.

### Alerts (2 new deterministic rules)
`returned_evaluation_pending_correction`, `submitted_evaluation_waiting_approval`
— dedup + auto-resolve, reusing the existing `AlertService` mechanism.

### Audit
`start_evaluation`, `save_evaluation_draft`, `submit_evaluation`,
`return_evaluation`, `approve_evaluation`, `reopen_evaluation` all wired with
mandatory-reason capture for return/reopen.

### Seed
6 evaluations covering all 5 states: 2 pending, 1 in_progress (partially
scored), 1 submitted, 1 returned_for_correction (with coordinator comment),
1 approved (attached to the demo student's own assignment so `student@` has a
real approved evaluation to view).

### Tests
**118 passing** (96 prior + 22 new): 15-criteria requirement, score range 0–4,
area/final score correctness (recomputed independently in the test, not
hardcoded), tutor/coordinator/student scope, submitted/approved locks,
return→correct→resubmit flow, admin reopen with reason, CSRF, audit, and
dashboard scoping (student dashboard confirmed free of global data).

## [0.2.0-alpha.4] — Phase 1 · Part 2 · Batch 2C

**Activity and procedure tracking** (complete, verified).

### Source-document analysis
Extracted and classified all activities from the four official "LISTA DE
ACTIVIDADES DE INTERNADO" documents (Cirugía 2026 current; Medicina, Pediatría,
Gineco-Obstetricia 2024 provisional). Full mapping in
[ACTIVITY_CATALOG_SOURCE_MAP.md](ACTIVITY_CATALOG_SOURCE_MAP.md). 129 catalog
rows: 4 shared narrative categories + 4×(15 clinical topics + procedure goals),
30 fixed-target procedures, the rest `no_fixed_target`(NA) or `completion_only`.
"NA" is stored as `target_count=NULL`, never 0.

### Schema (migration `e6118382e890`, on top of `0e5f841e0967`)
`ActivityDefinition` extended with `code` (unique), `target_type`,
`target_count` (now nullable), `unit_label`, `requires_tutor_verification`,
`evidence_policy`, `supervision_required`, `source_document/year/section`,
`is_provisional`, `display_order`, `is_active`. `StudentActivity` extended with
`evidence_reference`, `submitted_at`, `created_by_user_id`. New append-only
`ActivityReview` table (verify/reject/reopen/correct history — a later review
never overwrites an earlier one). Applied via a manual, explicitly-named table
rebuild for `activity_definitions` (SQLite can't relax NOT NULL in place and
batch-mode crashes on this table's pre-existing unnamed FK — see D-022/D-026);
all 4 pre-existing rows preserved. `alembic current` at head.

### Catalog management
List (search/filters: rotation, category, target type, verification,
active/inactive, current/provisional), detail, create/edit/(de)activate
(Admin full; University create/edit/(de)activate; Sede/Tutor/Student read-only),
and an **import preview/confirm** page that idempotently syncs the official
catalog by code.

### Student activity entry
Log an activity within an own active/planned rotation assignment; date must
fit the rotation period ± a configurable grace window; quantity must be a
positive integer; the definition must belong to the assignment's rotation and
be active. A visible privacy warning appears on every entry form. Pending and
rejected entries are editable by their owner; verified entries are locked;
rejected entries transition back to `pending` on correction (same row, full
history preserved via `ActivityReview`).

### Tutor verification
Inbox scoped to the tutor's own assigned students; verify (no comment) /
reject (mandatory comment) / scoped bulk-verify (out-of-scope ids silently
skipped, never touched). Inactive tutors cannot verify. Admin-only reopen with
mandatory reason.

### Progress & rollups
Fixed-target percentage (capped display at 100%, true count always shown);
NA shows verified count with an explicit "no numeric target" message (never
0%); completion-only shows done/not-done. Rollups per activity, assignment,
student, rotation type, sede and tutor workload. The rotation detail
**Actividades** tab now renders live progress, the entry form (with the
privacy warning), and the full entry table.

### Coordinator monitoring
`/activities/monitor` (Admin/University: all; Sede Coordinator: own sede):
low-progress students, old-pending students, students with rejections,
at-risk rotations ending soon, and tutors with a verification backlog.

### Alerts (5 new deterministic rules)
`activity_target_at_risk`, `old_pending_activity`,
`rejected_activity_requires_correction`,
`rotation_completed_with_unverified_activities`, `tutor_verification_backlog`
— all dedup and **auto-resolve** with preserved history (reusing the
Batch 2B `AlertService` mechanism).

### Audit
New actions: `create_activity_definition`, `update_activity_definition`,
`deactivate_activity_definition`, `create_student_activity`,
`update_student_activity`, `submit_student_activity`, `cancel_student_activity`,
`verify_student_activity`, `reject_student_activity`,
`correct_student_activity`, `reopen_student_activity`,
`bulk_verify_student_activities`, `import_activity_catalog_preview`,
`import_activity_catalog_confirmed`. Detail payloads exclude prohibited data;
a local offline heuristic (`privacy_validator.py`) blocks obvious patient
identifiers (DNI-like numbers, "historia clínica" labels, emails, phone
numbers, "nombre del paciente" phrases) before they are ever saved or logged.

### Seed
129 official catalog definitions + 24 demo activity records covering: ~20%,
~80% and 120% (capped display, true count kept) fixed-target progress; pending
entries; a rejected-then-corrected entry (single row, full history); a second,
never-corrected rejected entry; a tutor verification backlog (14 old-pending
entries for Dr. Martín Salas); a rotation ending soon with an at-risk target;
and a completed rotation with a lingering unverified entry.

### Tests
**96 passing** (65 prior + 31 new). Two real bugs found and fixed during
testing: a FastAPI route-ordering conflict (fixed paths like `/activities/mine`
must be registered before `/activities/{definition_id}`, or the int converter
swallows them and returns 422), and TestClient's list-of-tuples `data=` not
repeating form keys the way `requests` does (must use a dict with a list
value) — both fixed, not worked around.

## [0.2.0-alpha.3] — Phase 1 · Part 2 · Batch 2B

**Rotation assignment management** (complete, verified).

### Schema (migration `0e5f841e0967`, on top of `7fb2a9a545a7`)
Added to `rotation_assignments`: `notes`, `cancellation_reason`,
`reopened_reason`, `override_reason`, `completed_at`, `cancelled_at`,
`reopened_at`, `created_by_user_id`, `updated_by_user_id`. Applied to the
existing DB with all 23 rows preserved; `alembic current` at head.

### Rotation module
- **List** with search (student/code) and filters (period, rotation type, sede,
  tutor, student, status, institution, with/without tutor), pagination, result
  count, clear, conflict indicator and evaluation-status column.
- **Detail** with 7 tabs (Resumen · Estudiante · Tutor · Actividades ·
  Evaluación · Alertas · Auditoría), live conflict panel, duration, allowed
  actions by role+status.
- **Create/edit** with the "Validación de asignación" conflict panel; values
  preserved on failure. **Edit is status-gated**: planned = full edit, active =
  limited (tutor/end date/notes), completed/cancelled = locked.
- **Status workflow** planned→active→completed/cancelled with admin-only reopen;
  cancellation and reopen require a mandatory reason.
- **Tutor assignment/reassignment/removal** (active tutors of the sede only);
  removing a tutor raises a missing-tutor alert; completed assignments are
  locked until reopened.
- **Timeline/calendar** view grouped by student / sede / period / rotation type
  (lightweight, offline, status chips).

### Conflict service (`rotation_conflict_service.py`)
Authoritative server-side checks returning structured `Conflict` results (code,
severity, title, message, blocking, can_override, requires_reason):
`student_overlap`, `duplicate_core_rotation`, `tutor_sede_mismatch`,
`tutor_inactive`, `sede_inactive`, `student_inactive`, `institution_mismatch`,
`community_not_allowed`, `period_date_mismatch`, `tutor_workload_warning`,
`unusual_duration`. Institution/community/period conflicts are **admin-override-
able with a mandatory reason**; workload/duration are warnings requiring
confirmation (never hard blocks).

### Automatic evaluation creation
Completing an active rotation creates one `pending` evaluation (linked
student/assignment/tutor) with the 15 official criteria — never duplicated on
repeated completion. Audited as `create_pending_evaluation`.

### Alerts & agents
Four new deterministic rules: `overdue_evaluation_after_rotation_end`,
`student_rotation_overlap`, `tutor_sede_mismatch`, `institution_mismatch`.
`AlertService` now **auto-resolves** open rule alerts when the condition clears
(status → resolved, preserved as history) and re-opens if it returns.

### Audit
New actions: `create_rotation_assignment`, `update_rotation_assignment`,
`assign_tutor`, `reassign_tutor`, `remove_tutor`,
`activate_rotation_assignment`, `complete_rotation_assignment`,
`cancel_rotation_assignment`, `reopen_rotation_assignment`,
`override_rotation_conflict`, `conflict_validation_failed`,
`create_pending_evaluation`. Mandatory reasons stored for cancel/reopen/override.

### Interface language toggle
A top-bar **Traducir** button switches the interface chrome (navigation, top
bar) between Spanish (default) and English, stored per session, fully offline.

### Seed
Now includes planned/active/completed/cancelled rotations, a completed rotation
with an auto pending evaluation, a MINSA community rotation, and exactly one
controlled institution-mismatch demo (interns' institution otherwise matches
their sede). Multiple sedes/periods populate the timeline.

### Tests
- **65 passing** (44 prior + 21 new rotation tests). Also fixed a test-fixture
  bug so multiple role clients can be used in one test without clobbering
  sessions.

## [0.2.0-alpha.2] — Phase 1 · Part 2 · Batch 2A

**Sede, Sede-Coordinator and Tutor management** (complete, verified).

### Schema (migration `7fb2a9a545a7`, on top of baseline `407858b8a29f`)
- `sede_coordinator_profiles.is_principal` (Boolean, default true) — one active
  principal coordinator per sede.
- `tutor_profiles.specialty` (String) — distinct from the clinical `service`.
- New config `TUTOR_ASSIGNMENT_WARNING_THRESHOLD` (default 5). Upgrades cleanly
  from an existing Part 1 database with no data loss.

### Sede management
- List (search name/short/city/address; filters institution, type, active,
  has/missing coordinator; pagination; result count; clear), detail with tabs
  (Resumen · Coordinador · Tutores · Internos · Rotaciones · Alertas · Auditoría),
  create/edit, activate/deactivate, admin soft-delete.
- **Lifecycle rules:** deactivation blocked when active/planned rotations exist;
  **admin-only forced deactivation** with a mandatory reason + audit; university
  coordinator cannot force; sede coordinator cannot deactivate; soft-delete
  admin-only and blocked when active relationships exist.

### Sede Coordinator management
- List/detail/create/edit/activate-deactivate. User account (`sede_coordinator`)
  + profile created **atomically**; unique email; hashed password (generated if
  omitted, shown once, never stored in plain text).
- **Principal replacement workflow:** assigning a second active principal warns
  and requires an explicit "replace" confirmation, which deactivates the previous
  principal and writes `replace_sede_coordinator` + `create_sede_coordinator`
  audit entries. Coordinators cannot be attached to an inactive/deleted sede.

### Tutor management
- List (filters sede/service/active/has-assignments/**workload**), detail with
  tabs (Resumen · Asignaciones · Internos · Evaluaciones · Auditoría),
  create/edit/activate-deactivate. Atomic user (`tutor`) + profile creation.
- **Configurable workload indicator** (normal / near / above threshold) — a
  warning only, never a hard block. Deactivation blocked with active assignments
  unless an admin forces with a reason; reassignment blocked while active
  assignments remain at the old sede. Sede coordinators may edit only limited
  contact/service fields of own-sede tutors.

### Authorization, audit, CSRF
- Server-side scope on every route and record; students/tutors cannot reach the
  management lists; sede coordinators are confined to their own sede.
- New audit actions: `create_sede`, `update_sede`, `deactivate_sede`,
  `reactivate_sede`, `force_deactivate_sede`, `soft_delete_sede`,
  `create_sede_coordinator`, `update_sede_coordinator`,
  `reassign_sede_coordinator`, `replace_sede_coordinator`,
  `deactivate_sede_coordinator`, `reactivate_sede_coordinator`, `create_tutor`,
  `update_tutor`, `reassign_tutor`, `deactivate_tutor`, `reactivate_tutor`,
  `force_deactivate_tutor`. All forms CSRF-protected; no GET mutations.

### Seed
- 5 sedes (one — C.S. Santa Rosa — intentionally without coordinator/rotations),
  1 inactive tutor, a near-threshold and two above-threshold tutors, sedes with
  active rotations that block deactivation, and a coordinator-replacement setup.

### Tests
- **44 passing** (21 prior + 23 new: sedes, coordinators, tutors, scope, CSRF).

## [0.2.0-dev] — Phase 1 · Part 2 (in progress)

Part 2 is being delivered as verified increments. **Completed and tested so far:**

### Security repair (audit A.1–A.9)
- **Server-side authorization** added (`app/authorization.py`): `require_roles`
  route guards + record-level scope helpers (`can_view_student`,
  `can_view_assignment`, …). Admin-only (`/users`, `/settings`, `/audit`),
  admin+university (`/agent-executions`, `/periods`) and management (`/tutors`,
  `/reports`) routes are now enforced server-side — hidden sidebar links are no
  longer the boundary. Styled **403** page; denials recorded as
  `authorization_denied`.
- Corrected the false RBAC claim in `dependencies.py`.
- **Tutor functions verified** from the official 2026 PDF (DECISIONS_LOG D-015,
  A-1 resolved).

### Infrastructure
- **Alembic** migrations (`alembic.ini`, `migrations/`, baseline migration of the
  Part 1 schema). App no longer drops tables on startup; `python -m app.seed` is
  now **non-destructive** and `--reset` is required to rebuild demo data.
- **CSRF protection** (`app/csrf.py`): per-session synchronizer token, hidden
  field in every form, `csrf_protect` dependency, friendly 400 page. All
  mutations are POST; GET mutations are unavailable.
- **Audit logging** activated (`app/services/audit_service.py`) with a key
  denylist so passwords/tokens/patient data never enter the payload.
- **Fully offline assets**: Chart.js and Bootstrap Icons (incl. fonts) vendored
  under `app/static/vendor/`; all CDN references removed.
- Flash messages, pagination and reusable form macros/validators.

### Intern student management (section D) — complete
- List with search (name/code/document/email), filters (cycle, institution,
  sede, profile, active), pagination, result count and clear-filters.
- Detail page with rotation timeline, tutor, evaluation status, activity
  progress, related alerts and audit history summary.
- Create / edit / activate-deactivate / admin soft-delete, full validation
  (unique code/email/document, cycle 13/14, end>start, ~365-day warning with
  reason), record-level scope, and audit on every mutation.

### Tests
- `pytest` suite against a **temporary** database (`tests/`, `pytest.ini`):
  authentication, authorization/scope, students validation, CSRF. **21 passing.**

### Still pending in Part 2 (next increments)
Sede management (E), tutor/coordinator management (F), rotation assignments +
conflict detection (G), activity/procedure log + verification (H), digital
evaluation workflow with Decimal scoring + approval state machine (I), the
additional deterministic rules (K), the Part 2 schema migration for the new
evaluation/activity/rotation columns, and the remaining documentation updates.

## [0.1.0] — 2026-07-10 · Phase 1 · Part 1

**Foundation, rulebook, data model, authentication mockup, dashboard shell and
agent-ready architecture.**

### Added
- Modular FastAPI application (config, database, logging, security, templating,
  dependencies) runnable locally via `uvicorn app.main:app --reload`.
- SQLAlchemy data model for the full future system: `User`, `Role`, `Student`,
  `InstitutionType`, `Sede`, `SedeCoordinatorProfile`, `TutorProfile`,
  `AcademicPeriod`, `RotationType`, `RotationAssignment`, `Evaluation`,
  `EvaluationCriterion`, `ActivityDefinition`, `StudentActivity`, `Alert`,
  `DocumentRecord`, `Incident`, `AuditLog`, `AgentExecution`.
- Reusable mixins (timestamps, soft-delete, integer PK) and shared enums.
- Repository layer and service layer (auth, dashboard, alerts, navigation).
- Session-cookie authentication with bcrypt hashing; five seeded demo roles;
  no public registration.
- Role-based navigation with per-role visibility.
- Institutional UI: login, app shell, collapsible sidebar, top bar,
  notifications dropdown (live feed), user menu, responsive mobile navigation,
  empty/loading states, styled 404 and 500 pages.
- Fully styled **administrator dashboard**: 8 stat cards, rotation-distribution
  and institution charts (Chart.js), rotations-ending-soon table, recent alerts,
  recent agent activity, quick actions, current academic period, system status.
- Placeholder pages for every future module; real data pages for students,
  sedes, tutors, rotations, evaluations, alerts, agent executions and audit.
- **Agent-ready architecture**: `BaseAgent`, `AgentResponse`/`AgentFinding`,
  `AgentOrchestrator`, `RuleEngine`, and four working mock agents
  (monitoring, planning, evaluation, document).
- Three+ deterministic demo rules producing dashboard alerts: rotation ending
  within 7 days, assignment without tutor, pending evaluation, incomplete
  profile.
- Seed script with fictional data (12 interns, 4 sedes, 4 sede coordinators,
  8 tutors, MINSA/EsSalud mix, four core rotation types, active and upcoming
  assignments, one pending evaluation, and the four demo alerts).
- Faithful reproduction of the official evaluation instrument (3 areas × 5
  criteria, 0–4 scale, area sums and averaged final note).
- Full documentation set under `/docs`.
- `requirements.txt`, `.env.example`, `.gitignore`, `README.md`.

### Security & privacy
- No real patient clinical information stored; all demo data is fictional.
- Visible privacy notice on the login page.
- Secrets via `.env`; no hardcoded production secrets.

### Notes
- No external AI API is used; agents are deterministic mocks with an LLM-ready
  interface.
- SQLite for the prototype; schema designed for a future PostgreSQL migration.

## [Unreleased] — planned
- Phase 1 · Part 2: operational CRUD workflows (interns, sedes, tutors,
  rotations, activities, evaluation capture) and form validation/CSRF tokens.
