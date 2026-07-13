# DECISIONS LOG — UPeU Internado 360

Architectural and business decisions, with rationale. Newest first.

---

### D-029 · Admin reopen targets `in_progress`, not a new "reopened" status (Batch 2D)
**Decision:** Administrator reopen of an approved evaluation transitions it to
`in_progress` (editable by the tutor again), recording `reopened_at`/
`reopened_reason` on the row rather than introducing a sixth status value.
**Why:** mirrors D-026's reasoning for activities — the prior approval history
(`reviewed_at`/`reviewed_by_user_id`/`review_comments`) is preserved on the
same row and via the audit log; a dedicated status would be functionally
identical to `in_progress` in every query and view.

### D-028 · One adaptive evaluation detail page, not six separate templates (Batch 2D)
**Decision:** `evaluation_detail.html` renders the tutor scoring form,
read-only submitted view, coordinator review panel, returned-for-correction
banner and approved view all from one template, conditioned on role and
`ev.status` — plus a separate standalone `evaluation_print.html` for the
genuinely different printable layout. **Why:** consistent with
`rotation_detail.html`'s established pattern (Batch 2B) of one state-aware
page over duplicated near-identical templates; the printable view is kept
separate because its layout (no sidebar/topbar, print-optimized) is
structurally different, not just a permission variant.

### D-027 · Catalog uniqueness via index, not NOT NULL column (Batch 2C)
**Decision:** `activity_definitions.code` uniqueness is enforced with a
separate `CREATE UNIQUE INDEX`, while the column itself stays nullable at the
SQLite schema level; the application always supplies a code (validated as
required). **Why:** the pre-existing table already had 4 rows before the
migration; a NOT NULL+UNIQUE column added in one step has no safe single
default for multiple existing rows. Backfilling with `'LEGACY-' || id` then
indexing achieves the same real-world guarantee without a risky migration step,
consistent with D-022's "prefer app-level enforcement when SQLite ALTER is
unsafe" precedent.

### D-026 · Correction reuses the same row; "corrected" is a review action, not a status (Batch 2C)
**Decision:** `StudentActivity` status values are `draft`, `pending`,
`verified`, `rejected`, `cancelled` — five, not six. A rejected entry's
correction transitions the **same row** `rejected → pending`; the correction
itself is recorded as an `ActivityReview` row with `action="corrected"`,
alongside the earlier `action="rejected"` row, so nothing is overwritten.
**Why:** the spec listed `corrected` as a transitional state, but persisting it
as a resting status would be indistinguishable from `pending` in every
practical sense (queries, alerts, UI) while doubling the number of states to
reason about. The review history — not a status enum value — is what actually
needs to preserve "this was corrected."

### D-025 · Interface language toggle (chrome-level i18n) (Batch 2B)
**Decision:** Added a session-based ES/EN toggle (`app/i18n.py`) that translates
the persistent **chrome** (navigation, top bar) via a local dictionary; page
bodies remain Spanish. **Why:** the UI is authored in Spanish per requirements;
a full body-level i18n of every template is out of scope for this batch. Fully
offline (no external translation service). Full-page EN translation is a
documented future enhancement.

### D-024 · Conflict overrides are Admin-only, reason-mandatory, audited (Batch 2B)
**Decision:** Institution mismatch, EsSalud community rotation and far-outside
period dates are blocking but override-able only by an Administrator supplying a
reason (`override_rotation_conflict` audit + `override_reason` on the record).
Workload/duration are non-blocking warnings requiring confirmation. **Why:**
spec §6/§10 — human-in-the-loop, traceable exceptions without hard-coding
unsupported academic rules.

### D-023 · Automatic pending evaluation on completion (Batch 2B)
**Decision:** Completing a rotation creates one `pending` evaluation with the 15
official criteria (shared `evaluation_catalog.py`), never duplicated. Full score
capture stays in a later batch. **Why:** spec §11; centralizes the criteria used
by both seed and runtime.

