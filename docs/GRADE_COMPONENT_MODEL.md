# GRADE COMPONENT MODEL — UPeU Internado 360 (Batch 2F foundation)

The configurable grade architecture reserved for the future **Academic Grade
Agent**. The system stores components faithfully but **never computes a final
grade until the official weights are confirmed**.

## Tables (`app/models/grades.py`)

### GradeScheme
A versioned grading scheme for a course/rotation + academic period.
`code, name, rotation_type_id?, period_id?, version, status (draft|active|archived),
effective_from?, effective_to?, weights_confirmed, notes`.
`weights_confirmed` gates any final-grade calculation.

### GradeComponentDefinition
One component (column) of a scheme.
`scheme_id, name, category, weight_percent (NULLABLE), is_required, max_score (default 20),
source, display_order`.
`weight_percent` **may remain null** until the client confirms the formula.

Recognised categories: Actitudinal, Desempeño, Conocimiento, Ética y
profesionalismo, Participación/asistencia, Portafolio, Simulacros ENAM, Examen
oral, Examen escrito/final, Evaluación docente, Otro.

### StudentGradeComponent
A single student's score for one scheme component.
`student_id, scheme_id, component_id, score (NULLABLE), status (draft|imported|approved),
source_type (manual|import), source_batch_id?, source_sheet?, source_row?, source_col?,
entered_by_user_id?, approved_by_user_id?, approved_at?`.
`score = NULL` means **not registered** and is always distinct from a real `0`.

### GradeComponentHistory
Append-only history of every change: `old_score, new_score, old_status, new_status,
action, actor, batch_id?, note`. Actions: `import_created`, `import_updated`,
`approve`, `manual_update`.

## Final-grade policy

`GradeService.final_grade_note(scheme)` returns
**"Fórmula pendiente de confirmación"** whenever `weights_confirmed` is false or any
required component has a null weight. In that state no final grade is computed and
the UI shows the pending note. **The agent must never invent weights.**

## Source sheets (reference)

The official workbook groups grades under sheets such as *QX 2026*, *INT. CIRUGÍA*,
*INT. MEDICINA*, *INT. PEDIATRÍA*, *INT. GO*, *REV. MED. QUIR III/IV*. The importer
preserves the source sheet, row and column on every `StudentGradeComponent`.
