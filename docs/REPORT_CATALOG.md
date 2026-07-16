# REPORT CATALOG — UPeU Internado 360 (Batch 2E)

Every report applies **role scope before gathering data**, carries generation
metadata (date, filters, generating user), and can be exported to Excel
(openpyxl) and printable PDF (fpdf2). Patient information is never included.
Export actions are audited (`generate_report`, `export_report_excel`,
`export_report_pdf`, `generate_student_summary`).

## Catalog

| # | Key | Title | Roles |
|---|-----|-------|-------|
| 1 | `students_by_sede` | Internos por sede | Admin, University, Sede |
| 2 | `students_by_institution` | Internos por tipo de institución | Admin, University, Sede |
| 3 | `rotations_status` | Rotaciones activas/planificadas/completadas | Admin, University, Sede |
| 4 | `rotations_ending_soon` | Rotaciones por finalizar | Admin, University, Sede |
| 5 | `missing_tutor` | Rotaciones sin tutor asignado | Admin, University, Sede |
| 6 | `activity_progress_student` | Avance de actividades por interno | Admin, University, Sede, Tutor |
| 7 | `activity_progress_sede` | Avance de actividades por sede | Admin, University, Sede |
| 8 | `pending_verifications` | Verificaciones de tutor pendientes | Admin, University, Sede, Tutor |
| 9 | `evaluations_status` | Evaluaciones pendientes/enviadas/aprobadas | Admin, University, Sede |
| 10 | `tutor_workload` | Carga de trabajo de tutores | Admin, University, Sede |
| 11 | `open_incidents_severity` | Incidencias abiertas por severidad | Admin, University, Sede |
| 12 | `documents_status_type` | Documentos por estado/tipo | Admin, University, Sede |
| 13 | `internship_summary` | Resumen de internado por interno | Admin, University, Sede |
| 14 | Student summary | Registro consolidado por interno | Admin, University, Sede, Tutor, Student (own) |

## Scope rules

- **Sede Coordinator** exports only their own sede.
- **Tutor** exports only assigned students where permitted (reports 6 and 8, and
  student summaries of supervised students).
- **Student** may download only **their own** internship summary
  (`/reports/student/{id}` and its exports), and only approved/final information.
- Confidential documents/incidents are excluded from reports for non-global roles.

## Student internship summary (report 14)

A consolidated record: profile, institution type, sede history, rotation
timeline, tutors, activity progress, evaluation results, approved documents,
relevant incident summary (respecting visibility), alerts summary and completion
status. Available on screen, as printable PDF and as Excel. A student sees only
their own approved/final information; confidential incidents and internal notes
are excluded.

## Routes

- `GET /reports` — index (only permitted reports listed).
- `GET /reports/view/{key}` — on-screen table.
- `GET /reports/export/{key}.{xlsx|pdf}` — download.
- `GET /reports/student/{id}` — student summary on screen.
- `GET /reports/student/{id}/export.{xlsx|pdf}` — student summary download.

## Known limitations

- Excel **bulk import** is not part of this batch (next batch).
- Reports are read-only snapshots; no scheduling/emailing.
