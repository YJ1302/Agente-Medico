# GRADE IMPORT RULES — UPeU Internado 360 (Batch 2F)

Rules enforced by the grade-import profile (`GradeComponentProfile` in
`app/services/grade_service.py`).

## Value rules

- **Score range** is 0–max (default 0–20). A value outside the range is an **error**.
- **Blank cell → `NULL`** (not registered). A blank is never coerced to 0.
- **Zero stays zero** — `0` is a valid, distinct score and is preserved.
- A blank cell **never erases** an existing stored value on update.

## Detection

The importer flags, per row/component:

- **Missing student** — the code/DNI does not match any interno (error).
- **Duplicate student** — the same interno appears more than once in the sheet (warning).
- **Score outside range** (error).
- **Blank required component** (warning).
- **Overwrite of an approved value** — a differing value against an existing
  **approved** component (warning; only applied on a confirmed update).

## Approved-value protection

- An existing **approved** component is **never overwritten silently**.
- A confirmed update that changes an approved value records a
  `GradeComponentHistory` entry (`import_updated`), writes an
  `update_grade_component_from_import` audit entry, and drops the component status
  back to `imported` (it must be re-approved). Nothing about the change is silent.

## No final-grade calculation

- The system does **not** compute a final grade while weights are unconfirmed.
- The UI shows **"Fórmula pendiente de confirmación"** until
  `GradeScheme.weights_confirmed` is true and every required component has a weight.
- The future Academic Grade Agent must never invent weights.

## Traceability

- Every imported component records `source_type=import`, `source_batch_id`,
  `source_sheet`, `source_row`, `source_col`.
- Every create/update is written to `GradeComponentHistory` and audited
  (`import_grade_component`, `update_grade_component_from_import`).

## Cross-sheet consistency check

`GradeService.cross_sheet_report(batch_ids)` (route: `GET /grades/cross-sheet-check`,
Admin/University only) compares the student rosters of two or more confirmed
grade-import batches and reports, read-only:

- **Missing**: a student key present in one imported sheet but absent from
  another (e.g. listed in `INT. CIRUGÍA` but not in `QX 2026`).
- **Mismatches**: the same student key associated with different display names
  across sheets (a possible transcription error) — matching is always by
  `student_key` (código/DNI), never by name.

This report never mutates data; it is purely diagnostic.

## Real-workbook compatibility (BASE DE DATOS - NOTAS INTERNADO MÉDICO)

The client's official workbook has a two-row header: a merged **category band**
(Actitudinal / Desempeño / Conocimiento) on the row directly above the real
column headers, which live on row 3 (0-based index 2). `excel_reader.read_sheet`
detects the header row automatically and separately exposes the forward-filled
category band as `SheetPreview.category_headers` (one entry per column, aligned
with `headers`), so the scheme-authoring UI can suggest a component's category —
never a weight — from the sheet's own grouping. See `IMPORT_PROFILE_CATALOG.md`
§ "Real workbook mapping" for the exact sheet-name and category aliases.

## Known limitations

- Final weighting/formulas are intentionally deferred to the next batch (the
  Academic Grade Agent). `weights_confirmed` and per-component `weight_percent`
  remain configurable and may stay null indefinitely until confirmed by the client.
- The cross-sheet check compares rosters actually imported into the system (via
  confirmed batches); it does not re-open the original Excel files.
