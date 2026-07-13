# BUSINESS RULES — UPeU Internado 360

Derived from the 2026 reference documents (tutor & sede-coordinator functions,
official evaluation format) and the programming spreadsheet. Where sources
disagree, the most recent **2026** document prevails (see DECISIONS_LOG.md).

## 1. Internship structure

- **BR-01** The internship lasts **approximately 365 days**.
- **BR-02** Students belong to **cycle 13 or cycle 14**.
- **BR-03** The internship year is organized into **six bimonthly academic
  periods**: Ene-Feb, Mar-Abr, May-Jun, Jul-Ago, Set-Oct, Nov-Dic.
- **BR-04** Exactly one academic period is *current* at any time.

## 2. Institutions and sedes

- **BR-05** A student is assigned to **MINSA** or **EsSalud**.
- **BR-06** A **sede** is a teaching site: a **hospital** or a **health center**
  (C.S. / C.M.I.).
- **BR-07** **MINSA** placements may include an **additional community
  component**; **EsSalud** placements do not.
- **BR-08** MINSA placement **may use ranking**; EsSalud placement **may use
  examination results**.
- **BR-09** Each sede has a **Sede Coordinator** (docente) who is the
  institutional nexus between the sede and the university.

## 3. Rotations

- **BR-10** The **four core rotations** are **Medicina Interna**, **Cirugía
  General**, **Pediatría** and **Gineco-Obstetricia**.
- **BR-11** Each rotation of a student, at a sede, in a period, has **one
  tutor** (a rotation may be planned before a tutor is designated).
- **BR-12** A rotation assignment without a designated tutor is an operational
  risk and must be flagged (see BR-24).

## 4. Roles and the operational hierarchy

```
University Administrator
   → University Internship Coordinator
      → Sede Coordinator
         → Rotation Tutor
            → Intern Student
```

- **BR-13** The **Tutor** directly supervises, guides and **evaluates** the
  student.
- **BR-14** The Tutor **submits evaluations to the Sede Coordinator**.
- **BR-15** The **Sede Coordinator consolidates** and communicates information
  to the **University Internship Coordinator**.
- **BR-16** Formal institutional communication route:
  `Student/University → Hospital Teaching Unit → Sede Coordinator → University`.
  The Sede Coordinator may also communicate **directly** with the university
  when necessary.

## 5. Evaluations

- **BR-17** Evaluations occur **at the end of each rotation**.
- **BR-18** The evaluation has **three areas**: **Conocimientos** (knowledge),
  **Desempeño** (performance) and **Actitudinal** (attitude).
- **BR-19** Each area has **five criteria**. Each criterion is scored on the
  scale: **4** Muy satisfactorio · **3** Satisfactorio · **2** Casi
  satisfactorio · **1** Poco satisfactorio · **0** Inaceptable.
- **BR-20** Each **area score is the sum** of its five criteria (0–20).
- **BR-21** The **final rotation note is the average** of the three area scores.
- **BR-22** Evaluations have traceable statuses: `pending → in_progress →
  submitted → approved`.

## 6. Communication, documents and incidents

- **BR-23** Formal communication (documents) must have **traceable statuses**:
  `draft → submitted → under_review → approved | rejected → archived`.
- **BR-25** Incidents (situations affecting the normal development of the
  internship) are tracked with severity and status.

## 7. Alerts and automation

- **BR-24** The system runs **deterministic rules** that produce dashboard
  alerts. Minimum required rules:
  1. **Rotation ending within 7 days.**
  2. **Rotation assignment without a tutor.**
  3. **Pending evaluation.**
  Additionally: **incomplete student profile**.
- **BR-26** The platform explicitly separates **automated detection →
  agent recommendation → human decision**.
- **BR-27** **No final institutional communication is ever sent automatically
  by an AI agent without human approval.** Every agent response carries
  `requires_human_approval`.

## 8. Sede, coordinator and tutor lifecycle (Batch 2A)

- **BR-29 · Sede deactivation.** A sede cannot be deactivated while it has active
  or planned rotation assignments. Only an **Administrator** may force
  deactivation, and only with a mandatory reason recorded in the audit log. A
  University Coordinator cannot force; a Sede Coordinator cannot deactivate.
- **BR-30 · Sede soft-delete.** Administrator-only, requires a reason, and is
  blocked while active relationships (rotations, staff) exist.
- **BR-31 · Principal coordinator.** A sede has at most **one active principal
  coordinator**. Assigning another warns and requires explicit confirmation; the
  previous principal is deactivated and the replacement is audited. A coordinator
  belongs to exactly one sede and cannot be attached to an inactive/deleted sede.
- **BR-32 · Tutor membership.** A tutor must belong to an active, non-deleted
  sede. A tutor may supervise multiple students/assignments.
- **BR-33 · Tutor workload.** The workload indicator (normal/near/above a
  configurable threshold, default 5) is a **warning only** — never a hard block.
- **BR-34 · Tutor deactivation / reassignment.** Deactivation is blocked while
  the tutor has active/planned assignments unless an Administrator forces it with
  a reason. Reassignment to another sede is blocked while active/planned
  assignments still belong to the current sede.
