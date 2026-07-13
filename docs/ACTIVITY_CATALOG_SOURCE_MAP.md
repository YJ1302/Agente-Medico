# ACTIVITY CATALOG SOURCE MAP — UPeU Internado 360

Maps the official "LISTA DE ACTIVIDADES DE INTERNADO" reference documents to the
`activity_definitions` seed/catalog rows. This is the audit trail from source
document to database row required by Batch 2C.

## Source priority

| Rotation | Document used | Year | Status |
|---|---|---|---|
| Cirugía | LISTA DE ACTIVIDADES DE INTERNADO EN CIRUGIA 2026.docx | 2026 | **Current** |
| Medicina | LISTA DE ACTIVIDADES DE INTERNADO EN MEDICINA 2024 (1).docx | 2024 | Provisional |
| Pediatría | LISTA DE ACTIVIDADES DE INTERNADO EN PEDIATRIA 2024 (2).docx | 2024 | Provisional |
| Gineco-Obstetricia | LISTA DE ACTIVIDADES DE INTERNADO EN GINECO OBSTETRICIA 2024 (1).docx | 2024 | Provisional |

`LISTA DE ACTIVIDADES DE INTERNADO EN CIRUGIA 2024 (2).docx` is a superseded
predecessor of the 2026 Cirugía document and was **not** used, per the source
priority rule (2026 wins over 2024 when both exist for the same rotation). If a
future 2026 revision is supplied for Medicina, Pediatría or Gineco-Obstetricia,
it must replace the corresponding 2024 provisional rows (new `source_year`,
`is_provisional=False`), without deleting the historical provisional
definitions that already have student records attached (soft-deactivate
instead — see §2 rule "no hard delete").

**"NA" interpretation (binding on the whole system):** where the source table
says "NA" for a procedure target, it means *"No aplica: esto implica que tiene
que realizar el mayor número posible"* — no fixed numeric minimum, perform as
many as reasonably possible. This is stored as `target_type=no_fixed_target`,
`target_count=NULL`. It is **never** interpreted or displayed as a target of 0
or as 0%.

## Common structure (identical across all 4 documents)

Every document follows the same four-section template plus a topics table and
a procedures/goals table:

| Section | Category stored | Numeric targets? | Notes |
|---|---|---|---|
| A. Hospitalización | `hospitalization` | No (narrative duties, not counted procedures) | Item 14 explicitly requires tutor/attending supervision |
| B. Emergencia | `emergency` | No | Intro sentence requires tutor/resident/on-call supervision |
| C. Comunidad | `community` | No | Free-text participation, no numbered list |
| D. Actividades académicas | `academic` | No | Institutional academic activities (classes, case presentations, etc.) |
| Temas a Revisar (clinical topics) | `clinical_topic` | No — topics are reviewed/discussed, not counted | 15 topics + 1 "EXAMEN" row per rotation |
| Metas de Procedimientos (goals) | `procedure` | **Yes, per row** — fixed integer or `NA` | The only rows stored as numeric `StudentActivity` targets |

Because sections A–D and the "Revisión de Casos Clínicos" closing checklist are
**word-for-word identical in all four documents** (a shared template, not
rotation-specific content), Batch 2C stores them as **four reusable common
definitions** (`category=hospitalization|emergency|community|academic`,
`target_type=completion_only`, `rotation_type_id=NULL` → applicable to every
core rotation) rather than duplicating the same text four times per rotation.
The 15 clinical topics and the procedure/goal rows **are** rotation-specific and
are stored once per rotation with `rotation_type_id` set.

