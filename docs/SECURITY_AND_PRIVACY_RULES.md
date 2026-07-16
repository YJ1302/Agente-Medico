# SECURITY AND PRIVACY RULES — UPeU Internado 360

## 1. Privacy notice (must remain visible)

> **This prototype contains fictional demonstration data. It must not be used to
> store identifiable patient clinical information.**

Shown on the login page and enforced as a project rule. No real student or
patient data from the reference documents is imported; the uploaded Excel is
used only to understand structure.

## 2. Data classification

| Class | Examples | Rule |
|-------|----------|------|
| Prohibited | Patient clinical records, diagnoses, real identifiable patient data | **Never stored.** |
| Sensitive (future) | Real student PII, evaluation scores | Minimize; access-controlled; audit-logged. |
| Demo | Fictional names, codes, contacts | Allowed for the prototype only. |

## 3. Authentication & sessions

- Passwords stored **only** as bcrypt hashes (`passlib[bcrypt]`).
- No plain-text passwords logged or persisted.
- Session-cookie authentication via Starlette `SessionMiddleware`, signed with
  `SECRET_KEY`; cookie is **http-only**, **same-site=lax**, and **https-only**
  in production (`is_production`).
- Configurable session lifetime (`SESSION_MAX_AGE`, default 8h).
- **No public registration**; accounts are provisioned/seeded.

## 4. Authorization (RBAC)

- Five roles with a defined permissions matrix (USER_ROLES_AND_PERMISSIONS.md).
- Protected routes require a valid session (`require_identity`); otherwise
  redirect to `/login`.
- Navigation and, in later parts, write operations are filtered per role.

## 5. Input validation & CSRF

- Server-side validation is authoritative (Pydantic/typed forms).
- State-changing actions use **POST** with same-site cookies (mitigates CSRF for
  the prototype). A dedicated CSRF token will be added with real forms in
  Part 2; the architecture (POST + same-site) is already in place.

## 6. Secrets & configuration

- No hardcoded production secrets. All configuration via `.env` (git-ignored).
- `SECRET_KEY` must be replaced with a strong random value outside local demos.
- `.env.example` documents every variable without real secrets.

## 7. File uploads (architecture only in Part 1)

Uploads are **not** implemented yet. The reserved design (for Part 2):

- Validate MIME type and extension against an allowlist.
- Enforce a maximum size; stream to disk, never trust the client filename.
- Store outside the web root; serve via authorized, access-checked endpoints.
- Scan/quarantine untrusted files; never execute uploaded content.
- `DocumentRecord.file_path` is the reserved hook.

## 8. Audit logging

- `AuditLog` schema is provided in Part 1 (append-only design).
- **Rule:** all important actions must eventually be recorded (actor, action,
  entity, timestamp, IP). Wiring is completed progressively in Parts 2 & 3.
- **Batch 2A actions wired:** the full sede/coordinator/tutor lifecycle —
  `create_sede`, `update_sede`, `deactivate_sede`, `reactivate_sede`,
  `force_deactivate_sede`, `soft_delete_sede`, `create_sede_coordinator`,
  `update_sede_coordinator`, `reassign_sede_coordinator`,
  `replace_sede_coordinator`, `deactivate_sede_coordinator`,
  `reactivate_sede_coordinator`, `create_tutor`, `update_tutor`,
  `reassign_tutor`, `deactivate_tutor`, `reactivate_tutor`,
  `force_deactivate_tutor`, plus `authorization_denied`.
- **Mandatory reasons** are captured for force-deactivation, soft-delete,
  coordinator replacement and tutor reassignment. The audit `detail` payload is
  sanitized against a denylist so passwords, password hashes, CSRF tokens,
  session contents and document ids never appear.
- **Batch 2B rotation actions wired:** `create_rotation_assignment`,
  `update_rotation_assignment`, `assign_tutor`, `reassign_tutor`, `remove_tutor`,
  `activate_rotation_assignment`, `complete_rotation_assignment`,
  `cancel_rotation_assignment`, `reopen_rotation_assignment`,
  `override_rotation_conflict`, `conflict_validation_failed`,
  `create_pending_evaluation`. Mandatory reasons are stored for cancellation,
  reopen and every conflict override (institution/community/period).
- **Batch 2C activity actions wired:** `create_activity_definition`,
  `update_activity_definition`, `deactivate_activity_definition`,
  `create_student_activity`, `update_student_activity`,
  `submit_student_activity`, `cancel_student_activity`,
  `verify_student_activity`, `reject_student_activity`,
  `correct_student_activity`, `reopen_student_activity`,
  `bulk_verify_student_activities`, `import_activity_catalog_preview`,
  `import_activity_catalog_confirmed`.

