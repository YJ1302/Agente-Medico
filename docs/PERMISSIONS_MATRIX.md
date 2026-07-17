# PERMISSIONS MATRIX — UPeU Internado 360

Single-page authoritative reference for role-based access control. This
supplements — it does not replace — `USER_ROLES_AND_PERMISSIONS.md`'s
per-batch detail; this page is the flat, module-by-module summary used for
the RBAC hardening pass (see `DECISIONS_LOG.md` for the corresponding entry).

**Enforcement is always server-side and layered — never template-only:**

1. **Route guard** (`app/authorization.py`: `require_admin`,
   `require_admin_or_university`, `require_management`, or `require_identity`
   + a manual role check) — rejects before any handler code runs.
2. **Query-level scope** — list/dashboard endpoints pass `sede_ids=` /
   `student_ids=` / `tutor_ids=` into the repository query itself (SQL `IN`
   clauses), never "fetch everything, hide in the template."
3. **Record-level scope** (`can_view_*`/`can_edit_*`/`can_manage`/`ensure(...)`
   in each service) — re-checked on every detail/edit/mutate/download
   endpoint, independently of what the route guard already allowed, so a
   Sede Coordinator who passes the route guard still cannot touch another
   sede's row by URL.
4. **Confidentiality** (`VisibilityLevel`: normal/restricted/confidential) is
   a separate axis from role/sede scope, checked in *addition* to it on
   documents and incidents.
5. **Audit** — every denial raises `Forbidden`, which the global exception
   handler in `app/main.py` renders as a generic 403 (`errors/403.html`) and
   records as an `authorization_denied` audit entry. The 403 page text is
   identical whether a record doesn't exist or the caller lacks scope — the
   distinguishing detail (`reason`) is audit-only, never rendered to the user.

## Module matrix

| Module | Admin | University Coord. | Sede Coord. | Tutor | Student |
|---|:---:|:---:|:---:|:---:|:---:|
| Dashboard | global KPIs | global KPIs | own sede only | own workload only | own summary only, zero global numbers |
| Students | full | read all | own sede (SQL-scoped) | assigned only | own record only |
| Sedes | full | read all | own sede | — | — |
| Coordinators | full | read all | own sede, read-only | — | — |
| Tutors | full | read all | own sede | own profile only | — |
| Rotations | full | full | own sede | assigned only | own only |
| Activities (catalog) | full | full | read | read | read |
| Activities (verify) | full | full | — | assigned students only | own submissions only |
| Activities (monitor) | full | full | own sede | — | — |
| Evaluations | full | full | approve/return, own sede | score/submit, assigned only | own **approved** only |
| Documents | full | full, incl. confidential | own sede + confidentiality gate | linked to assigned students only, permitted types | own + permitted create types |
| Incidents | full | full, incl. confidential | own sede + confidentiality gate | assigned students only | own, non-confidential |
| Reports | full | full | own sede | none (own-student data already covered by Activities/Evaluations) | own internship summary only |
| Imports | full | full (no user/role import) | own sede, students/rotations only | — | — |
| Grade schemes/components | full | full | — (never sees raw matrix) | — | — |
| Alerts | global | global | own sede only (resolved via related-entity lookup) | own students/own tutor alerts only | own only |
| Agent Center | full | full | **blocked** (agents are not sede-scoped) | **blocked** | **blocked** |
| AI Assistant | full | full | own sede (grade questions blocked) | **blocked** | **blocked** |
| Audit logs | full | — | — | — | — |
| Settings/config | full | — | — | — | — |
| Users & Roles | full | — | — | — | — |
| Attachments/downloads | full | full, incl. confidential | own sede + confidentiality gate (re-checked on every download, not just the list) | linked to assigned students | own only |
| PDF/Excel exports | full | full | own sede | — | own summary only |
| `/api/notifications` (JSON) | global | global | own sede | own students/tutor | own only |

## Agent Center — why Sede Coordinator is blocked, not scoped

All five registered agents (`monitoring_agent`, `planning_agent`,
`evaluation_agent`, `document_agent`, `incident_monitoring_agent`) scan
**every** active record institution-wide — none accept or apply a `sede_ids`
filter (`app/agents/*.py`, each calls `repos.X.all_active()`/`.pending()`
unscoped). Rewriting five agents' internal detection logic to be sede-aware
would be a redesign of a completed module, which this hardening pass
explicitly avoids. Per the required access model ("Sede Coordinator: only if
agents are correctly scoped to their own sede; otherwise hide and block"),
the compliant choice is to block the module entirely for that role
(`require_admin_or_university` route guard in `app/routes/agent_routes.py`,
matching nav visibility in `app/services/navigation.py`) until/unless the
agents themselves are redesigned to be sede-aware in a future phase.

University Coordinator gets full access because every existing agent is
academic/institutional monitoring in nature (rotation planning, evaluation
completeness, document/incident triage) — there is no system-administration
agent in this codebase to withhold from that role.

## Confidentiality is not a role override

A document/incident marked `visibility=confidential` is visible only to a
global viewer (Admin/University Coordinator) or the record's own
creator/reporter/responsible user — **a Sede Coordinator's own-sede scope
never overrides confidentiality**, on read *or* write. This was a real gap
fixed in this hardening pass: `DocumentService.can_edit()`/`can_review_flow()`
and `IncidentService.can_manage()` previously granted a Sede Coordinator
write access to any own-sede record regardless of confidentiality, even
though the corresponding *read* check (`can_view()`) already enforced it
correctly — see `DECISIONS_LOG.md`.

## Cross-sede link validation on create/edit

`DocumentService._resolve_links()` and `IncidentService._resolve_links()` now
independently validate that a `student_id`/`sede_id` submitted in a POST body
falls within a Sede Coordinator's own scope — the create/edit forms only ever
*display* a scoped dropdown; the server no longer trusts it blindly. This
closes a cross-sede record-creation gap found in this audit.

## Internal identifiers vs. display names

Agent internal identifiers (`monitoring_agent`, `planning_agent`, etc.) are
preserved everywhere they matter for stability — run URLs
(`/agents/{agent_name}/run`), persistence (`AgentExecution.agent_name`), and
audit entries. `app/agents/orchestrator.py::AGENT_DISPLAY_NAMES` maps each to
a professional Spanish label used only in the two templates a human reads
(`pages/agents.html`, `pages/agent_executions.html`).