### D-022 · Rotation lifecycle fields added; SQLite ADD COLUMN migration (Batch 2B)
**Decision:** Added nine `rotation_assignments` columns (notes, reasons,
lifecycle timestamps, created/updated_by). The migration uses plain
`op.add_column` (not batch mode) because SQLite batch-recreate fails on the
table's pre-existing unnamed foreign keys ("Constraint must have a name"); the
two user references are added as plain nullable integers (the ORM keeps the
ForeignKey for relationships / future PostgreSQL). **Why:** preserve existing
data and keep the migration reliable on SQLite.

### D-021 · Tutor workload is a configurable warning, not a hard block (Batch 2A)
**Decision:** Added `TUTOR_ASSIGNMENT_WARNING_THRESHOLD` (default 5). A tutor
over the threshold is flagged (normal/near/above) but assignment is never
blocked by workload alone. **Why:** spec F forbids inventing a strict official
medical limit; a configurable warning is the safe, honest model.

### D-020 · `tutor_profiles.specialty` added (Batch 2A)
**Decision:** Added a `specialty` column separate from `service`. **Why:** the
Batch 2A spec lists Specialty and Clinical service as distinct tutor fields; the
Part 1 model only had `service`.

### D-019 · `is_principal` models one active coordinator per sede (Batch 2A)
**Decision:** Added `sede_coordinator_profiles.is_principal` (default true). A
sede has at most one *active* principal coordinator; assigning another triggers
a controlled replacement (previous deactivated + audited). **Why:** spec E/F —
explicit is clearer than inferring "principal" from activity alone, and it keeps
room for future secondary coordinators. Migration `7fb2a9a545a7` uses a
`server_default` so existing rows migrate as principal without data loss.

### D-018 · Server-side authorization added (Part 2 repair)
**Decision:** Introduced `app/authorization.py` with `require_roles(...)` route
guards and record-level scope helpers; applied guards to admin/management routes;
added a styled 403 page and `authorization_denied` auditing. **Why:** Part 1
only enforced authentication — hidden sidebar links were not a security
boundary. Corrects the false RBAC claim in `dependencies.py`. (Repairs audit
items A.1–A.8.)

### D-017 · Audit logging activated
**Decision:** Added `AuditService` writing the previously-unused `AuditLog`
model, with a key denylist so passwords/tokens/patient data never enter the
payload. **Why:** Rulebook R4 requires important actions to be auditable.

### D-016 · Assets served locally (offline requirement)
**Decision:** Chart.js and Bootstrap Icons (CSS + woff/woff2 fonts) are vendored
under `app/static/vendor/` and served by the app; all CDN references removed.
**Why:** Part 2 requirement L — the full interface, icons and charts must render
without internet. **Supersedes D-014.** No proprietary fonts are bundled; system
fonts remain per UI_DESIGN_SYSTEM.md.

### D-015 · Tutor functions verified from the official 2026 document
**Decision:** The tutor PDF was successfully text-extracted and the tutor's
official functions confirmed: supervise/orient the intern's practical-assistance
activities, coordinate scheduling with the sede, review clinical topics,
**evaluate professional competencies, and register/submit evaluations and grades
to the Coordinator of Internship**. This validates BR-13/BR-14. **Why:** audit
item A.9 — replaces the earlier inference-only assumption (see revised A-1).

### D-014 · Browser CDN assets (icons, charts) kept optional *(superseded by D-016)*
**Decision:** Bootstrap Icons and Chart.js loaded from a CDN in Part 1; the app
was functional without them. **Superseded in Part 2** by fully local assets.

### D-013 · One current academic period guaranteed
**Decision:** The seed marks exactly one period `is_current`; if "today" falls
in a gap it marks the nearest period. **Why:** the dashboard and rules assume a
single current period (BR-04).

### D-012 · Alerts deduplicated against open alerts
**Decision:** `AlertService` only creates an alert if no equivalent open alert
exists (same category + entity). **Why:** the dashboard refreshes rules on each
load; without dedup, alerts would multiply.

### D-011 · Non-admin dashboards reuse a shared shell
**Decision:** Only the administrator dashboard is fully built; other roles use
`dashboard_role.html` with role-specific welcome text and placeholder cards.
**Why:** explicit Part 1 scope; the operational dashboards arrive in Part 2.

