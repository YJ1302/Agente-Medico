# DEMO GUIDE — UPeU Internado 360

A practical guide to demonstrate Phase 1 · Part 1 to Universidad Peruana Unión.

## 1. How to start the system

```bat
venv\Scripts\activate
python -m app.seed          :: loads fresh fictional demo data
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Works offline (only icons/charts use an optional
CDN). Ensure `DEMO_MODE=true` in `.env` so demo credentials appear on login.

## 2. Which account to use

Password for all accounts: **`Demo123!`** (click a row on the login page to
autofill).

| To show… | Use |
|----------|-----|
| The full product (main demo) | `admin@internado360.demo` |
| University-level view | `coordinator@internado360.demo` |
| Sede-level view | `sede@internado360.demo` |
| Tutor view | `tutor@internado360.demo` |
| Intern view | `student@internado360.demo` |

Start and spend most of the demo on the **Administrator** account.

## 3. Which screens to demonstrate

1. **Login** — institutional branding, demo credentials, privacy notice.
2. **Administrator dashboard** — the centerpiece (see §4).
3. **Rotaciones** — real assignments; point out the "Sin tutor" row.
4. **Alertas** — the four automatically detected alerts.
5. **Centro de Agentes** — click **"Ejecutar todos"**.
6. **Ejecuciones de Agentes** — structured results + "Requiere aprobación".
7. **Evaluaciones** — the official 3-area / 0–4 instrument.
8. Switch role (logout → login as tutor) to show role-based dashboards & menu.

## 4. What each dashboard card means

**Stat cards (top row):**
- **Internos activos** — active interns in the system.
- **Internos MINSA / EsSalud** — split by provider institution.
- **Sedes activas** — teaching hospitals/health centers.
- **Rotaciones activas** — assignments currently in progress.
- **Evaluaciones pendientes** — evaluations not yet submitted.
- **Alertas abiertas** — open items needing attention.
- **Cambios de rotación próximos** — rotations starting within ~2 weeks.

**Panels:**
- **Distribución de rotaciones** (doughnut) — load per rotation type.
- **Internos por institución** (bar) — MINSA vs EsSalud.
- **Rotaciones por finalizar** — rotations ending within 7 days.
- **Alertas recientes** — latest detected issues.
- **Actividad reciente de agentes** — recent agent runs.
- **Acciones rápidas** / **Estado del sistema** — shortcuts + health.
- **Periodo académico actual** — the current bimonthly block.

## 5. How to explain the agent architecture

Say this: *"The platform is agent-ready. Today the agents run **deterministic
business rules** — no external AI is called — so results are explainable and
safe. Crucially, the system separates three stages: **automated detection →
agent recommendation → human decision**. Every agent result is stored and
marked 'requires human approval'. No agent ever sends an official communication
by itself. When we enable real AI in a later phase, it plugs into the same
interface without changing the rest of the system."*

Demonstrate by running the agents and opening **Ejecuciones de Agentes** to show
the structured `findings` and `recommended_actions`, each flagged for human
approval.

## 6. How to explain Parts 2 and 3

*"This first deliverable is the **foundation**: the data model for the whole
system, authentication with roles, the institutional interface, the working
administrator dashboard, and the agent architecture. **Part 2** adds the
operational workflows — registering and managing interns, sedes, tutors,
rotations, activities and the full evaluation capture. **Part 3** adds documents
and incidents management, reporting, audit logging throughout, and the first
real AI-assisted features, always with human approval."*

## 7. Five-minute demonstration script

- **0:00 – 0:40 — Login.** Show branding, the demo credentials box and the
  privacy notice. Log in as Administrator.
- **0:40 – 2:10 — Dashboard.** Walk the stat cards; explain MINSA/EsSalud split;
  show both charts; point to "Rotaciones por finalizar" and "Alertas recientes";
  mention the current academic period banner.
- **2:10 – 3:00 — Rotaciones & Alertas.** Open Rotaciones, highlight the
  **"Sin tutor"** row. Open Alertas, show the four detected alerts and the
  "detection → recommendation → human decision" banner.
- **3:00 – 4:00 — Agents.** Open Centro de Agentes, click **"Ejecutar todos"**,
  then open Ejecuciones de Agentes to show structured results and the
  human-approval flag.
- **4:00 – 4:40 — Roles.** Log out, log in as **Tutor**; show the role-specific
  dashboard and the filtered sidebar.
- **4:40 – 5:00 — Close.** Summarize the foundation and preview Parts 2 & 3.

## 7b. Batch 2A flow (Sedes · Coordinadores · Tutores)

1. **Sedes** → show search/filters (try "Sin coordinador" → *C.S. Santa Rosa*).
   Open **H. Vitarte**, walk the tabs (Resumen · Coordinador · Tutores · Internos
   · Rotaciones · Alertas · Auditoría).
2. **Deactivation guard:** on H. Vitarte press *Desactivar* — it's blocked
   because active rotations exist. As **admin**, force it with a reason (the only
   role allowed) and note the audit entry. On **C.S. Santa Rosa** show a normal
   deactivation (no rotations).
3. **Coordinadores de Sede** → *Nuevo coordinador*. Assign to a sede that already
   has a principal → the replacement warning appears; tick "reemplazar" to
   complete the controlled hand-over (previous coordinator deactivated + audited).
   The account is created atomically; a temporary password is shown once.
4. **Tutores** → filter by **Carga = Sobre el umbral** to show the workload
   indicator (Dr. Martín Salas 7/5). Open a tutor's detail (tabs + workload bar).
   Try to deactivate a tutor with active assignments → blocked; as admin, force
   with a reason.
5. **Scope:** log in as **sede@** (Coordinador de Sede) — the sidebar and every
   record are limited to their own sede; opening another sede's URL returns 403.

## 7c. Batch 2B flow (Rotaciones)

1. **Rotaciones** → show search + the filter row (period, rotation, sede, tutor,
   status, institution, with/without tutor); note the conflict indicator and
   evaluation-status columns. Open **Cronograma** and switch grouping
   (interno / sede / periodo / rotación).
2. **Create** → *Nueva rotación*. Pick a student who already has an active
   rotation and overlapping dates → the **"Validación de asignación"** panel
   lists the blocking conflict; the form keeps your values. Fix the dates and
   save.
3. **Override demo** → as **admin**, place an EsSalud interno at a MINSA sede →
   the institution-mismatch block appears with an override-reason field
   (admin-only). Enter a reason to proceed (recorded in Auditoría).
4. **Lifecycle** → open a planned rotation → **Activar** → **Completar**
   (confirm). Open the **Evaluación** tab: a *pending* evaluation with 15
   criteria was created automatically. Try **Cancelar** → a reason is required.
5. **Reopen** → on a completed rotation, only **admin** sees **Reabrir**
   (mandatory reason). University Coordinator cannot reopen.
6. **Tutor** tab → change/remove the tutor (only active tutors of the sede);
   removing one raises a missing-tutor alert visible in **Alertas**.
7. **Idioma** → click **Traducir** in the top bar to switch the interface
   chrome to English and back.

## 7d. Batch 2C flow (Actividades)

1. **Catálogo de Actividades** → filter by rotación/categoría; open **Importar
   catálogo oficial** to show the idempotent sync preview (129 official
   definitions from the 4 specialty documents).
2. Open a student's active rotation (e.g. `student@`'s Medicina rotation,
   `/rotations/1`) → **Actividades** tab: shows fixed-target progress bars
   (one intern is at ~20%, another rotation shows ~80%, another **120%** — bar
   capped at 100% but the true count stays visible), NA activities with "sin
   meta numérica", pending/verified/rejected counters.
3. As **student@**, register a new activity — point out the privacy warning
   banner. Try entering "HC 12345678" in notes → blocked with the identifier
   warning.
4. As **tutor@**, open **Bandeja de Verificación** → verify one entry, reject
   another (comment required) → show the rejected entry's history preserved
   after the student corrects and resubmits it.
5. **Monitoreo de Actividades** (admin/university/sede-coordinator) → point out
   the tutor with a verification backlog (Dr. Martín Salas) and the rotation
   ending soon with an at-risk target — both also visible as alerts in
   **Alertas**.

## 7e. Batch 2D flow (Evaluaciones + paneles por rol)

1. Log in as **tutor@** → dashboard shows only assigned students, active
   rotations, evaluations to complete and the activity verification queue
   (no global MINSA/EsSalud numbers). Open an evaluation → score the 15
   criteria (watch the live area/final totals update in JavaScript) → **Enviar
   para aprobación**.
2. Log in as **sede@** → dashboard shows own-sede KPIs only. Open
   **Evaluaciones**, find the submitted one → **Aprobar**, or **Devolver**
   with a mandatory comment (show the returned-for-correction banner if you
   devuelve it, then log back in as tutor@ to correct and resubmit).
3. Log in as **student@** → dashboard shows *only* their own rotation, tutor,
   sede, days remaining, activity progress and evaluation status — open
   **Mi evaluación**: only the **approved** one is visible; a pending one
   returns 403 if the URL is guessed.
4. Open an **approved** evaluation (any role that can see it) → **Imprimir**
   for the printable view.
5. As **admin**, open an approved evaluation → **Reabrir** (mandatory reason)
   → note it returns to `in_progress` and the audit trail preserves the prior
   approval.

## 8. Reset between demos

Re-run `python -m app.seed` to restore a clean dataset (alerts, pending
evaluation and the missing-tutor scenario are recreated).

---

## Batch 2E demo — Documents, Incidents, Reports

Seeded data (fictional): 9 documents covering every status (incl. a resignation
example modelled on the reference, a student change-of-sede draft, and an overdue
document), 6 incidents (open/low, high, critical, resolved, confidential, overdue)
and 5 document templates.

Suggested walkthrough:
1. **Admin / University** → `/documents`: open the resignation (`DOC-2026-0007`),
   view tabs, download the formal **PDF**. Take a draft through
   submit → review → approve → archive.
2. **Sede Coordinator** (`sede@`) → confirm own-sede-only visibility; try a
   sede-2 document/incident URL → 403.
3. **Incidents** → open the **critical** incident (prominent banner); resolve
   (requires comments) then close (requires resolution). Note high/critical
   alerts on `/alerts`.
4. **Reports** → `/reports`: view a report, export **Excel** and **PDF**; open a
   **student internship summary** and export it.
5. **Student** (`student@`) → sees only own documents/incidents and only their own
   internship summary; cannot open management reports.

Attachments: on a **draft** document, Adjuntos tab → upload a PDF/PNG; note the
privacy warning and that only authorized roles can download.

---

## Batch 2F demo — Bulk import & grades

Seeded: 2 grade schemes (null weights), example blank-vs-zero scores, and 3 import
batches (one confirmed, one with errors, one grade preview).

Walkthrough (Admin or University):
1. **Centro de Importación** (`/imports`) → pick **Internos** → upload a small
   `.xlsx` (columns Código, Nombre, DNI/CE, Correo, Ciclo, Institución, Sede) →
   select sheet → adjust the auto-mapping → choose a mode → **Validar** → review the
   preview (valid/warning/error counts) → **Confirmar**. Download the error report
   if any row failed.
2. Try mode **«Cancelar todo si hay errores»** with one bad row → nothing is written.
3. **Notas académicas** (`/grades`) → open a scheme → note **"Fórmula pendiente de
   confirmación"** and the matrix where a blank cell shows "sin registro" (distinct
   from 0). Import grade components via `/imports/new?profile=grade_components`
   (choose the scheme first).
4. Confirm RBAC: a Student gets **403** on `/imports`; a Tutor cannot import master data.