## 8b. Patient-identifier heuristic (Batch 2C)

- `app/services/privacy_validator.py` scans activity `notes` and
  `evidence_reference` before saving, blocking obvious patient identifiers:
  8-digit DNI-like numbers, "HC"/"historia clínica"/"N° historia" labels,
  email addresses, Peruvian mobile-phone patterns, and phrases like "nombre
  del paciente". A match is rejected with a visible warning, never stored or
  logged. This is a **practical heuristic, not a guarantee** of
  de-identification — no external service or AI is used.
- Every activity entry form displays: *"No registre nombres, documentos,
  números de historia clínica ni otra información identificable del
  paciente."*

## 9. AI / agent safety

- Agents are deterministic in Part 1; no data leaves the machine.
- Every agent recommendation requires **human approval**
  (`requires_human_approval`).
- No agent sends a final institutional communication autonomously.
- When real AI is added, prompts must exclude prohibited patient data and
  responses must be treated as recommendations, not decisions.

## 10. Logging hygiene

- Use the shared logger; never log passwords, tokens or session contents.
- Access logs are quieted; application logs are level-controlled via
  `LOG_LEVEL`.

## 11. Operational checklist for non-demo use

- [ ] Replace `SECRET_KEY`; set `APP_ENV=production`, `DEBUG=false`,
      `DEMO_MODE=false`.
- [ ] Move to PostgreSQL with least-privilege credentials.
- [ ] Enable HTTPS everywhere; verify `https_only` cookies.
- [ ] Turn on full audit logging and backups.
- [ ] Review the permissions matrix against real institutional policy.

---

## Batch 2E — Attachments, confidentiality & audit

### Secure attachments
See `FILE_UPLOAD_SECURITY.md`. Summary: extension + MIME + magic-byte validation;
server-generated UUID filenames; storage outside `app/static`; authorized
download-only route with scope re-check; path-traversal-proof; draft/open-only
deletion (Administrator override with reason); uploaded files never executed;
upload/download/delete audited; visible pre-upload privacy warning. **Do not
store patient-identifying clinical records.**

### Confidentiality
`visibility ∈ {normal, restricted, confidential}` on documents and incidents,
enforced server-side (never merely hidden in the UI). Students never see
restricted internal notes; confidential records are limited to Administrator and
University Coordinator unless explicitly assigned; confidential data is redacted
from alerts and excluded from audit summaries and dashboard snippets.

### Audit (Batch 2E actions)
Documents: `create_document`, `update_document`, `submit_document`,
`start_document_review`, `approve_document`, `reject_document`,
`archive_document`, `reopen_document`, `upload_document_attachment`,
`download_document_attachment`, `delete_document_attachment`,
`generate_document_pdf`.
Incidents: `create_incident`, `update_incident`, `assign_incident`,
`change_incident_status`, `resolve_incident`, `close_incident`,
`dismiss_incident`, `reopen_incident`, `upload_incident_attachment` (+download/delete).
Reports: `generate_report`, `export_report_excel`, `export_report_pdf`,
`generate_student_summary`.
Audit details exclude passwords, CSRF tokens, session data, file contents,
confidential body text and unnecessary personal data (denylist + sanitizer).

> Institutional legal/privacy review is required before production. The platform
> does not claim legal compliance automatically.

---

## Batch 2F — Import safety & audit

- Uploaded import files are validated (extension `.xlsx`/`.xlsm`, MIME, size,
  readability, malformed workbook, duplicate sheets), stored **outside**
  `app/static` (`var/imports/`), never publicly served, and **deleted after import**
  unless `IMPORT_RETAIN_FILES` is set. Row count is bounded by `IMPORT_MAX_ROWS`.
- Imports are transactional (all-or-nothing option), reuse authoritative validators,
  and guard against stale/duplicate confirmation.
- New audit actions: `upload_import_file`, `create_import_batch`,
  `map_import_columns`, `validate_import_batch`, `confirm_import_batch`,
  `cancel_import_batch`, `import_row_created/updated/skipped/failed`,
  `download_import_error_report`, `import_grade_component`,
  `update_grade_component_from_import`. Audit details never store passwords, CSRF
  tokens, full file contents or unnecessary sensitive values.
- Grade changes preserve full history (`grade_component_history`); an approved grade
  is never overwritten silently. **No patient data** is imported.
- Institutional legal/privacy review remains required before production.