### D-010 · JSON stored as TEXT for agent/audit payloads
**Decision:** `agent_executions.findings_json`, `recommended_actions_json` and
`audit_logs.detail` are TEXT holding JSON. **Why:** SQLite portability and
simplicity now; can migrate to native JSONB on PostgreSQL later.

### D-009 · Session-cookie auth (not JWT) for Part 1
**Decision:** Use Starlette signed session cookies. **Why:** simplest secure
option for a server-rendered app; http-only + same-site mitigates common
attacks. JWT/API auth can be added when an API/SPA is introduced.

### D-008 · Deterministic agents, no external AI in Part 1
**Decision:** Agents are mock/deterministic with a fixed, LLM-ready interface.
**Why:** the spec forbids external AI in Part 1 and requires explainable,
human-approved automation. The interface lets real AI drop in later unchanged.

### D-007 · Human-in-the-loop enforced in the model
**Decision:** `AgentResponse.requires_human_approval` and
`Alert.requires_human_action` are first-class fields. **Why:** BR-26/BR-27 —
detection and recommendation never become autonomous action.

### D-006 · Soft-delete + active state instead of hard deletes
**Decision:** Mixins add `is_active`, `is_deleted`, `deleted_at`. **Why:**
preserve history and future audit integrity (Rulebook R4).

### D-005 · Integer surrogate keys in Part 1 (UUID deferred)
**Decision:** Use autoincrement integer PKs consistently now. **Why:** simpler,
smaller and faster on SQLite for a demo; the repository layer hides the key
type, so a later UUID switch (better for distributed/production systems) is
contained. Trade-off recorded per the spec's "UUIDs or well-designed integer
IDs" allowance.

### D-004 · Evaluation instrument modeled exactly from the 2026 format
**Decision:** Three areas (Conocimientos, Desempeño, Actitudinal), five criteria
each, 0–4 scale; area score = sum, final = average of areas; the 15 criteria
texts are seeded verbatim. **Why:** fidelity to `FORMATO DE EVALUACION INTERNO`
(BR-17…BR-21).

### D-003 · Bimonthly academic periods (six per year)
**Decision:** Model the year as six bimonthly periods (Ene-Feb … Nov-Dic).
**Why:** the programming spreadsheet organizes rotations in bimonthly columns;
this also matches the ~365-day internship (BR-03).

### D-002 · MINSA vs EsSalud modeled as `InstitutionType`
**Decision:** A dedicated table with `placement_method` and
`has_community_component`. **Why:** BR-05…BR-08 — MINSA uses ranking and adds a
community component; EsSalud uses examination. Keeps sedes and students linked to
one provider system without duplication.

### D-001 · 2026 documents prioritized over 2024
**Decision:** Where facts differ, 2026 documents win (e.g. tutor/coordinator
functions, evaluation format). The 2024 activity lists inform the activity
catalog only. **Why:** explicit project rule (Rulebook R2).

---

## Ambiguities & assumptions

- **A-1 · Tutor functions — RESOLVED in Part 2.** The tutor PDF (`FUNCIONES DE
  TUTOR DE INTERNADO 2026.pdf`) was successfully text-extracted and the tutor's
  official functions confirmed (see D-015). The earlier Part 1 inference is now
  **verified against the source document**; BR-13/BR-14 stand as written. This
  assumption is closed.
- **A-2 · Sede name spellings vary** across the spreadsheet (e.g. "José Agurto
  Tello / Argurto"). Seed sedes use clean, fictional-but-representative names; no
  real roster is imported.
- **A-3 · Real student data ignored by design.** The Excel contains real DNIs and
  names; per R1 these are **not** used. All seeded people are invented.
- **A-4 · Community component** is modeled as a non-core `RotationType` for MINSA
  rather than a separate subsystem, pending Part 2 requirements.
- **A-5 · CSRF tokens** are deferred to Part 2 (state changes already use POST +
  same-site cookies); documented in SECURITY_AND_PRIVACY_RULES.md.
