# IMPORT PROFILE CATALOG — UPeU Internado 360 (Batch 2F)

Each profile declares columns (with header aliases for auto-mapping), a unique key
for duplicate detection, and reuses the existing service validation. Defined in
`app/services/import_profiles.py` (grade profile in `grade_service.py`).

## 1. Students (`students`)
- **Roles**: Admin, University, Sede Coordinator (own sede).
- **Required**: Código, Nombre completo. **Optional**: Documento, Correo, Teléfono,
  Ciclo, Institución (MINSA/EsSalud), Sede, Inicio, Término, Activo.
- **Unique key**: student code. Also unique: document id, email (when provided).
- **Validation** (reuses `StudentService._validate`): unique code/document/email,
  cycle ∈ {13,14}, known institution, known sede, end date after start date.

## 2. Sedes (`sedes`)
- **Roles**: Admin, University.
- **Required**: Nombre, Nombre corto, Institución, Tipo. **Optional**: Ciudad, Dirección.
- **Unique key**: name (also short name). **Validation**: `SedeService._validate`.

## 3. Sede Coordinators (`coordinators`)
- **Roles**: Admin, University.
- **Required**: Nombre completo, Correo, Sede. **Optional**: Teléfono, Especialidad.
- **Unique key**: email. Creates a login user (role `sede_coordinator`).
- **Validation**: `CoordinatorService._validate` (email uniqueness, active sede).

## 4. Tutors (`tutors`)
- **Roles**: Admin, University.
- **Required**: Nombre completo, Correo, Sede. **Optional**: Teléfono, Especialidad.
- **Unique key**: email. Creates a login user (role `tutor`).
- **Validation**: `TutorService._validate`.

## 5. Rotations (`rotations`)
- **Roles**: Admin, University, Sede Coordinator (own sede).
- **Required**: Código interno, Rotación, Sede, Periodo. **Optional**: Tutor (correo),
  Inicio, Término, Estado.
- **Unique key**: (student, rotation type, period) — a duplicate core rotation.
- **Validation**: reuses the **rotation conflict engine** (student overlap, duplicate
  core rotation, tutor–sede mismatch, institution mismatch, community rule, inactive
  records, date/period mismatch). Blocking non-overridable conflicts → errors;
  overridable conflicts → warnings.

## 6. Grade components (`grade_components`)
- **Roles**: Admin, University.
- **Requires a target grade scheme** chosen at upload. Maps: Interno (código/DNI),
  optionally Nombre del alumno (display/cross-sheet check only — matching is always
  by código/DNI), + one column per scheme component.
- See `GRADE_COMPONENT_MODEL.md` and `GRADE_IMPORT_RULES.md`.

## Column mapping

Auto-mapping matches headers against each field's aliases; the user can override
every mapping in the mapping step before validating.

## Real workbook mapping — BASE DE DATOS - NOTAS INTERNADO MÉDICO 2026

Verified against the client's official file (7 sheets, header on row 3 below a
merged category band on row 2, data from row 4, `Código`/`Nombre del alumno`
columns, blank vs `0` distinguished correctly). No changes to the reader or the
grade-import validation logic were required — the existing header-detection
heuristic, blank/zero handling and student-key resolution already read this
file correctly. Sheet-name → suggested rotation type (`grade_service.
SHEET_ROTATION_HINTS`, a hint only, never auto-applied):

| Sheet name | Rotation hint | Notes |
|---|---|---|
| `QX 2026` | — | ENAM simulacro average, not rotation-specific |
| `INT. CIRUGÍA` | `CIR` | |
| `INT. MEDICINA` | `MED` | |
| `INT. PEDIATRÍA` | `PED` | |
| `INT. GO` | `GO` | |
| `REV. MED. QUIR III` | — | Cross-specialty review |
| `REV. MED. QUIR IV` | — | Cross-specialty review |

Category-band label → internal `GRADE_CATEGORIES` code
(`grade_service.category_code_for_band`): `Actitudinal → actitudinal`,
`Desempeño → desempeno`, `Conocimiento → conocimiento`; any other/unrecognised
label maps to `otro`. These are UI *suggestions* for the person authoring a
`GradeComponentDefinition` — the category is never inferred automatically into
saved data, and no weight is ever suggested or invented.
