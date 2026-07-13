"""Official activity/procedure catalog — single source of truth.

Extracted from the four "LISTA DE ACTIVIDADES DE INTERNADO" reference
documents (see docs/ACTIVITY_CATALOG_SOURCE_MAP.md for the full source-to-row
mapping and the source-priority rule: Cirugía 2026 is current; Medicina,
Pediatría and Gineco-Obstetricia 2024 are provisional until updated versions
are supplied).

Both ``app/seed.py`` (initial load) and the catalog import-preview page
(admin-triggered, idempotent re-sync) read this module, so there is exactly
one place the official catalog is defined.

"NA" in the source documents means *no fixed numerical minimum — perform the
largest reasonable number possible*; it is represented here as
``target_type="no_fixed_target"`` with ``target_count=None`` and must never be
treated as a target of zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FIXED = "fixed"
NO_FIXED = "no_fixed_target"
COMPLETION_ONLY = "completion_only"

CIRUGIA_DOC = "LISTA DE ACTIVIDADES DE INTERNADO EN CIRUGIA 2026.docx"
MEDICINA_DOC = "LISTA DE ACTIVIDADES DE INTERNADO EN MEDICINA 2024 (1).docx"
PEDIATRIA_DOC = "LISTA DE ACTIVIDADES DE INTERNADO EN PEDIATRIA 2024 (2).docx"
GINECO_DOC = "LISTA DE ACTIVIDADES DE INTERNADO EN GINECO OBSTETRICIA 2024 (1).docx"


@dataclass
class CatalogItem:
    code: str
    name: str
    category: str
    rotation_code: str | None  # RotationType.code, or None for shared items
    target_type: str
    target_count: int | None = None
    unit_label: str | None = None
    requires_tutor_verification: bool = True
    evidence_policy: str = "anonymous_reference"
    supervision_required: bool = False
    source_document: str | None = None
    source_year: int | None = None
    source_section: str | None = None
    is_provisional: bool = False
    display_order: int = 0
    description: str | None = None


# --- Shared narrative categories (identical text across all four documents; -
# rotation_code=None → applies to every core rotation, stored once). ---------
_SHARED: list[CatalogItem] = [
    CatalogItem(
        code="SHARED-HOSP", name="Actividades de Hospitalización",
        category="hospitalization", rotation_code=None, target_type=COMPLETION_ONLY,
        requires_tutor_verification=True, evidence_policy="none",
        supervision_required=True, source_section="A. Hospitalización",
        display_order=1,
        description="Historia clínica, visita diaria, diagnósticos, exámenes "
                     "auxiliares, medidas terapéuticas, evolución, epicrisis y "
                     "procedimientos bajo supervisión del médico asistente/docente.",
    ),
    CatalogItem(
        code="SHARED-EMER", name="Actividades de Emergencia",
        category="emergency", rotation_code=None, target_type=COMPLETION_ONLY,
        requires_tutor_verification=True, evidence_policy="none",
        supervision_required=True, source_section="B. Emergencia",
        display_order=2,
        description="Guardias, historia clínica de emergencia, hipótesis "
                     "diagnósticas, medidas terapéuticas y notas de evolución "
                     "bajo supervisión del tutor, residente o médico de guardia.",
    ),
    CatalogItem(
        code="SHARED-COMM", name="Participación Comunitaria",
        category="community", rotation_code=None, target_type=COMPLETION_ONLY,
        requires_tutor_verification=False, evidence_policy="none",
        source_section="C. Comunidad", display_order=3,
        description="Participación en programas de salud del niño, campañas "
                     "médicas y actividades de prevención y promoción de la salud.",
    ),
    CatalogItem(
        code="SHARED-ACAD", name="Actividades Académicas",
        category="academic", rotation_code=None, target_type=COMPLETION_ONLY,
        requires_tutor_verification=False, evidence_policy="none",
        source_section="D. Actividades académicas", display_order=4,
        description="Clases teóricas, presentación de casos clínicos, "
                     "reuniones clínico-radiológicas, revisiones bibliográficas "
                     "y exposición de temas programados.",
    ),
]

_TOPIC_SECTION = "Relación de Temas / Revisión de Casos Clínicos"
_PROC_SECTION = "Metas de Procedimientos"


def _topics(rotation_code: str, doc: str, year: int, provisional: bool,
           topics: list[str], start_order: int) -> list[CatalogItem]:
    items = []
    for i, name in enumerate(topics):
        items.append(CatalogItem(
            code=f"{rotation_code}-TOPIC-{i+1:02d}", name=name,
            category="clinical_topic", rotation_code=rotation_code,
            target_type=COMPLETION_ONLY, requires_tutor_verification=True,
            evidence_policy="none", source_document=doc, source_year=year,
            source_section=_TOPIC_SECTION, is_provisional=provisional,
            display_order=start_order + i,
        ))
    return items


def _procs(rotation_code: str, doc: str, year: int, provisional: bool,
          rows: list[tuple[str, int | None]], start_order: int,
          supervision: bool = True) -> list[CatalogItem]:
    items = []
    for i, (name, target) in enumerate(rows):
        items.append(CatalogItem(
            code=f"{rotation_code}-PROC-{i+1:02d}", name=name,
            category="procedure", rotation_code=rotation_code,
            target_type=(FIXED if target is not None else NO_FIXED),
            target_count=target, unit_label="veces" if target is not None else None,
            requires_tutor_verification=True, evidence_policy="anonymous_reference",
            supervision_required=supervision, source_document=doc, source_year=year,
            source_section=_PROC_SECTION, is_provisional=provisional,
            display_order=start_order + i,
        ))
    return items


_CIRUGIA_TOPICS = [
    "Revisión de Cuidados perioperatorios",
    "Revisión de Complicaciones trans y post-operatorias más frecuentes",
    "Revisión de Apendicitis aguda",
    "Revisión de Patología de las vías biliares y vesícula",
    "Revisión de Pancreatitis aguda y crónica",
    "Revisión de Hemorragia Digestiva",
    "Revisión de Diverticulitis",
    "Revisión de Hernias (inguinal, crural, umbilical; eventraciones)",
    "Revisión de perforaciones gastrointestinales",
    "Revisión de Obstrucción intestinal alta y baja",
    "Revisión de manejo racional de antibióticos",
    "Revisión de traumatismo abdominal abierto y cerrado",
    "Revisión de patología anorrectal (hemorroides, fisuras, fístulas, abscesos)",
    "Revisión de traumatismo encéfalocraneano y vertebro medular, hemorragia subaracnoidea",
    "Revisión del manejo del paciente con politraumatismo y del paciente quemado",
]
_CIRUGIA_PROCS = [
    ("Elabora historia clínica según el formato del establecimiento de salud", None),
    ("Identifica los problemas del paciente y los prioriza", None),
    ("Propone exámenes de apoyo diagnóstico y los sustenta, según guía clínica", None),
    ("Interpreta exámenes auxiliares de laboratorio e imágenes", None),
    ("Instalación de sonda nasogástrica", 4),
    ("Instalación de sonda vesical", 5),
    ("Instalación de sonda rectal", 2),
    ("Identifica el área quirúrgica y respeta las normas de bioseguridad", None),
    ("Realiza suturas", None),
    ("Realiza cuidado de ostomías", 10),
    ("Realiza curación de heridas", None),
    ("Realiza ayudantías en procedimientos de cirugía mayor", None),
    ("Asiste y apoya en cirugías laparoscópicas", None),
    ("Cura úlceras de presión", None),
    ("Inmovilización de fracturas por métodos no invasivos (vendajes, férulas, yesos)", 10),
    ("Realiza toracocentesis", 2),
    ("Realiza taponamiento nasal anterior", 4),
]

_MEDICINA_TOPICS = [
    "Neumonía", "Tuberculosis pulmonar", "Enfermedad Pulmonar Obstructiva crónica",
    "Falla respiratoria", "Hipertensión arterial", "Análisis de Gases Arteriales",
    "Cardiopatía isquémica", "Insuficiencia cardíaca", "Arresto cardiopulmonar",
    "Shock", "Anemias", "Hemorragia digestiva", "Enfermedad ulcero-péptica",
    "Hepatitis infecciosa", "Enfermedades de transmisión sexual: Sífilis, Gonorrea, SIDA",
]
_MEDICINA_PROCS = [
    ("Elabora historia clínica según el formato del establecimiento de salud", None),
    ("Identifica los problemas del paciente y los prioriza", None),
    ("Propone exámenes de apoyo diagnóstico y los sustenta, según guía clínica", None),
    ("Interpreta exámenes auxiliares de laboratorio e imágenes", None),
    ("Toma de muestra para análisis de laboratorio (Orina)", 10),
    ("Toma de muestra para análisis de laboratorio (AGA)", 10),
    ("Instalación de sonda vesical", 5),
    ("Toma de EKG e interpretación", 10),
    ("Realiza lavado gástrico", 3),
    ("Realiza drenaje pleural", 3),
    ("Realiza maniobras de resucitación cardio-respiratoria", 2),
    ("Maneja desfibrilador", 2),
    ("Realiza punción pleural", 2),
    ("Realiza paracentesis", 2),
    ("Realiza punción lumbar", 1),
]

_PEDIATRIA_TOPICS = [
    "Revisión de Atención inmediata al recién nacido normal",
    "Revisión de atención al recién nacido deprimido",
    "Revisión de Hipoglicemia neonatal",
    "Revisión de ictericia neonatal",
    "Revisión de infección neonatal (conjuntivitis, meningitis, neumonía, otras) y Sepsis neonatal",
    "Enfermedad de la membrana hialina",
    "Cardiopatías congénitas",
    "Revisión de malformaciones congénitas en el neonato",
    "Revisión de Asma bronquial",
    "Antibioticoterapia en pediatría",
    "Revisión de convulsiones",
    "Revisión de infecciones de la vía aérea superior",
    "Revisión de neumonía",
    "Revisión de diarrea aguda y crónica",
]
_PEDIATRIA_PROCS = [
    ("Elabora historia clínica pediátrica según el formato del establecimiento de salud", None),
    ("Identifica los problemas del paciente y los prioriza", None),
    ("Propone exámenes de apoyo diagnóstico y los sustenta, según guía clínica", None),
    ("Interpreta exámenes auxiliares de laboratorio e imágenes", None),
    ("Dosifica los principales fármacos de uso pediátrico", None),
    ("Realiza los procedimientos de atención al recién nacido normal", 20),
    ("Realiza los procedimientos de atención al recién nacido deprimido", 5),
    ("Realiza la exploración de caderas en un neonato y en lactante", None),
    ("Explora el canal inguinal en un lactante", None),
    ("Enseña la técnica de lactancia materna", None),
    ("Maneja quemaduras", None),
    ("Enseña el calendario de vacunas", None),
    ("Realiza el balance hídrico", None),
    ("Valora el crecimiento", None),
    ("Valora el neurodesarrollo", None),
    ("Realiza otoscopia", 5),
    ("Realiza rinoscopia", 5),
]

_GINECO_TOPICS = [
    "Fisiología del embarazo / Diagnóstico del embarazo y control prenatal",
    "Factores de riesgo durante el embarazo. Riesgo reproductivo",
    "Hiperémesis gravídica",
    "Hemorragia de la primera mitad del embarazo",
    "Hemorragia de la segunda mitad del embarazo",
    "Trabajo de parto",
    "Distocias",
    "Hipertensión inducida por el embarazo",
    "Retardo del crecimiento intrauterino",
    "Ruptura prematura de membranas",
    "Analgesia de parto",
    "Diabetes y gestación",
    "TBC y gestación",
    "HIV-SIDA y gestación",
    "Infecciones en obstetricia: ITU, corioamnionitis, infección puerperal",
]
_GINECO_PROCS = [
    ("Elabora historia clínica según el formato del establecimiento de salud", None),
    ("Identifica los problemas del paciente y los prioriza", None),
    ("Propone exámenes de apoyo diagnóstico y los sustenta, según guía clínica", None),
    ("Interpreta exámenes auxiliares de laboratorio e imágenes", None),
    ("Monitorea la labor de parto usando el partograma", 15),
    ("Atiende a la mujer en trabajo de parto", 15),
    ("Realiza la episiotomía, la episiorrafia y reparación de laceraciones", 15),
    ("Asiste y apoya en cesáreas", None),
    ("Asiste y apoya en legrados uterinos", None),
    ("Realiza la exploración de mamas", None),
    ("Toma de muestra cervical para citología", 15),
    ("Realiza debridación de abscesos: mastitis", 3),
    ("Realiza debridación de abscesos: bartolinitis", 3),
    ("Toma de muestras de secreciones vaginales", 5),
    ("Asiste a la paciente en ecografía ginecológica u obstétrica", None),
    ("Proporciona información sobre anticonceptivos", None),
    ("Coloca dispositivos intrauterinos", 5),
]


def build_catalog() -> list[CatalogItem]:
    """Return the complete official catalog (shared + all four rotations)."""
    items = list(_SHARED)
    items += _topics("CIR", CIRUGIA_DOC, 2026, False, _CIRUGIA_TOPICS, 10)
    items += _procs("CIR", CIRUGIA_DOC, 2026, False, _CIRUGIA_PROCS, 30)
    items += _topics("MED", MEDICINA_DOC, 2024, True, _MEDICINA_TOPICS, 10)
    items += _procs("MED", MEDICINA_DOC, 2024, True, _MEDICINA_PROCS, 30)
    items += _topics("PED", PEDIATRIA_DOC, 2024, True, _PEDIATRIA_TOPICS, 10)
    items += _procs("PED", PEDIATRIA_DOC, 2024, True, _PEDIATRIA_PROCS, 30)
    items += _topics("GO", GINECO_DOC, 2024, True, _GINECO_TOPICS, 10)
    items += _procs("GO", GINECO_DOC, 2024, True, _GINECO_PROCS, 30)
    return items
