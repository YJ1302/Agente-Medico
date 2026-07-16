# DATA DICTIONARY — UPeU Internado 360

All tables include `id` (integer PK). Most include `created_at`, `updated_at`
(TimestampMixin) and, where noted, `is_active`, `is_deleted`, `deleted_at`
(SoftDeleteMixin). Types are shown in a SQLite/PostgreSQL-portable form.

## roles
| Column | Type | Notes |
|--------|------|-------|
| code | str(50) unique | `admin`, `university_coordinator`, `sede_coordinator`, `tutor`, `student` |
| name | str(120) | Display name |
| description | text | Optional |
| hierarchy_level | int | Lower = higher authority |

## users *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| email | str(255) unique | Login identifier |
| hashed_password | str(255) | bcrypt hash only |
| full_name | str(160) | |
| phone | str(40) | Optional |
| role_id | FK roles.id | One role per user (Part 1) |

## institution_types
| Column | Type | Notes |
|--------|------|-------|
| code | str(20) unique | `MINSA` / `ESSALUD` |
| name | str(120) | |
| placement_method | str(60) | `ranking` / `examen` |
| has_community_component | bool | MINSA = true |
| description | text | |

## sedes *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| name | str(200) | Full name |
| short_name | str(80) | Display short name |
| sede_type | str(40) | `hospital` / `health_center` |
| city, address | str | Optional |
| institution_type_id | FK institution_types.id | MINSA/EsSalud |

## sede_coordinator_profiles *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| user_id | FK users.id unique | Login account (role `sede_coordinator`) |
| sede_id | FK sedes.id | Coordinated sede |
| specialty | str(120) | |
| office_phone | str(40) | |
| is_principal | bool | *(Batch 2A)* One active principal coordinator per sede |

## tutor_profiles *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| user_id | FK users.id unique | Login account (role `tutor`) |
| sede_id | FK sedes.id | |
| specialty | str(120) | *(Batch 2A)* Medical specialty (distinct from service) |
| service | str(120) | Clinical service (e.g. Medicina Interna) |
| contact_phone | str(40) | |

> **Config (not a column):** `TUTOR_ASSIGNMENT_WARNING_THRESHOLD` (default 5) —
> active/planned assignments above which a tutor's workload is flagged (warning
> only, never a block). Levels: normal (`< threshold-1`), near (`threshold-1`),
> above (`>= threshold`).

## students *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| user_id | FK users.id unique nullable | Optional account |
| student_code | str(30) unique | |
| full_name | str(160) | Fictional |
| document_id | str(20) | Fictional demo id |
| email, phone | str | |
| cycle | str(2) | `13` / `14` |
| institution_type_id | FK nullable | MINSA/EsSalud |
| sede_id | FK nullable | |
| internship_start / internship_end | date | ~365-day span |
| profile_status | str(20) | `complete` / `incomplete` |

## academic_periods
| Column | Type | Notes |
|--------|------|-------|
| name | str(80) | e.g. "Enero - Febrero 2026" |
| code | str(30) unique | e.g. "ENE-FEB-2026" |
| year | int | |
| ordinal | int | 1..6 within the year |
| start_date / end_date | date | |
| is_current | bool | Exactly one true |

## rotation_types
| Column | Type | Notes |
|--------|------|-------|
| name | str(120) unique | Medicina Interna, Cirugía General, Pediatría, Gineco-Obstetricia, Comunitario |
| code | str(30) unique | MED, CIR, PED, GO, COM |
| description | text | |
| is_core | bool | Core vs additional component |
| typical_weeks | int | |

## rotation_assignments *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| student_id | FK students.id | |
| rotation_type_id | FK rotation_types.id | |
| sede_id | FK sedes.id | |
| period_id | FK academic_periods.id | |
| tutor_id | FK tutor_profiles.id **nullable** | Null → missing-tutor alert |
| start_date / end_date | date | Drives ending-soon rule |
| status | str(20) | `planned`/`active`/`completed`/`cancelled` |
| notes | text | *(2B)* Free-text notes |
| cancellation_reason | text | *(2B)* Mandatory on cancel |
| reopened_reason | text | *(2B)* Mandatory on admin reopen |
| override_reason | text | *(2B)* Recorded on admin conflict override |
| completed_at / cancelled_at / reopened_at | datetime | *(2B)* Lifecycle timestamps |
| created_by_user_id / updated_by_user_id | FK users.id nullable | *(2B)* Actor traceability |