- **BR-35 · Atomic accounts.** Coordinator and tutor login accounts and profiles
  are created together in a single transaction; email is unique; passwords are
  hashed and never displayed.

## 9. Rotation lifecycle & conflicts (Batch 2B)

- **BR-36 · Status machine.** Allowed transitions: `planned → active`,
  `planned → cancelled`, `active → completed`, `active → cancelled`. Reopen
  (`completed → active`, `cancelled → planned`) is **Administrator-only** and
  requires a reason. Completed/cancelled records are otherwise locked.
- **BR-37 · Edit gating.** Planned = full edit; active = tutor/end-date/notes
  only; completed/cancelled = locked (no silent historical changes). Every
  change is audited.
- **BR-38 · Cancellation & reopen** require a mandatory reason (stored + audited).
- **BR-39 · Completion** creates exactly one `pending` evaluation (15 criteria)
  if none exists, never duplicating it; alerts refresh.
- **BR-40 · Conflicts (authoritative, server-side):** student overlap, duplicate
  core rotation in a period, tutor-sede mismatch, inactive tutor/sede/student
  **block** the save. Institution mismatch, EsSalud community rotation and
  far-outside period dates **block but are Administrator-override-able with a
  mandatory reason** (audited). Tutor workload and unusual duration are
  **warnings** that require confirmation but never block.
- **BR-41 · Tutor rules.** A tutor must be active and belong to the assignment's
  sede. Removing a tutor from an assignment raises a missing-tutor alert;
  reassignment is audited; a completed assignment's tutor cannot change until an
  admin reopens it.
- **BR-42 · Alert self-healing.** Rule-based alerts auto-resolve when their
  condition clears (kept as history) and reappear if the condition returns.

## 10. Activity and procedure tracking (Batch 2C)

- **BR-43 · Catalog source.** Activity definitions come from the official
  "LISTA DE ACTIVIDADES DE INTERNADO" documents. Cirugía 2026 is current;
  Medicina, Pediatría and Gineco-Obstetricia 2024 are provisional until updated
  versions are supplied. A future 2026 document always wins over its 2024
  predecessor. See ACTIVITY_CATALOG_SOURCE_MAP.md.
- **BR-44 · NA means no fixed minimum.** "NA" in a source procedure target
  means the intern performs the largest reasonable number possible. It is
  stored as `target_type=no_fixed_target`, `target_count=NULL` — **never** as
  a target of 0, and never displayed as 0%.
- **BR-45 · Entry scope.** A student logs activities only within their own
  active/planned rotation assignment, using a definition that belongs to that
  rotation (or a shared definition), with a date fitting the rotation period
  within a configurable grace window.
- **BR-46 · Status workflow.** `draft → pending → verified`;
  `pending → rejected → pending` (same row, corrected in place, full review
  history preserved); `pending → cancelled` (student, before review);
  `verified → pending` only via Administrator reopen with a mandatory reason.
- **BR-47 · Verification scope.** A tutor verifies/rejects only activities tied
  to assignments they supervise. Rejection requires a comment. Bulk-verify
  silently skips any id outside the tutor's scope.
- **BR-48 · Progress counts verified only.** Pending, rejected and cancelled
  quantities never contribute to progress. Fixed-target percentage display is
  capped at 100% while the true (possibly over-100%) count remains visible.
- **BR-49 · Privacy validation.** Free-text activity fields are checked by a
  local, offline heuristic before saving; content resembling a patient
  identifier (DNI-like number, "historia clínica" label, email, phone,
  "nombre del paciente") is rejected, not stored or logged.

## 11. Digital evaluation workflow (Batch 2D)

- **BR-50 · Instrument.** Conocimientos, Desempeño, Actitudinal — 5 criteria
  each, scored 0–4. Area total = sum of its 5 criteria (0–20). Final score =
  average of the three area totals (0–20, 2 decimals).
- **BR-51 · Status machine.** `pending → in_progress → submitted → approved`;
  `submitted → returned_for_correction → in_progress`. Approved is locked
  except for an **Administrator-only reopen with a mandatory reason**
  (`approved → in_progress`).
- **BR-52 · Authoritative recomputation.** All 15 criteria must be scored
  before submission; area totals and the final score are **always recomputed
  server-side from the stored per-criterion scores** on submit — a
  browser-supplied total is display-only and never trusted or persisted.
- **BR-53 · Role authority.** A tutor fills/submits only evaluations for their
  own assigned rotations. A Sede Coordinator approves or returns only
  own-sede submitted evaluations (mandatory comment on return). University
  Coordinator and Administrator view all. A student sees only their **own
  approved** evaluation — never pending, in-progress or returned.
- **BR-54 · Dashboards.** Each role sees only the KPIs it is entitled to:
  Admin/University see global academic numbers; Sede Coordinator sees own-sede
  numbers only; Tutor and Student dashboards contain **no global totals**
  (never MINSA/EsSalud/intern counts) — only their own assigned/personal data.

## 12. Privacy

- **BR-28** No real patient clinical information may be stored. All demo data is
  fictional/anonymized.
