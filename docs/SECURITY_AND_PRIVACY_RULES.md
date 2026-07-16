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

### Phase 3A/3B — AI Coordinator Assistant (dual provider)

The assistant (`app/services/ai_assistant_service.py`,
`app/agents/assistant_llm_client.py`) is the first feature in this codebase to
call an external AI provider. It supports **two interchangeable providers**,
selected by `AI_ASSISTANT_PROVIDER` (`anthropic`, the default, or `gemini`) —
both share the same query layer, system prompt, RBAC, redaction, rate
limiting, timeout and audit behavior described below; only the outbound
transport call differs. Its safety posture:

- **Deterministic queries first.** Every one of the 11 supported questions is
  answered by a plain, scoped repository query (see
  `AI_ASSISTANT_ARCHITECTURE.md`). The LLM is invoked, if at all, only
  afterwards, to phrase the already-computed result — never to decide what
  data to fetch or to fetch it itself.
- **The full database is never sent to the model.** Only the small
  structured payload (title, headers, up to 20 rows, count) already produced
  by the scoped query is included in the prompt.
- **Prompt-injection resistance.** The question and any embedded instructions
  are always sent as plain user content, never merged into the system role.
  The system prompt explicitly instructs the model to treat any instruction
  found inside the question or the data as content to describe, not as a
  command, and to never compute or suggest a final grade.
- **Scope enforced twice.** The route guard (`require_management`) blocks
  Students and Tutors outright (403, audited). Inside the service,
  `can_ask()` additionally restricts the two grade-related questions to
  Admin/University Coordinator, matching the existing `/grades` boundary.
- **Redaction before assembly.** Confidential incidents are shown only as
  `(incidencia confidencial)` unless the caller is a global viewer;
  confidential documents are excluded entirely from the assistant's answers.
  This redaction happens before the data is ever put in the on-screen
  answer, the audit log, or the LLM payload.
- **No grade invention.** The assistant never computes or estimates a final
  grade; `grade_components_missing` only reports the same
  weight/score-is-null signals `GradeService.final_grade_note()` already
  surfaces elsewhere.
- **No mutation capability.** There is no write endpoint in this module —
  `GET /assistant` and `POST /assistant/ask` only ever return an answer.
  Approving evaluations, closing incidents, sending documents or confirming
  grade weights remain human-only actions in their own modules.
- **Graceful degradation, either provider.** If `AI_ASSISTANT_ENABLED` is
  false, the selected provider's API key is unset, its SDK package
  (`anthropic` or `google-genai`) is not installed, the call exceeds
  `AI_ASSISTANT_TIMEOUT_SECONDS` (enforced uniformly via a thread-pool
  timeout, independent of what the provider's own SDK supports), the key is
  invalid, the account's quota is exhausted, or the provider errors for any
  other reason, `AssistantLLMClient.summarize()` returns `None` — never
  raises — and the service falls back to a deterministic templated
  narrative. The assistant always answers, on either provider, online or
  offline.
- **Rate limiting.** An in-process sliding-window limiter
  (`AI_ASSISTANT_RATE_LIMIT_PER_MINUTE`, default 10/min per user) rejects
  excess requests before any query runs; the rejection itself is audited
  (`ai_assistant_rate_limited`).
- **Audit.** Every call writes `ai_assistant_query` (intent, truncated
  question, result count) before any LLM call and `ai_assistant_response`
  (intent, whether the LLM summary was used, result count) after. Full row
  data and confidential content are never written to the audit log.
- **Secrets.** `ANTHROPIC_API_KEY` and `GEMINI_API_KEY` are read only from
  the environment (`app/config.py::Settings`), are never logged, audited, or
  rendered in any template, and are absent from `.env.example` (blank
  placeholders only). Only the key matching the selected
  `AI_ASSISTANT_PROVIDER` needs to be set — the unused provider's key may
  remain blank.

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