> **Config (not columns):** `ROTATION_DURATION_TOLERANCE_RATIO` (0.4),
> `ROTATION_PERIOD_WARNING_DAYS` (14), `ROTATION_PERIOD_BLOCK_DAYS` (60) drive
> the unusual-duration and period-date conflict checks.

## evaluations *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| assignment_id | FK rotation_assignments.id unique | One evaluation per assignment |
| student_id | FK students.id | |
| tutor_id | FK tutor_profiles.id nullable | |
| status | str(20) | `pending`/`in_progress`/`submitted`/`returned_for_correction`/`approved` |
| score_knowledge / score_performance / score_attitude | float | Area totals (0–20); **always server-recomputed** from criteria, never trusted from the browser |
| final_score | float | Average of the three areas (0–20, 2 decimals) |
| comments | text | Tutor's comments |
| submitted_at / submitted_by_user_id | datetime / int nullable *(2D)* | |
| reviewed_at / reviewed_by_user_id | datetime / int nullable *(2D)* | Set on approve or return |
| review_comments | text nullable *(2D)* | Coordinator's comments; mandatory when returning |
| reopened_at / reopened_reason | datetime / text nullable *(2D)* | Admin-only reopen of an approved evaluation |

## evaluation_criteria
| Column | Type | Notes |
|--------|------|-------|
| evaluation_id | FK evaluations.id | |
| area | str(30) | `conocimientos`/`desempeno`/`actitudinal` |
| order_index | int | 0..4 |
| description | text | Official criterion text |
| score | int nullable | 0–4 scale |

## activity_definitions *(Batch 2C)*
| Column | Type | Notes |
|--------|------|-------|
| rotation_type_id | FK nullable | `NULL` = shared across every core rotation |
| code | str(40) unique index | e.g. `MED-PROC-05`; app-enforced uniqueness (see D-022) |
| name | str(240) | Activity/procedure |
| category | str(30) | `hospitalization`/`emergency`/`community`/`academic`/`clinical_topic`/`procedure` |
| description | text | |
| target_type | str(20) | `fixed`/`no_fixed_target`/`completion_only` |
| target_count | int nullable | **Only set for `fixed`; NULL for NA — never 0** |
| unit_label | str(40) nullable | e.g. "veces" |
| requires_tutor_verification | bool | |
| evidence_policy | str(30) | `none`/`anonymous_reference`/`optional_attachment` |
| supervision_required | bool | |
| source_document / source_year / source_section | str/int/str nullable | Traceability to the official document |
| is_provisional | bool | True = 2024 source pending a 2026 update |
| display_order | int | |
| is_active | bool | Deactivate instead of delete when student records exist |

## student_activities *(Batch 2C)*
| Column | Type | Notes |
|--------|------|-------|
| student_id | FK students.id | |
| definition_id | FK activity_definitions.id | |
| assignment_id | FK nullable | |
| performed_count | int | Quantity performed (completion-only activities always 1) |
| logged_on | date | |
| verification_status | str(20) | `draft`/`pending`/`verified`/`rejected`/`cancelled` |
| evidence_reference | str(255) nullable | Anonymous reference only — never a patient identifier |
| notes | text | Validated against `privacy_validator.py` before save |
| submitted_at | datetime nullable | |
| created_by_user_id | FK users.id nullable | |

## activity_reviews *(Batch 2C, append-only)*
| Column | Type | Notes |
|--------|------|-------|
| student_activity_id | FK student_activities.id | |
| action | str(20) | `verified`/`rejected`/`reopened`/`corrected` |
| reviewer_user_id | FK users.id nullable | |
| comment | text nullable | Mandatory for `rejected` |
| created_at | datetime | Never updated — one row per review event |

## alerts *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| category | str(60) | Maps to rule codes |
| severity | str(20) | `info`/`warning`/`critical` |
| status | str(20) | `open`/`acknowledged`/`resolved`/`dismissed` |
| title | str(200) | |
| message | text | |
| source | str(40) | `rule_engine`/`agent`/`manual` |
| related_entity_type / related_entity_id | str/int | Back-reference |
| requires_human_action | bool | Always true for rule alerts |

