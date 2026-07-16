# DOCUMENT WORKFLOW — UPeU Internado 360 (Batch 2E)

Formal document management for institutional communications. No document is ever
sent automatically — **human approval is always required**.

## Document types

`resignation` (Renuncia al internado), `sede_change` (Cambio de sede),
`rotation_change` (Cambio de rotación), `tutor_designation` (Designación de
tutor), `coordinator_designation` (Designación de coordinador), `permission`
(Permiso), `medical_leave` (Descanso médico), `internship_interruption`
(Interrupción de internado), `internship_resumption` (Reanudación de internado),
`grade_correction` (Corrección de nota), `incident_report` (Informe de
incidente), `official_communication` (Comunicación oficial), `other` (Otro).

## Status machine

```
draft ──submit──▶ submitted ──start_review──▶ under_review ──approve──▶ approved ──archive──▶ archived
                                                   │
                                                   └──reject──▶ rejected ──return──▶ draft
approved | archived ──reopen (Admin + reason)──▶ draft
```

Allowed transitions (enforced in `DocumentService.TRANSITIONS`):

| From | To | Trigger | Authority |
|------|----|---------|-----------|
| draft | submitted | submit | author / global / own-sede coordinator |
| submitted | under_review | start_review | Admin, University, own-sede Coordinator |
| under_review | approved | approve | Admin, University |
| under_review | rejected | reject (**reason required**) | Admin, University |
| rejected | draft | return_to_draft | author / global / own-sede coordinator |
| approved | archived | archive | Admin, University |
| approved / archived | draft | reopen (**Administrator only, reason required**) | Admin |

## Rules

- Drafts are the only editable status; submitted/approved/archived/rejected are **locked** for field edits.
- Rejection requires a reason; the reason is stored and shown on the detail page.
- Archiving asks for confirmation in the UI.
- Reopening an approved/archived document is Administrator-only and requires a reason.
- Every transition is written to `status_history` (append-only) **and** audited.
- No automatic sending; a human always decides.

## Numbering

Codes are `DOC-YYYY-NNNN`, generated server-side, unique, sequential per year,
concurrency-safe (atomic increment on `document_sequences`; UNIQUE code is the
backstop). Not editable by normal users. See `app/services/numbering.py`.

## Formal communication route

```
Estudiante / Universidad → Unidad de Docencia del Hospital → Coordinador de Sede → Universidad
```

The Sede Coordinator may communicate directly with the university when authorized.

## Templates

Reusable, editable drafts (never auto-approved) exist for: resignation,
sede change, rotation change, incident report and official communication. The
resignation template follows the attached reference structure (institution
header, place/date, document number, recipient, subject, greeting, student/sede
context, request, attachment reference, closing, signatory). See the
`document_templates` table and `_seed_document_templates()` in `app/seed.py`.

## Detail tabs

`Resumen · Contenido · Adjuntos · Flujo · Historial · Auditoría`.

## Known limitations

- The formal PDF is generated from stored fields; institutional legal/privacy
  review is required before any document is used officially.
- Excel bulk import of documents is **not** implemented in this batch (next batch).
