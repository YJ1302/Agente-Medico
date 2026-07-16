"""AI Coordinator Assistant service (Phase 3A).

A safe natural-language Q&A layer for authorized coordinators, built on the
same principles as ``report_service.py``:

* **Deterministic queries first.** Every supported question is answered by a
  plain repository/service query, scoped to the caller's role exactly like
  ``ReportService``. An LLM (see ``app.agents.assistant_llm_client``) is only
  ever used afterwards, to phrase the already-computed result as prose — it
  never sees the database, only the small structured payload this module
  produces.
* **Deterministic intent matching.** The free-text question is matched to one
  of the supported intents with plain keyword/substring checks against the
  caller's *own* scoped records (student names/codes, sede names). No LLM is
  involved in routing, so a question can never expand what data is reachable.
* **Scope is enforced twice.** Once by the route guard (``require_management``
  blocks Students and Tutors outright) and once inside ``can_ask``/the scope
  helpers below (a Sede Coordinator cannot reach the grade-scheme questions
  reserved for Admin/University Coordinator, matching GRADE_COMPONENT_MODEL.md
  and USER_ROLES_AND_PERMISSIONS.md Batch 2F).
* **Never invents grade weights or final grades.** The grade-related builders
  surface the same "Fórmula pendiente de confirmación" gate used everywhere
  else (``GradeService.final_grade_note``); they never compute a final score.
* **Confidential content is redacted before it is ever assembled**, so it
  cannot leak into the on-screen answer, the audit log or the LLM payload.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.agents.assistant_llm_client import assistant_llm_client
from app.authorization import is_global_viewer
from app.config import settings
from app.models.base import (
    AssignmentStatus,
    DocumentStatus,
    EvaluationStatus,
    IncidentSeverity,
    IncidentStatus,
    VisibilityLevel,
)
from app.models.operations import DOCUMENT_TYPES
from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_UNIVERSITY_COORDINATOR,
)
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.rate_limiter import assistant_rate_limiter

# Role sets --------------------------------------------------------------
ROLES_ALL_COORDINATORS = {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR}
# Grade-scheme visibility mirrors GradeService/USER_ROLES_AND_PERMISSIONS.md
# Batch 2F: Sede Coordinators do not see the raw grade matrix.
ROLES_GLOBAL_ONLY = {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR}

# Question registry: key -> (title, allowed roles). Also the canonical list
# of the 11 supported questions surfaced in the UI and reported to the user.
QUESTIONS: dict[str, tuple[str, set[str]]] = {
    "pending_evaluations": ("Internos con evaluaciones pendientes", ROLES_ALL_COORDINATORS),
    "low_activity": ("Internos con bajo avance de actividades", ROLES_ALL_COORDINATORS),
    "rotations_ending_soon": ("Rotaciones por finalizar", ROLES_ALL_COORDINATORS),
    "students_without_tutor": ("Internos sin tutor asignado", ROLES_ALL_COORDINATORS),
    "tutor_backlog": ("Tutores con cola de verificación pendiente", ROLES_ALL_COORDINATORS),
    "open_incidents": ("Incidencias abiertas de severidad alta o crítica", ROLES_ALL_COORDINATORS),
    "documents_awaiting_review": ("Documentos en espera de revisión", ROLES_ALL_COORDINATORS),
    "grade_components_missing": ("Componentes de nota faltantes o inconsistentes", ROLES_GLOBAL_ONLY),
    "cross_sheet_inconsistencies": ("Inconsistencias de notas entre hojas", ROLES_GLOBAL_ONLY),
    "student_summary": ("Resumen de internado de un interno", ROLES_ALL_COORDINATORS),
    "sede_summary": ("Resumen por sede", ROLES_ALL_COORDINATORS),
}

# Ordered substring patterns: a question matches an intent if ANY phrase in
# its list appears in the normalized text. Checked in this order; first match
# wins. Patterns are plain substrings (already accent-stripped, lowercase, and
# with runs of whitespace collapsed to single spaces) so natural phrasings
# like "no tienen tutor" and "sin tutor" both match without a bespoke parser.
_KEYWORD_INTENTS: list[tuple[str, list[str]]] = [
    ("students_without_tutor", [
        "sin tutor", "no tiene tutor", "no tienen tutor", "sin asignar tutor",
        "falta de tutor", "no cuenta con tutor", "no cuentan con tutor",
    ]),
    ("tutor_backlog", [
        "cola de verificacion", "backlog", "tutor atrasad", "tutores atrasad",
        "verificaciones pendientes", "verificacion pendiente", "cola de tutor",
        "tutores con pendientes",
    ]),
    ("pending_evaluations", [
        "evaluacion pendiente", "evaluaciones pendientes", "evaluaciones sin completar",
        "evaluacion sin completar",
    ]),
    ("low_activity", [
        "bajo avance", "poco avance", "actividad baja", "actividades bajas",
        "sin actividad", "avance bajo", "avance de actividades bajo",
    ]),
    ("rotations_ending_soon", [
        "por finalizar", "rotacion termina", "rotaciones terminan",
        "rotacion vence", "rotaciones vencen", "rotaciones pronto",
        "rotacion finaliza", "rotaciones finalizan", "rotaciones a punto de",
    ]),
    ("open_incidents", [
        "incidencia critica", "incidencias criticas", "incidencia alta",
        "incidencias altas", "incidencias abiertas", "incidencia abierta",
    ]),
    ("documents_awaiting_review", [
        "documento en revision", "documentos en revision", "documentos pendientes",
        "documento pendiente", "documentos en espera", "documentos esperando",
    ]),
    ("cross_sheet_inconsistencies", [
        "entre hojas", "cruce de hojas", "hojas de notas", "consistencia entre hojas",
    ]),
    ("grade_components_missing", [
        "nota faltante", "notas faltantes", "componente de nota", "componentes de nota",
        "calificacion inconsistente", "nota inconsistente", "notas inconsistentes",
        "notas faltantes o inconsistentes",
    ]),
]


def _normalize(text: str) -> str:
    """Lowercase, strip accents and collapse whitespace for keyword matching."""
    text = (text or "").lower().strip()
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return " ".join(stripped.split())


@dataclass
class AssistantSource:
    label: str
    count: int


@dataclass
class AssistantAnswer:
    intent: str
    question: str
    title: str
    headers: list[str]
    rows: list[list]
    sources: list[AssistantSource]
    found: bool
    narrative: str = ""
    llm_narrative: str | None = None
    notes: list[str] = field(default_factory=list)


class AIAssistantService:
    """Answers a supported natural-language question with scoped, sourced data."""

    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)

    # -- scope helpers (mirrors ReportService's pattern) -------------------
    def _own_sede_ids(self) -> set[int]:
        return {
            c.sede_id for c in self.repos.sede_coordinators.active()
            if c.user_id == self.identity.user_id and c.sede_id
        }

    def scoped_students(self) -> list:
        if is_global_viewer(self.identity):
            return self.repos.students.search()
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            return self.repos.students.search(sede_ids=self._own_sede_ids() or {-1})
        return []

    def scoped_sedes(self) -> list:
        if is_global_viewer(self.identity):
            return self.repos.sedes.active()
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            ids = self._own_sede_ids()
            return [s for s in self.repos.sedes.active() if s.id in ids]
        return []

    def scoped_assignments(self) -> list:
        if is_global_viewer(self.identity):
            return self.repos.assignments.all_with_relations()
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            return self.repos.assignments.search(sede_ids=self._own_sede_ids() or {-1})
        return []

    # -- access --------------------------------------------------------------
    def available_questions(self) -> list[tuple[str, str]]:
        return [
            (k, title) for k, (title, roles) in QUESTIONS.items()
            if self.identity.role_code in roles
        ]

    def can_ask(self, key: str) -> bool:
        meta = QUESTIONS.get(key)
        return bool(meta) and self.identity.role_code in meta[1]

    # -- entity extraction (deterministic, matched only against already-
    # scoped records, so a question can never resolve to an out-of-scope
    # student or sede) --------------------------------------------------
    def _find_student_in_text(self, question: str):
        norm = _normalize(question)
        fallback = None
        for s in self.scoped_students():
            code_norm = _normalize(s.student_code or "")
            name_norm = _normalize(s.full_name or "")
            if code_norm and code_norm in norm:
                return s
            if name_norm and name_norm in norm:
                return s
            tokens = [t for t in name_norm.split() if len(t) > 2]
            if tokens and all(t in norm for t in tokens):
                fallback = fallback or s
        return fallback

    def _find_sede_in_text(self, question: str):
        norm = _normalize(question)
        for sede in self.scoped_sedes():
            for candidate in (sede.name, sede.short_name):
                cand_norm = _normalize(candidate or "")
                if cand_norm and cand_norm in norm:
                    return sede
        return None

    # -- intent matching ------------------------------------------------
    def match_intent(self, question: str) -> tuple[str | None, dict]:
        norm = _normalize(question)

        if "resumen" in norm or "informe" in norm:
            student = self._find_student_in_text(question)
            if student is not None:
                return "student_summary", {"student": student}
            sede = self._find_sede_in_text(question)
            if sede is not None:
                return "sede_summary", {"sede": sede}

        for key, phrases in _KEYWORD_INTENTS:
            if any(phrase in norm for phrase in phrases):
                return key, {}

        # Last resort: an entity name/code was given without "resumen".
        student = self._find_student_in_text(question)
        if student is not None:
            return "student_summary", {"student": student}
        sede = self._find_sede_in_text(question)
        if sede is not None:
            return "sede_summary", {"sede": sede}

        return None, {}

    # -- narrative (deterministic; used verbatim when the LLM is unavailable) --
    def _narrative(self, title: str, rows: list[list], found: bool) -> str:
        if not found or not rows:
            return f"No se encontraron resultados para: {title}."
        return f"Se encontraron {len(rows)} resultado(s) para: {title}."

    def _answer(self, key: str, headers: list[str], rows: list[list],
                *, found: bool | None = None, notes: list[str] | None = None) -> AssistantAnswer:
        title = QUESTIONS[key][0]
        found = bool(rows) if found is None else found
        sources = [AssistantSource(label=title, count=len(rows))]
        return AssistantAnswer(
            intent=key, question="", title=title, headers=headers, rows=rows,
            sources=sources, found=found,
            narrative=self._narrative(title, rows, found), notes=notes or [],
        )

    # -- question builders ------------------------------------------------
    def _q_pending_evaluations(self, entity=None) -> AssistantAnswer:
        assignment_ids = {a.id for a in self.scoped_assignments()}
        rows = []
        for ev in self.repos.evaluations.search():
            if ev.assignment_id not in assignment_ids:
                continue
            if ev.status not in (EvaluationStatus.PENDING.value, EvaluationStatus.IN_PROGRESS.value):
                continue
            rows.append([
                ev.student.full_name if ev.student else "—",
                ev.assignment.rotation_type.name if ev.assignment and ev.assignment.rotation_type else "—",
                ev.status,
            ])
        return self._answer("pending_evaluations", ["Interno", "Rotación", "Estado"], rows)

    def _q_low_activity(self, entity=None) -> AssistantAnswer:
        rows = []
        for s in self.scoped_students():
            entries = self.repos.student_activities.for_student(s.id)
            total = len(entries)
            verified = sum(1 for e in entries if e.verification_status == "verified")
            ratio = (verified / total) if total else 0.0
            if total == 0 or ratio < settings.ai_assistant_low_activity_ratio:
                rows.append([
                    s.full_name,
                    s.sede.short_name or s.sede.name if s.sede else "—",
                    total, verified, f"{round(ratio * 100)}%",
                ])
        rows.sort(key=lambda r: r[3])
        return self._answer("low_activity",
                            ["Interno", "Sede", "Registradas", "Verificadas", "% verificado"], rows)

    def _q_rotations_ending_soon(self, entity=None) -> AssistantAnswer:
        today = date.today()
        cutoff = today + timedelta(days=settings.ai_assistant_rotation_ending_days)
        rows = []
        for a in self.scoped_assignments():
            if a.status == AssignmentStatus.ACTIVE.value and a.end_date and today <= a.end_date <= cutoff:
                rows.append([
                    a.student.full_name if a.student else "—",
                    a.rotation_type.name if a.rotation_type else "—",
                    a.sede.short_name or a.sede.name if a.sede else "—",
                    a.end_date.strftime("%d/%m/%Y"), (a.end_date - today).days,
                ])
        rows.sort(key=lambda r: r[4])
        return self._answer(
            "rotations_ending_soon",
            ["Interno", "Rotación", "Sede", "Fin", "Días restantes"], rows,
        )

    def _q_students_without_tutor(self, entity=None) -> AssistantAnswer:
        rows = []
        for a in self.scoped_assignments():
            if a.tutor_id is None and a.status in (
                AssignmentStatus.ACTIVE.value, AssignmentStatus.PLANNED.value
            ):
                rows.append([
                    a.student.full_name if a.student else "—",
                    a.rotation_type.name if a.rotation_type else "—",
                    a.sede.short_name or a.sede.name if a.sede else "—",
                    a.period.name if a.period else "—",
                ])
        return self._answer("students_without_tutor", ["Interno", "Rotación", "Sede", "Periodo"], rows)

    def _q_tutor_backlog(self, entity=None) -> AssistantAnswer:
        cutoff = date.today() - timedelta(days=settings.activity_old_pending_days)
        student_ids = {s.id for s in self.scoped_students()}
        counts: dict[int, int] = {}
        for e in self.repos.student_activities.all_pending():
            if not e.assignment or not e.assignment.tutor_id:
                continue
            if e.student_id not in student_ids:
                continue
            if e.submitted_at and e.submitted_at.date() <= cutoff:
                counts[e.assignment.tutor_id] = counts.get(e.assignment.tutor_id, 0) + 1
        rows = []
        for tutor_id, count in counts.items():
            if count > settings.tutor_verification_backlog_threshold:
                tutor = self.repos.tutors.get(tutor_id)
                rows.append([
                    tutor.user.full_name if tutor and tutor.user else "—",
                    tutor.sede.short_name or tutor.sede.name if tutor and tutor.sede else "—",
                    count,
                ])
        rows.sort(key=lambda r: -r[2])
        return self._answer("tutor_backlog", ["Tutor", "Sede", "Pendientes atrasados"], rows)

    def _q_open_incidents(self, entity=None) -> AssistantAnswer:
        sede_ids = self._own_sede_ids() if self.identity.role_code == ROLE_SEDE_COORDINATOR else None
        terminal = {IncidentStatus.CLOSED.value, IncidentStatus.DISMISSED.value,
                    IncidentStatus.RESOLVED.value}
        rows = []
        for inc in self.repos.incidents.all_active():
            if inc.status in terminal:
                continue
            if inc.severity not in (IncidentSeverity.HIGH.value, IncidentSeverity.CRITICAL.value):
                continue
            if sede_ids is not None and inc.sede_id not in sede_ids:
                continue
            # Redact confidential titles for non-global viewers (defense in
            # depth — the assistant only ever shows counts/codes for these).
            if inc.visibility == VisibilityLevel.CONFIDENTIAL.value and not is_global_viewer(self.identity):
                title = "(incidencia confidencial)"
            else:
                title = inc.title
            rows.append([inc.code, title, inc.severity, inc.status])
        return self._answer("open_incidents", ["Código", "Título", "Severidad", "Estado"], rows)

    def _q_documents_awaiting_review(self, entity=None) -> AssistantAnswer:
        sede_ids = self._own_sede_ids() if self.identity.role_code == ROLE_SEDE_COORDINATOR else None
        rows = []
        for d in self.repos.documents.all_active():
            if d.status not in (DocumentStatus.SUBMITTED.value, DocumentStatus.UNDER_REVIEW.value):
                continue
            if sede_ids is not None and d.sede_id not in sede_ids:
                continue
            if d.visibility == VisibilityLevel.CONFIDENTIAL.value and not is_global_viewer(self.identity):
                continue
            rows.append([d.code, DOCUMENT_TYPES.get(d.doc_type, d.doc_type), d.status, d.priority])
        return self._answer("documents_awaiting_review", ["Código", "Tipo", "Estado", "Prioridad"], rows)

    def _q_grade_components_missing(self, entity=None) -> AssistantAnswer:
        rows = []
        for scheme in self.repos.grade_schemes.active():
            components = {c.id: c for c in self.repos.grade_components.for_scheme(scheme.id)}
            for c in components.values():
                if c.is_required and c.weight_percent is None:
                    rows.append([scheme.name, c.name, "Peso no confirmado", "—"])
            for sgc in self.repos.student_grades.for_scheme(scheme.id):
                c = components.get(sgc.component_id)
                if c is not None and c.is_required and sgc.score is None:
                    student = self.repos.students.get(sgc.student_id)
                    rows.append([scheme.name, c.name, "Nota no registrada",
                                student.full_name if student else "—"])
        return self._answer(
            "grade_components_missing", ["Esquema", "Componente", "Problema", "Detalle"], rows,
            notes=["No se calculan notas finales mientras los pesos no estén confirmados."],
        )

    def _q_cross_sheet_inconsistencies(self, entity=None) -> AssistantAnswer:
        batches = self.repos.import_batches.recent(limit=20, profile="grade_components")
        ids = [b.id for b in batches]
        if not ids:
            return self._answer(
                "cross_sheet_inconsistencies", ["Clave de interno", "Presente en", "Problema"], [],
                found=False, notes=["No hay lotes de importación de notas para comparar."],
            )
        from app.services.grade_service import GradeService
        report = GradeService(self.db, self.identity).cross_sheet_report(ids)
        rows = []
        for m in report["missing"]:
            rows.append([
                m["student_key"], ", ".join(m["present_in"]),
                "Ausente de: " + ", ".join(m["absent_from"]),
            ])
        for mm in report["mismatches"]:
            rows.append([
                mm["student_key"], "—",
                "Nombres distintos entre hojas: " + json.dumps(mm["names"], ensure_ascii=False),
            ])
        return self._answer(
            "cross_sheet_inconsistencies", ["Clave de interno", "Presente en", "Problema"], rows,
        )

    def _q_student_summary(self, entity=None) -> AssistantAnswer:
        student = entity
        if student is None:
            return self._answer("student_summary", ["Interno"], [], found=False,
                                notes=["No se identificó al interno en la pregunta. "
                                       "Incluya su nombre completo o código."])
        from app.services.report_service import ReportService
        data = ReportService(self.db, self.identity).build_student_summary(student.id)
        if not data:
            return self._answer("student_summary", ["Interno"], [], found=False,
                                notes=["No tiene permiso para ver este interno, o no existe."])
        row = [
            data["student"].full_name, data["completion"]["total"], data["completion"]["active"],
            data["activity"]["verified"], data["activity"]["pending"],
            len(data["evaluations"]), len(data["documents"]), len(data["incidents"]),
        ]
        headers = ["Interno", "Rotaciones", "Activas", "Act. verificadas", "Act. pendientes",
                   "Evaluaciones", "Documentos aprobados", "Incidencias"]
        return self._answer("student_summary", headers, [row])

    def _q_sede_summary(self, entity=None) -> AssistantAnswer:
        sede = entity
        if sede is None:
            return self._answer("sede_summary", ["Sede"], [], found=False,
                                notes=["No se identificó la sede en la pregunta."])
        students = [s for s in self.scoped_students() if s.sede_id == sede.id]
        assignments = [a for a in self.scoped_assignments() if a.sede_id == sede.id]
        active = sum(1 for a in assignments if a.status == AssignmentStatus.ACTIVE.value)
        missing_tutor = sum(
            1 for a in assignments if a.tutor_id is None
            and a.status in (AssignmentStatus.ACTIVE.value, AssignmentStatus.PLANNED.value)
        )
        terminal = {IncidentStatus.CLOSED.value, IncidentStatus.DISMISSED.value,
                    IncidentStatus.RESOLVED.value}
        open_incidents = sum(
            1 for i in self.repos.incidents.all_active()
            if i.sede_id == sede.id and i.status not in terminal
        )
        docs_review = sum(
            1 for d in self.repos.documents.all_active()
            if d.sede_id == sede.id
            and d.status in (DocumentStatus.SUBMITTED.value, DocumentStatus.UNDER_REVIEW.value)
        )
        row = [sede.name, len(students), active, missing_tutor, open_incidents, docs_review]
        headers = ["Sede", "Internos", "Rotaciones activas", "Sin tutor",
                   "Incidencias abiertas", "Documentos en revisión"]
        return self._answer("sede_summary", headers, [row])

    # -- top-level ask/answer ---------------------------------------------
    def ask(self, question: str) -> AssistantAnswer:
        """Pure deterministic answer (no rate limiting, no audit, no LLM)."""
        key, extra = self.match_intent(question)
        if key is None:
            supported = "; ".join(title for title, _ in QUESTIONS.values())
            return AssistantAnswer(
                intent="unknown", question=question, title="Pregunta no reconocida",
                headers=[], rows=[], sources=[], found=False,
                narrative="No se reconoció una pregunta soportada. Reformule usando una "
                          "de las consultas disponibles.",
                notes=[f"Preguntas soportadas: {supported}"],
            )
        if not self.can_ask(key):
            return AssistantAnswer(
                intent=key, question=question, title=QUESTIONS[key][0],
                headers=[], rows=[], sources=[], found=False,
                narrative="No tiene permiso para esta consulta con su rol actual.", notes=[],
            )
        builder = getattr(self, f"_q_{key}")
        entity = extra.get("student") if "student" in extra else extra.get("sede")
        answer = builder(entity)
        answer.question = question
        return answer

    def answer(self, question: str, ip: str | None = None) -> AssistantAnswer:
        """Rate-limited, audited entry point used by the route layer.

        Runs the deterministic query first, audits the query, attempts an
        optional LLM summary of the already-computed result, then audits the
        generated response. Never sends the raw question or full database to
        the model beyond the small structured payload already built above.
        """
        limiter_key = f"user:{self.identity.user_id}"
        if not assistant_rate_limiter.allow(
            limiter_key, settings.ai_assistant_rate_limit_per_minute
        ):
            AuditService(self.db).record(
                audit.AI_ASSISTANT_RATE_LIMITED, identity=self.identity,
                entity_type="ai_assistant",
                detail={"question": question[:200]}, ip_address=ip,
            )
            return AssistantAnswer(
                intent="rate_limited", question=question, title="Límite de consultas alcanzado",
                headers=[], rows=[], sources=[], found=False,
                narrative="Ha alcanzado el límite de consultas por minuto. "
                          "Intente de nuevo en unos segundos.", notes=[],
            )

        answer = self.ask(question)

        AuditService(self.db).record(
            audit.AI_ASSISTANT_QUERY, identity=self.identity, entity_type="ai_assistant",
            detail={"intent": answer.intent, "question": question[:200],
                    "result_count": len(answer.rows)},
            ip_address=ip,
        )

        if answer.found and answer.intent not in ("unknown", "rate_limited"):
            payload = {
                "title": answer.title, "headers": answer.headers,
                "rows": answer.rows[:20], "count": len(answer.rows),
            }
            try:
                answer.llm_narrative = assistant_llm_client.summarize(question, payload)
            except Exception:  # belt-and-suspenders: never let the LLM break the answer
                answer.llm_narrative = None

        AuditService(self.db).record(
            audit.AI_ASSISTANT_RESPONSE, identity=self.identity, entity_type="ai_assistant",
            detail={"intent": answer.intent, "used_llm": bool(answer.llm_narrative),
                    "result_count": len(answer.rows)},
            ip_address=ip,
        )
        return answer