## document_records *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| code | str(40) unique | e.g. DOC-2026-0001 |
| title | str(200) | |
| doc_type | str(60) | Oficio, Informe, … |
| status | str(30) | draft→…→archived |
| origin / destination | str(120) | Communication route |
| sede_id / student_id | FK nullable | |
| summary | text | |
| file_path | str(255) nullable | Reserved for future uploads |

## incidents *(soft-delete)*
| Column | Type | Notes |
|--------|------|-------|
| code | str(40) unique | e.g. INC-2026-0001 |
| title | str(200) | |
| description | text | |
| severity | str(20) | `low`/`medium`/`high` |
| status | str(20) | `open`/`in_review`/`resolved`/`closed` |
| sede_id / student_id | FK nullable | |
| reported_by | str(120) | |

## audit_logs
| Column | Type | Notes |
|--------|------|-------|
| actor_user_id | FK nullable | |
| actor_label | str(160) | e.g. email or `system` |
| action | str(80) | e.g. `login`, `create_student` |
| entity_type / entity_id | str/int | |
| detail | text | JSON payload |
| ip_address | str(64) | |

## agent_executions
| Column | Type | Notes |
|--------|------|-------|
| agent_name | str(80) | |
| task | str(160) | |
| status | str(30) | `success`/`no_findings`/`needs_review`/`error` |
| summary | text | |
| findings_json | text | JSON list of findings |
| recommended_actions_json | text | JSON list of actions |
| requires_human_approval | bool | |
| duration_ms | int | |
| triggered_by | str(80) | user email / `system` |

---

# Batch 2E — Documents, Incidents, Attachments, Reports

## document_records *(soft-delete; extended in Batch 2E)*
| Column | Type | Notes |
|--------|------|-------|
| code | str(40) unique | `DOC-YYYY-NNNN`, server-generated |
| seq_year / seq_number | int | Numbering provenance |
| title | str(200) | |
| doc_type | str(60) | See DOCUMENT_TYPES (13 codes) |
| status | str(30) | draft/submitted/under_review/approved/rejected/archived |
| priority | str(20) | low/normal/high/urgent |
| visibility | str(20) | normal/restricted/confidential |
| origin / destination | str(160) | Communication route participants |
| sede_id / student_id / assignment_id | FK nullable | Optional links |
| subject | str(300) | |
| summary / body / internal_notes | text | `internal_notes` hidden from students |
| created_by / submitted_by / reviewed_by / approved_by / rejected_by / archived_by / reopened_by `_user_id` | FK nullable | Lifecycle actors |
| submitted_at / reviewed_at / approved_at / rejected_at / archived_at / reopened_at | datetime | Lifecycle timestamps |
| rejection_reason / reopen_reason | text | Mandatory on reject / reopen |
| due_date | date | Drives the overdue-document rule |
| file_path | str(255) | Legacy Part 1 field (unused; real files → `attachments`) |

## incidents *(soft-delete; extended in Batch 2E)*
| Column | Type | Notes |
|--------|------|-------|
| code | str(40) unique | `INC-YYYY-NNNN`, server-generated |
| seq_year / seq_number | int | Numbering provenance |
| title | str(200) | |
| incident_type | str(60) | See INCIDENT_TYPES (13 codes) |
| description | text | |
| severity | str(20) | low/medium/high/critical |
| status | str(20) | open/under_review/action_required/resolved/closed/dismissed/reopened |
| visibility | str(20) | normal/restricted/confidential |
| sede_id / student_id / assignment_id | FK nullable | |
| reported_by | str(120) | Legacy free-text reporter |
| reported_by_user_id | FK nullable | Authoritative reporter |
| report_date / due_date | date | |
| responsible_user_id | FK nullable | Assigned responsible person |
| internal_notes | text | Hidden from students |
| resolution | text | Required to resolve/close |
| resolved_by / closed_by / dismissed_by / reopened_by `_user_id` | FK nullable | |
| resolved_at / closed_at / dismissed_at / reopened_at | datetime | |
| dismiss_reason / reopen_reason | text | Mandatory on dismiss / reopen |

## attachments *(soft-delete; NEW — polymorphic)*
| Column | Type | Notes |
|--------|------|-------|
| owner_type | str(20) | `document` \| `incident` |
| owner_id | int | Owning record id |
| original_filename | str(255) | Basename only (never trusted for storage) |
| stored_filename | str(255) unique | Server-generated `<uuid>.<ext>` |
| mime_type | str(120) | |
| size_bytes | int | |
| uploaded_by_user_id / deleted_by_user_id | FK nullable | |

