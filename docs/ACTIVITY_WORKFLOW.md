# ACTIVITY WORKFLOW — UPeU Internado 360 (Batch 2C)

Describes the activity/procedure tracking module: catalog, student entry
lifecycle, tutor verification, progress calculations, coordinator monitoring,
alerts and privacy validation.

## 1. Catalog

`ActivityDefinition` rows come from the official "LISTA DE ACTIVIDADES"
documents (see [ACTIVITY_CATALOG_SOURCE_MAP.md](ACTIVITY_CATALOG_SOURCE_MAP.md))
or are created manually by an Administrator/University Coordinator. Each has:

- `target_type`: `fixed` (numeric goal), `no_fixed_target` (NA — perform the
  largest reasonable number, `target_count` is always `NULL`, never 0), or
  `completion_only` (done/not done, no quantity target).
- `category`: `hospitalization`, `emergency`, `community`, `academic`,
  `clinical_topic`, or `procedure`.
- `rotation_type_id`: `NULL` means the definition applies to every core
  rotation (the four shared narrative categories); otherwise it is
  rotation-specific.
- `source_document` / `source_year` / `source_section` / `is_provisional`:
  traceability back to the official document. Provisional (2024) definitions
  are superseded by future 2026 revisions without deleting history —
  definitions with existing student records are deactivated, never hard-deleted.

The **import preview** (`/activities/import`, Admin/University) diffs the code
module `app/data/activity_catalog.py` against the database and creates only
missing rows (idempotent by `code` — safe to re-run).

## 2. Student entry lifecycle

Status values: `draft`, `pending`, `verified`, `rejected`, `cancelled`.
(`corrected` is not a resting state — see the note below.)

```
draft ──► pending ──► verified
            │            (Administrator may reopen: verified → pending,
            ▼             mandatory reason, ActivityReview action=reopened)
         rejected ──► pending
        (same row;    (student edits the SAME row and resubmits;
         mandatory     an ActivityReview action=corrected row is added —
         comment)      the rejection review is preserved, never overwritten)
            │
            ▼ (student, before any review)
        cancelled
```

A student may only log activities within their **own** rotation assignment,
for a definition that belongs to that assignment's rotation (or is a shared
definition), while the assignment is `active` or `planned`. The activity date
must fall within the rotation period ± a configurable retrospective grace
window (`ACTIVITY_RETROSPECTIVE_GRACE_DAYS`, default 7 days).

**Design note (D-026):** a rejected-then-corrected activity is the *same*
database row transitioning `rejected → pending` — never a duplicate row. Full
history (who rejected, when, why; who corrected, when) is preserved in the
append-only `ActivityReview` table, never overwritten.

## 3. Tutor verification

A tutor sees, in their inbox (`/activities/verify`), only pending activities
belonging to students on assignments **they** supervise. Verifying requires no
comment; rejecting requires a mandatory comment. Bulk-verify only touches
entries within the acting tutor's own scope — out-of-scope ids in the same
request are silently skipped (never verified). An inactive tutor cannot verify.
Administrators may reopen a verified entry with a mandatory reason.

## 4. Progress calculation

- **Fixed target:** `percent = verified_total / target_count × 100`. The
  displayed bar is capped at 100%, but the true verified count (which may
  exceed the target) is always shown alongside it.
- **No fixed target (NA):** shows the verified count only, with the message
  *"Sin meta numérica — realizar el mayor número posible."* Never rendered as
  0% or as an implicit target of zero.
- **Completion-only:** shows completed/not completed (any verified entry ⇒
  completed).

Only `verified` entries count toward progress. `pending`, `rejected` and
`cancelled` entries never count.

## 5. Coordinator monitoring

`/activities/monitor` (Admin/University: all sedes; Sede Coordinator: own sede
only) surfaces:

- Assignments with **&lt;50%** average verified progress across their
  fixed-target definitions (an expected, broad indicator — most rotations show
  low numbers early on; the narrower **at-risk alert**, below, is what flags a
  genuine problem).
- Students with pending activities older than `ACTIVITY_OLD_PENDING_DAYS`
  (default 5).
- Students with rejected activities.
- Active rotations ending within `ACTIVITY_AT_RISK_ROTATION_DAYS` (default 10)
  whose average fixed-target progress is below
  `ACTIVITY_AT_RISK_THRESHOLD_RATIO` (default 50%).
- Tutors whose old-pending queue exceeds `TUTOR_VERIFICATION_BACKLOG_THRESHOLD`
  (default 8).

## 6. Deterministic alert rules (Batch 2C)

| Rule | Fires when |
|---|---|
| `activity_target_at_risk` | Active rotation ends soon **and** fixed-target progress is materially below goal |
| `old_pending_activity` | A pending entry has sat unreviewed past the threshold |
| `rejected_activity_requires_correction` | A rejected entry has not been corrected past the threshold |
| `rotation_completed_with_unverified_activities` | A `completed` assignment still has `pending` entries |
| `tutor_verification_backlog` | A tutor's old-pending queue exceeds the threshold |

All alerts deduplicate (no repeat open alert for the same condition) and
**auto-resolve** when the underlying condition clears — the resolved row is
kept as history, and a new alert opens if the condition returns. Agents never
mutate records; every recommendation still requires human action
(AGENT_ARCHITECTURE.md).

## 7. Privacy validation

`app/services/privacy_validator.py` runs a local, offline heuristic
(`find_identifier_risk`) over `notes` and `evidence_reference` before saving,
detecting: 8-digit DNI-like numbers, "HC"/"historia clínica"/"N° historia"
labels, email addresses, Peruvian mobile-phone patterns, and phrases like
"nombre del paciente". A match blocks the save with:

> *"El sistema detectó contenido que podría identificar a un paciente. Elimine
> esa información antes de guardar."*

This is a practical heuristic, **not a guarantee** of de-identification — it
catches the common, obvious cases only, per SECURITY_AND_PRIVACY_RULES.md. No
external service or AI is used.

## 8. Known limitations

- Attachments are represented only as a free-text "anonymous reference" field
  (`evidence_policy=optional_attachment` is modeled but no file upload exists
  yet — reserved for a later batch, consistent with the file-upload
  architecture already reserved in Part 1).
- The "low progress (&lt;50%)" monitoring indicator is intentionally broad by
  design (see §5) — it is not itself an alert; `activity_target_at_risk` is
  the narrower, alert-worthy signal.
- Full evaluation *scoring* is out of scope for this batch (Batch 2D).
