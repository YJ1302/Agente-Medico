# INCIDENT WORKFLOW — UPeU Internado 360 (Batch 2E)

Management of situations affecting the normal development of the internship.
Incident history is append-only and never silently overwritten.

## Incident types

`absence` (Inasistencia), `repeated_tardiness` (Tardanza reiterada),
`activity_noncompliance` (Incumplimiento de actividades), `conduct` (Problema de
conducta), `health` (Problema de salud), `student_complaint` (Queja del
estudiante), `tutor_complaint` (Queja del tutor), `sede_complaint` (Queja de la
sede), `rotation_interruption` (Interrupción de rotación), `resignation`
(Renuncia), `accident` (Accidente), `confidentiality` (Confidencialidad),
`other` (Otro).

## Severity

`low · medium · high · critical`. **High and critical** incidents generate
alerts; **critical** incidents are surfaced prominently on authorized dashboards
and in the incident list.

## Status machine

```
open ──review──▶ under_review ──action──▶ action_required ──resolve──▶ resolved ──close──▶ closed
        │              │                                                   │
        └──dismiss─────┘ (reason required) ──▶ dismissed        resolved | closed ──reopen──▶ reopened
```

Allowed transitions (`IncidentService.TRANSITIONS`):

| From | To | Trigger | Notes |
|------|----|---------|-------|
| open | under_review | start_review | |
| open / under_review | dismissed | dismiss | **reason required** |
| under_review | action_required | mark_action_required | |
| under_review / action_required | resolved | resolve | **resolution comments required** |
| resolved | closed | close | **resolution must be present** |
| resolved / closed | reopened | reopen | **Administrator only, reason required** |
| reopened | under_review / action_required | continue handling | |

## Rules

- Resolution requires comments; closing requires a resolution already recorded.
- Dismissal requires a reason; reopen requires Administrator + reason.
- Every status change is written to `status_history` (append-only) and audited.
- Confidential incidents and restricted internal notes are never exposed outside
  authorized scope (see `SECURITY_AND_PRIVACY_RULES.md`).

## Transition authority

- **Manage** (review / action / resolve / close / dismiss): Administrator,
  University Coordinator, and the **own-sede** Sede Coordinator.
- **Reopen**: Administrator only.
- **Create**: Administrator, University, Sede Coordinator (own sede), Tutor
  (only for assigned students).

## Detail tabs

`Resumen · Seguimiento · Adjuntos · Historial · Auditoría`.

## Deterministic alerts (rule engine)

`high_severity_incident`, `critical_incident`, `incident_due_soon`,
`incident_overdue`, `unresolved_incident_near_rotation_end`. Confidential
incident titles are redacted in alert text.
