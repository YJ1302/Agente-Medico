# USER ROLES AND PERMISSIONS — UPeU Internado 360

## Roles

| Code | Display | Hierarchy | Purpose |
|------|---------|:--------:|---------|
| `admin` | Administrador | 1 | Platform administration and full oversight. |
| `university_coordinator` | Coordinador Universitario | 2 | Academic authority for the internship at the university. |
| `sede_coordinator` | Coordinador de Sede | 3 | Institutional nexus at a teaching sede. |
| `tutor` | Tutor | 4 | Supervises and evaluates interns per rotation/service. |
| `student` | Interno | 5 | The intern; consumes their own internship information. |

## Operational hierarchy

```
Administrator → University Coordinator → Sede Coordinator → Tutor → Student
```

The tutor evaluates the student and reports to the sede coordinator; the sede
coordinator consolidates and reports to the university. (See BUSINESS_RULES.md
BR-13…BR-16.)

## Permissions matrix

Legend: **F** full (create/edit/manage) · **R** read · **S** scoped to own
records/sede · **—** no access. In Part 1 the operational modules are read/
placeholder; this matrix defines the **target** access model that Parts 2 & 3
enforce with write operations.

| Module / Capability        | Admin | Univ. Coord. | Sede Coord. | Tutor | Student |
|----------------------------|:-----:|:------------:|:-----------:|:-----:|:-------:|
| Dashboard                  |  F    |  R           |  R (sede)   |  R (own) | R (own) |
| Students                   |  F    |  R           |  S (sede)   |  S (assigned) | S (self) |
| Sedes                      |  F    |  R           |  R (own)    |  R    | R |
| Coordinators & Tutors      |  F    |  R           |  S (sede)   |  —    | — |
| Rotations                  |  F    |  R           |  S (sede)   |  S (own) | S (self) |
| Activity monitoring        |  F    |  R           |  S (sede)   |  S (own students) | S (self) |
| Evaluations                |  F    |  R           |  S (sede)   |  S (create own) | S (view own) |
| Documents                  |  F    |  R/approve   |  S (create) |  —    | S (own) |
| Incidents                  |  F    |  R           |  S (sede)   |  S (report) | S (report) |
| Reports                    |  F    |  R           |  R (sede)   |  —    | — |
| Agent Center               |  F    |  R/run       |  R          |  —    | — |
| Alerts                     |  F    |  R           |  R (sede)   |  R (own) | — |
| Agent Executions           |  F    |  R           |  —          |  —    | — |
| Users & Roles              |  F    |  —           |  —          |  —    | — |
| Academic Periods           |  F    |  R           |  —          |  —    | — |
| System Settings            |  F    |  —           |  —          |  —    | — |
| Audit Log                  |  F    |  —           |  —          |  —    | — |

## Navigation visibility (Part 1, enforced)

The sidebar is filtered per role in `app/services/navigation.py`:

- **Users & Roles, System Settings, Audit Log** — Admin only.
- **Agent Executions, Academic Periods** — Admin + University Coordinator.
- **Coordinators & Tutors** — Admin + University + Sede Coordinator.
- All other items — visible to every authenticated role.

## Batch 2A scope (Sedes, Coordinators, Tutors) — enforced server-side

| Capability | Admin | Univ. Coord. | Sede Coord. | Tutor | Student |
|------------|:-----:|:------------:|:-----------:|:-----:|:-------:|
| Sede list / detail | F | R (all) | R (own sede) | R (own) | R (own, basic) |
| Create / edit sede | F | F (academic) | — | — | — |
| Deactivate sede (no active rotations) | F | F | — | — | — |
| **Force**-deactivate sede (has rotations) | F (reason) | — | — | — | — |
| Soft-delete sede | F (reason) | — | — | — | — |
| Coordinator list / detail | F | R (all) | R (own sede) | — | — |
| Create / edit / (de)activate coordinator | F | F | — | — | — |
| Replace principal coordinator | F | F (confirm) | — | — | — |
| Tutor list / detail | F | R (all) | R (own sede) | R (own only) | — |
| Create tutor / reassign / (de)activate | F | F | — | — | — |
| Edit tutor contact/service fields | F | F | S (own sede) | — | — |
| Force-deactivate tutor (has assignments) | F (reason) | — | — | — | — |

Denied access returns **403** (or a safe redirect) and writes an
`authorization_denied` audit entry. Students and tutors cannot reach the
coordinator/tutor management lists; a Sede Coordinator cannot open another
sede's records by editing the URL.

## Batch 2B scope (Rotation assignments) — enforced server-side

| Capability | Admin | Univ. Coord. | Sede Coord. | Tutor | Student |
|------------|:-----:|:------------:|:-----------:|:-----:|:-------:|
| View assignments | all | all | own sede | own (assigned) | own |
| Create / edit (planned) | F | F | own sede | — | — |
| Assign / change / remove tutor | F | F | own sede | — | — |
| Activate / complete / cancel | F | F | own sede | — | — |
| Override institution/community/period conflict | F (reason) | — | — | — | — |
| Reopen completed/cancelled | F (reason) | — | — | — | — |