## status_history *(NEW — polymorphic, append-only)*
| Column | Type | Notes |
|--------|------|-------|
| owner_type / owner_id | str(20)/int | `document` \| `incident` |
| from_status / to_status | str(30) | |
| action | str(60) | e.g. submit/approve/resolve/dismiss |
| actor_user_id / actor_label | FK/str(160) | |
| note | text | Non-confidential reason/note |

## document_templates *(soft-delete; NEW)*
| Column | Type | Notes |
|--------|------|-------|
| code | str(60) unique | e.g. `tpl_resignation` |
| name | str(160) | |
| doc_type | str(60) | |
| subject_template | str(300) | |
| body_template | text | Seeds an editable draft (never auto-approved) |
| description | str(300) | |

## document_sequences *(NEW)*
| Column | Type | Notes |
|--------|------|-------|
| kind | str(20) | `document` \| `incident` |
| year | int | UNIQUE(kind, year) |
| last_value | int | Atomically incremented for numbering |

---

# Batch 2F — Bulk import & academic grades

## import_batches *(soft-delete; NEW)*
| Column | Type | Notes |
|--------|------|-------|
| code | str(40) unique | `IMP-YYYY-NNNN` |
| profile | str(40) | students/sedes/tutors/coordinators/rotations/grade_components |
| original_filename | str(255) | |
| stored_filename | str(255) | temp file (outside static); nulled after import |
| sheet_name | str(120) | |
| mode | str(30) | create_only/update_existing/skip_duplicates/valid_only/all_or_nothing |
| status | str(20) | uploaded/mapped/validated/confirmed/partial/cancelled/failed |
| mapping_json | text | {target_field: source_header} (+ `_scheme_id` for grades) |
| content_hash | str(64) | SHA-256 of file+sheet+mapping (stale-confirm guard) |
| total_rows / valid_rows / warning_rows / error_rows | int | validation counts |
| created_count / updated_count / skipped_count / failed_count | int | import outcome |
| sede_scope_id | FK nullable | own-sede coordinator scope |
| created_by / confirmed_by `_user_id` | FK nullable | |
| confirmed_at | datetime | |

## import_rows *(NEW)*
| Column | Type | Notes |
|--------|------|-------|
| batch_id | FK import_batches | |
| row_number | int | 1-based source row |
| source_sheet | str(120) | |
| raw_json / normalized_json | text | mapped display + cleaned values |
| messages_json | text | [{level, field, message}] |
| status | str(20) | pending/valid/warning/error/created/updated/skipped/failed |
| action | str(20) | create/update/skip |
| target_entity_type / target_entity_id | str/int | set after import |

## grade_schemes *(soft-delete; NEW)*
| Column | Type | Notes |
|--------|------|-------|
| code | str(60) unique | |
| name | str(160) | |
| rotation_type_id / period_id | FK nullable | |
| version | int | |
| status | str(20) | draft/active/archived |
| effective_from / effective_to | date | |
| weights_confirmed | bool | gates final-grade calculation |
| notes | text | |

## grade_component_definitions *(NEW)*
| Column | Type | Notes |
|--------|------|-------|
| scheme_id | FK grade_schemes | |
| name | str(160) | |
| category | str(40) | GRADE_CATEGORIES |
| weight_percent | float **nullable** | null until confirmed |
| is_required | bool | |
| max_score | float | default 20 |
| source | str(120) | source sheet/label |
| display_order | int | |

## student_grade_components *(soft-delete; NEW)*
| Column | Type | Notes |
|--------|------|-------|
| student_id / scheme_id / component_id | FK | |
| score | float **nullable** | NULL = not registered (distinct from 0) |
| status | str(20) | draft/imported/approved |
| source_type | str(20) | manual/import |
| source_batch_id | FK nullable | import provenance |
| source_sheet / source_row / source_col | str/int | preserved from the file |
| entered_by / approved_by `_user_id` | FK nullable | |
| approved_at | datetime | |

## grade_component_history *(NEW, append-only)*
| Column | Type | Notes |
|--------|------|-------|
| student_grade_component_id | FK | |
| old_score / new_score | float | |
| old_status / new_status | str(20) | |
| action | str(40) | import_created/import_updated/approve/manual_update |
| actor_user_id / actor_label | FK/str | |
| batch_id | FK nullable | |
| note | text | |