The Pediatría topics table contains one verbatim duplicate row ("Revisión de
infección neonatal…") in the source; only one catalog row is created for it
(duplicate not seeded twice). The Gineco-Obstetricia procedures table header
literally reads "…PARA EL INTERNO DE CIRUGÍA" in the source .docx — a
copy-paste artifact of the original document, not an extraction error; it does
not affect the stored rotation link (rows are correctly attached to
Gineco-Obstetricia via `rotation_type_id`).

## Cirugía (2026) — Metas de Procedimientos

| Activity | target_type | target_count | requires_tutor_verification |
|---|---|---|---|
| Instalación de sonda nasogástrica | fixed | 4 | yes |
| Instalación de sonda vesical | fixed | 5 | yes |
| Instalación de sonda rectal | fixed | 2 | yes |
| Realiza cuidado de ostomías | fixed | 10 | yes |
| Inmovilización de fracturas por métodos no invasivos | fixed | 10 | yes |
| Realiza toracocentesis | fixed | 2 | yes |
| Realiza taponamiento nasal anterior | fixed | 4 | yes |
| Elabora historia clínica según formato del establecimiento | no_fixed_target | — | yes |
| Identifica los problemas del paciente y los prioriza | no_fixed_target | — | yes |
| Propone exámenes de apoyo diagnóstico según guía clínica | no_fixed_target | — | yes |
| Interpreta exámenes auxiliares de laboratorio e imágenes | no_fixed_target | — | yes |
| Identifica el área quirúrgica y respeta normas de bioseguridad | no_fixed_target | — | yes |
| Realiza suturas | no_fixed_target | — | yes |
| Realiza curación de heridas | no_fixed_target | — | yes |
| Realiza ayudantías en procedimientos de cirugía mayor | no_fixed_target | — | yes |
| Asiste y apoya en cirugías laparoscópicas | no_fixed_target | — | yes |
| Cura úlceras de presión | no_fixed_target | — | yes |

## Medicina (2024, provisional) — Metas de Procedimientos

| Activity | target_type | target_count |
|---|---|---|
| Toma de muestra para análisis de laboratorio (Orina) | fixed | 10 |
| Toma de muestra para análisis de laboratorio (AGA) | fixed | 10 |
| Instalación de sonda vesical | fixed | 5 |
| Toma de EKG e interpretación | fixed | 10 |
| Realiza lavado gástrico | fixed | 3 |
| Realiza drenaje pleural | fixed | 3 |
| Realiza maniobras de resucitación cardio-respiratoria | fixed | 2 |
| Maneja desfibrilador | fixed | 2 |
| Realiza punción pleural | fixed | 2 |
| Realiza paracentesis | fixed | 2 |
| Realiza punción lumbar | fixed | 1 |
| Elabora historia clínica según formato del establecimiento | no_fixed_target | — |
| Identifica los problemas del paciente y los prioriza | no_fixed_target | — |
| Propone exámenes de apoyo diagnóstico según guía clínica | no_fixed_target | — |
| Interpreta exámenes auxiliares de laboratorio e imágenes | no_fixed_target | — |

## Pediatría (2024, provisional) — Metas de Procedimientos

| Activity | target_type | target_count |
|---|---|---|
| Realiza los procedimientos de atención al recién nacido normal | fixed | 20 |
| Realiza los procedimientos de atención al recién nacido deprimido | fixed | 5 |
| Realiza otoscopia | fixed | 5 |
| Realiza rinoscopia | fixed | 5 |
| Elabora historia clínica pediátrica según formato del establecimiento | no_fixed_target | — |
| Identifica los problemas del paciente y los prioriza | no_fixed_target | — |
| Propone exámenes de apoyo diagnóstico según guía clínica | no_fixed_target | — |
| Interpreta exámenes auxiliares de laboratorio e imágenes | no_fixed_target | — |
| Dosifica los principales fármacos de uso pediátrico | no_fixed_target | — |
| Realiza la exploración de caderas en un neonato y en lactante | no_fixed_target | — |
| Explora el canal inguinal en un lactante | no_fixed_target | — |
| Enseña la técnica de lactancia materna | no_fixed_target | — |
| Maneja quemaduras | no_fixed_target | — |
| Enseña el calendario de vacunas | no_fixed_target | — |
| Realiza el balance hídrico | no_fixed_target | — |
| Valora el crecimiento | no_fixed_target | — |
| Valora el neurodesarrollo | no_fixed_target | — |

## Gineco-Obstetricia (2024, provisional) — Metas de Procedimientos

| Activity | target_type | target_count |
|---|---|---|
| Monitorea la labor de parto usando el partograma | fixed | 15 |
| Atiende a la mujer en trabajo de parto | fixed | 15 |
| Realiza episiotomía, episiorrafia y reparación de laceraciones | fixed | 15 |
| Toma de muestra cervical para citología | fixed | 15 |
| Realiza debridación de abscesos: mastitis | fixed | 3 |
| Realiza debridación de abscesos: bartolinitis | fixed | 3 |
| Toma de muestras de secreciones vaginales | fixed | 5 |
| Coloca dispositivos intrauterinos | fixed | 5 |
| Elabora historia clínica según formato del establecimiento | no_fixed_target | — |
| Identifica los problemas del paciente y los prioriza | no_fixed_target | — |
| Propone exámenes de apoyo diagnóstico según guía clínica | no_fixed_target | — |
| Interpreta exámenes auxiliares de laboratorio e imágenes | no_fixed_target | — |
| Asiste y apoya en cesáreas | no_fixed_target | — |
| Asiste y apoya en legrados uterinos | no_fixed_target | — |
| Realiza la exploración de mamas | no_fixed_target | — |
| Asiste a la paciente en ecografía ginecológica u obstétrica | no_fixed_target | — |
| Proporciona información sobre anticonceptivos | no_fixed_target | — |

## Clinical topics (`clinical_topic`, `target_type=completion_only`)

The 15 topics per rotation (Cirugía, Medicina, Pediatría, Gineco-Obstetricia)
are stored as `completion_only` catalog rows (reviewed/discussed, not counted
by quantity) — see the full per-rotation lists extracted from each document.
The final "EXAMEN" row of each topics table is **not** stored as a trackable
activity (it is a rotation-end exam event, out of scope for Batch 2C activity
tracking).

## Evidence and supervision

No document specifies a file/photo evidence requirement for any activity — per
the Batch 2C privacy rules, evidence is always `anonymous_reference` (free-text
reference/description, never an identifiable file) for procedure rows, and
`none` for narrative/topic rows. All procedure and hospitalization/emergency
items require tutor verification (`requires_tutor_verification=True`);
`supervision_required=True` is set specifically on items whose source text
explicitly names supervision (Hospitalización #14, all Emergencia items, and
every procedure row, consistent with "bajo el asesoramiento y supervisión del
Médico Asistente y/o Docente").

## Source metadata stored per definition

Every `ActivityDefinition` row stores `source_document`, `source_year`,
`source_section` (e.g. "Metas de Procedimientos", "Hospitalización"), and
`is_provisional`. No page numbers exist in any source document (none of the
four .docx files contain page/section numbering beyond the lettered
A–D sections and the two named tables), so `source_section` uses the visible
section heading text instead of a page number.