Cancel/reopen require a mandatory reason. Warnings (workload, unusual duration)
require confirmation but never block. Unauthorized access returns **403** and is
audited (`authorization_denied`); URL manipulation cannot reach another
student's/sede's assignment.

## Batch 2C scope (Activity tracking) — enforced server-side

| Capability | Admin | Univ. Coord. | Sede Coord. | Tutor | Student |
|------------|:-----:|:------------:|:-----------:|:-----:|:-------:|
| Catalog list/detail | F | R (all) | R | R | R |
| Create/edit/(de)activate catalog definitions | F | F | — | — | — |
| Import official catalog | F | F | — | — | — |
| Log own activity entry | — | — | — | — | F (own assignment) |
| Edit/cancel own pending or rejected entry | — | — | — | — | F (own only) |
| View "Mis Actividades" | — | — | — | — | F (own) |
| Verification inbox | R (all) | R (all) | — | R (own students) | — |
| Verify / reject / bulk-verify | F | F | — | F (own students only) | — |
| Reopen a verified entry | F (reason) | — | — | — | — |
| Monitoring page | F | F (all) | F (own sede) | — | — |

Denied access returns **403** and is audited (`authorization_denied`). A
student cannot log or view another student's activities by URL; a tutor
cannot review an entry outside their assigned students.

## Batch 2D scope (Evaluations + dashboards) — enforced server-side

| Capability | Admin | Univ. Coord. | Sede Coord. | Tutor | Student |
|------------|:-----:|:------------:|:-----------:|:-----:|:-------:|
| Evaluation list/detail | all | all | own sede | own (assigned) | own **approved only** |
| Start / save draft / submit | — | — | — | F (own) | — |
| Approve / return for correction | — | — | F (own sede) | — | — |
| Reopen approved | F (reason) | — | — | — | — |
| Dashboard scope | global | global | own sede | own assignments | own (no global data) |

Denied access returns **403** and is audited. A student cannot see a pending,
in-progress or returned evaluation — theirs or anyone else's — by URL. Tutor
and Student dashboards never include global MINSA/EsSalud/intern totals.

## Authentication rules

- Seeded demo accounts only; **no public registration**.
- One account per role for the demo; `Demo123!` password (bcrypt-hashed).
- Session-cookie authentication; unauthenticated access to protected pages
  redirects to `/login`.

---

## Batch 2E — Documents, Incidents & Reports permissions

### Documents
| Action | Admin | University | Sede Coord (own sede) | Tutor | Student |
|--------|:---:|:---:|:---:|:---:|:---:|
| View | all | all | own sede | related to own assignments | own only |
| Create | all types | all types | all types | — | renuncia, cambio de sede, permiso, descanso médico |
| Edit draft | ✔ | ✔ | own sede / own | — | own draft |
| Submit | ✔ | ✔ | ✔ | — | own |
| Start review | ✔ | ✔ | own sede | — | — |
| Approve / Reject | ✔ | ✔ | — | — | — |
| Archive | ✔ | ✔ | — | — | — |
| Reopen (reason) | ✔ | — | — | — | — |

### Incidents
| Action | Admin | University | Sede Coord (own sede) | Tutor | Student |
|--------|:---:|:---:|:---:|:---:|:---:|
| View | all | all | own sede | assigned students / own reports | own only (non-confidential) |
| Create | ✔ | ✔ | own sede | assigned students only | — |
| Review/Action/Resolve/Close/Dismiss | ✔ | ✔ | own sede | — | — |
| Reopen (reason) | ✔ | — | — | — | — |

### Confidentiality
- `restricted` internal notes are never shown to students.
- `confidential` records: Administrator & University Coordinator only, unless the
  record is explicitly assigned (responsible/reporter/creator).
- Confidential data never appears in notifications, dashboard snippets or audit summaries.

### Reports
- Sede Coordinator exports own sede only; Tutor only assigned students where
  permitted; Student may download only their own internship summary. See
  `REPORT_CATALOG.md`.

Every unauthorized request returns 403 (or a safe redirect), writes an
`authorization_denied` audit entry, and does not leak restricted record data.

> Institutional legal/privacy review is required before production use. The
> platform does not assert legal compliance automatically.

---

## Batch 2F — Bulk import & grade permissions

| Import profile | Admin | University | Sede Coord | Tutor | Student |
|----------------|:---:|:---:|:---:|:---:|:---:|
| Students | ✔ | ✔ | own sede | — | — |
| Sedes | ✔ | ✔ | — | — | — |
| Coordinators | ✔ | ✔ | — | — | — |
| Tutors | ✔ | ✔ | — | — | — |
| Rotations | ✔ | ✔ | own sede | — | — |
| Grade components | ✔ | ✔ | — | — | — |

- **Administrator**: full import access, all profiles, may confirm updates.
- **University Coordinator**: students, rotations and grades (plus sedes/staff);
  no system user/role import beyond the above.
- **Sede Coordinator**: own-sede students/rotations only (scope enforced per row);
  no global grade import.
- **Tutor**: no bulk master-data import (may later upload permitted grade sheets for
  assigned students only — reserved for the next batch).
- **Student**: no import access.

- **Grade viewing** (`/grades`): Administrator and University Coordinator only.
  Students never see the raw grade matrix.
- Every unauthorized import/grade request returns **403** and is audited.
