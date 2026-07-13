"""Deterministic business-rule engine.

The rule engine runs pure, explainable checks over current data — no AI, no
randomness. Each rule returns a list of ``AgentFinding`` objects. These are the
authoritative "automated detection" layer; agents may *recommend* actions on
top of findings, but a human always decides.

Part 1 ships (at least) three working demo rules required by the spec:
    1. Rotation ending within seven days.
    2. Rotation assignment without a designated tutor.
    3. Pending evaluation.
A fourth rule (incomplete student profile) is included to power the seeded
alert set.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

from app.agents.base_agent import AgentFinding
from app.models.operations import (
    ALERT_ACTIVITY_TARGET_AT_RISK,
    ALERT_INCOMPLETE_PROFILE,
    ALERT_INSTITUTION_MISMATCH,
    ALERT_MISSING_TUTOR,
    ALERT_OLD_PENDING_ACTIVITY,
    ALERT_OVERDUE_EVALUATION,
    ALERT_PENDING_EVALUATION,
    ALERT_REJECTED_ACTIVITY_CORRECTION,
    ALERT_RETURNED_EVALUATION,
    ALERT_ROTATION_COMPLETED_UNVERIFIED,
    ALERT_ROTATION_ENDING,
    ALERT_STUDENT_OVERLAP,
    ALERT_SUBMITTED_EVALUATION,
    ALERT_TUTOR_SEDE_MISMATCH,
    ALERT_TUTOR_VERIFICATION_BACKLOG,
)
from app.repositories.repositories import RepositoryBundle

# Number of days that defines an "ending soon" rotation.
ROTATION_ENDING_WINDOW_DAYS = 7


def rule_rotation_ending_soon(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Detect active rotations ending within the configured window."""
    today = today or date.today()
    cutoff = today + timedelta(days=ROTATION_ENDING_WINDOW_DAYS)
    findings: list[AgentFinding] = []
    for a in repos.assignments.ending_before(cutoff):
        if a.end_date and a.end_date >= today:
            days_left = (a.end_date - today).days
            findings.append(
                AgentFinding(
                    code=ALERT_ROTATION_ENDING,
                    title="Rotación por finalizar",
                    detail=(
                        f"{a.student.full_name} — {a.rotation_type.name} en "
                        f"{a.sede.short_name or a.sede.name} finaliza en "
                        f"{days_left} día(s) ({a.end_date:%d/%m/%Y})."
                    ),
                    severity="warning",
                    entity_type="rotation_assignment",
                    entity_id=a.id,
                )
            )
    return findings


def rule_missing_tutor(repos: RepositoryBundle, today: date | None = None) -> list[AgentFinding]:
    """Detect active/planned assignments that have no tutor designated."""
    findings: list[AgentFinding] = []
    for a in repos.assignments.missing_tutor():
        findings.append(
            AgentFinding(
                code=ALERT_MISSING_TUTOR,
                title="Rotación sin tutor asignado",
                detail=(
                    f"La rotación de {a.student.full_name} en "
                    f"{a.rotation_type.name} ({a.sede.short_name or a.sede.name}) "
                    "no tiene tutor designado."
                ),
                severity="critical",
                entity_type="rotation_assignment",
                entity_id=a.id,
            )
        )
    return findings


def rule_pending_evaluation(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Detect evaluations that remain pending / in progress."""
    findings: list[AgentFinding] = []
    for ev in repos.evaluations.pending():
        student_name = ev.student.full_name if ev.student else "Interno"
        findings.append(
            AgentFinding(
                code=ALERT_PENDING_EVALUATION,
                title="Evaluación pendiente",
                detail=(
                    f"Evaluación de fin de rotación pendiente para {student_name}."
                ),
                severity="warning",
                entity_type="evaluation",
                entity_id=ev.id,
            )
        )
    return findings


def rule_incomplete_profile(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Detect students whose profile is marked incomplete."""
    findings: list[AgentFinding] = []
    for s in repos.students.incomplete_profiles():
        findings.append(
            AgentFinding(
                code=ALERT_INCOMPLETE_PROFILE,
                title="Perfil de interno incompleto",
                detail=f"El perfil de {s.full_name} está incompleto.",
                severity="info",
                entity_type="student",
                entity_id=s.id,
            )
        )
    return findings


def rule_overdue_evaluation(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Pending evaluations whose rotation already ended (overdue)."""
    today = today or date.today()
    findings: list[AgentFinding] = []
    for ev in repos.evaluations.pending():
        a = ev.assignment
        if a and a.end_date and a.end_date < today:
            days = (today - a.end_date).days
            findings.append(
                AgentFinding(
                    code=ALERT_OVERDUE_EVALUATION,
                    title="Evaluación vencida",
                    detail=(
                        f"La evaluación de {ev.student.full_name if ev.student else 'interno'} "
                        f"está pendiente {days} día(s) después del fin de la rotación."
                    ),
                    severity="critical",
                    entity_type="evaluation",
                    entity_id=ev.id,
                )
            )
    return findings


def rule_student_overlap(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Students with overlapping active/planned rotations."""
    from app.models.base import AssignmentStatus

    by_student: dict[int, list] = {}
    for a in repos.assignments.all_with_relations():
        if a.status in (AssignmentStatus.ACTIVE.value, AssignmentStatus.PLANNED.value) \
                and a.start_date and a.end_date:
            by_student.setdefault(a.student_id, []).append(a)
    findings: list[AgentFinding] = []
    for student_id, rows in by_student.items():
        rows.sort(key=lambda a: a.start_date)
        for i in range(len(rows) - 1):
            if rows[i].end_date >= rows[i + 1].start_date:
                findings.append(
                    AgentFinding(
                        code=ALERT_STUDENT_OVERLAP,
                        title="Rotaciones superpuestas",
                        detail=(
                            f"{rows[i].student.full_name}: «{rows[i].rotation_type.name}» "
                            f"y «{rows[i + 1].rotation_type.name}» se superponen."
                        ),
                        severity="critical",
                        entity_type="student",
                        entity_id=student_id,
                    )
                )
                break
    return findings


def rule_tutor_sede_mismatch(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Assignments whose tutor does not belong to the assignment's sede."""
    findings: list[AgentFinding] = []
    for a in repos.assignments.all_with_relations():
        if a.tutor and a.tutor.sede_id != a.sede_id:
            findings.append(
                AgentFinding(
                    code=ALERT_TUTOR_SEDE_MISMATCH,
                    title="Tutor de otra sede",
                    detail=(
                        f"{a.student.full_name}: el tutor {a.tutor.user.full_name} "
                        f"no pertenece a {a.sede.short_name or a.sede.name}."
                    ),
                    severity="critical",
                    entity_type="rotation_assignment",
                    entity_id=a.id,
                )
            )
    return findings


def rule_institution_mismatch(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Assignments where the sede institution differs from the student's."""
    findings: list[AgentFinding] = []
    for a in repos.assignments.all_with_relations():
        st = a.student
        if st and st.institution_type_id and a.sede \
                and a.sede.institution_type_id != st.institution_type_id:
            findings.append(
                AgentFinding(
                    code=ALERT_INSTITUTION_MISMATCH,
                    title="Institución no coincide",
                    detail=(
                        f"{st.full_name}: la sede no coincide con la institución "
                        "del interno (MINSA/EsSalud)."
                    ),
                    severity="warning",
                    entity_type="rotation_assignment",
                    entity_id=a.id,
                )
            )
    return findings


def rule_activity_target_at_risk(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Active rotations ending soon with a fixed-target activity far below goal."""
    from app.config import settings
    from app.models.activity import TARGET_FIXED, STATUS_VERIFIED
    from app.models.base import AssignmentStatus

    today = today or date.today()
    cutoff = today + timedelta(days=settings.activity_at_risk_rotation_days)
    findings: list[AgentFinding] = []
    for a in repos.assignments.all_with_relations():
        if a.status != AssignmentStatus.ACTIVE.value or not a.end_date or a.end_date > cutoff:
            continue
        fixed_defs = [d for d in repos.activity_definitions.for_rotation(a.rotation_type_id)
                     if d.target_type == TARGET_FIXED]
        if not fixed_defs:
            continue
        entries = repos.student_activities.for_assignment(a.id)
        verified_by_def: dict[int, int] = {}
        for e in entries:
            if e.verification_status == STATUS_VERIFIED:
                verified_by_def[e.definition_id] = verified_by_def.get(e.definition_id, 0) + e.performed_count
        ratios = [min(1.0, verified_by_def.get(d.id, 0) / d.target_count) for d in fixed_defs]
        avg_ratio = sum(ratios) / len(ratios) if ratios else 0
        if avg_ratio < settings.activity_at_risk_threshold_ratio:
            findings.append(AgentFinding(
                code=ALERT_ACTIVITY_TARGET_AT_RISK,
                title="Meta de actividades en riesgo",
                detail=(f"{a.student.full_name if a.student else 'Interno'}: la rotación "
                        f"termina el {a.end_date:%d/%m/%Y} con {round(avg_ratio*100)}% de "
                        "avance promedio en metas fijas."),
                severity="warning", entity_type="rotation_assignment", entity_id=a.id,
            ))
    return findings


def rule_old_pending_activity(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Activities pending verification longer than the configured threshold."""
    from app.config import settings

    today = today or date.today()
    cutoff = today - timedelta(days=settings.activity_old_pending_days)
    findings: list[AgentFinding] = []
    for e in repos.student_activities.all_pending():
        if e.submitted_at and e.submitted_at.date() <= cutoff:
            findings.append(AgentFinding(
                code=ALERT_OLD_PENDING_ACTIVITY,
                title="Actividad pendiente hace tiempo",
                detail=(f"{e.student.full_name if e.student else 'Interno'}: "
                        f"«{e.definition.name}» pendiente desde {e.submitted_at:%d/%m/%Y}."),
                severity="warning", entity_type="student_activity", entity_id=e.id,
            ))
    return findings


def rule_rejected_activity_requires_correction(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Rejected activities not corrected within the configured threshold."""
    from app.config import settings
    from app.models.activity import STATUS_REJECTED

    today = today or date.today()
    cutoff = today - timedelta(days=settings.activity_rejected_correction_days)
    findings: list[AgentFinding] = []
    for e in repos.student_activities.all_with_relations():
        if e.verification_status == STATUS_REJECTED and e.updated_at and \
                e.updated_at.date() <= cutoff:
            findings.append(AgentFinding(
                code=ALERT_REJECTED_ACTIVITY_CORRECTION,
                title="Actividad rechazada sin corregir",
                detail=(f"{e.student.full_name if e.student else 'Interno'}: "
                        f"«{e.definition.name}» rechazada y sin corregir."),
                severity="warning", entity_type="student_activity", entity_id=e.id,
            ))
    return findings


def rule_rotation_completed_with_unverified_activities(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Completed assignments that still have pending activity entries."""
    from app.models.base import AssignmentStatus

    findings: list[AgentFinding] = []
    for a in repos.assignments.all_with_relations():
        if a.status != AssignmentStatus.COMPLETED.value:
            continue
        entries = repos.student_activities.for_assignment(a.id)
        pending = [e for e in entries if e.verification_status == "pending"]
        if pending:
            findings.append(AgentFinding(
                code=ALERT_ROTATION_COMPLETED_UNVERIFIED,
                title="Rotación completada con actividades sin verificar",
                detail=(f"{a.student.full_name if a.student else 'Interno'}: "
                        f"{len(pending)} actividad(es) pendiente(s) tras completar la rotación."),
                severity="critical", entity_type="rotation_assignment", entity_id=a.id,
            ))
    return findings


def rule_tutor_verification_backlog(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Tutors with more old pending verifications than the configured threshold."""
    from app.config import settings

    today = today or date.today()
    cutoff = today - timedelta(days=settings.activity_old_pending_days)
    counts: dict[int, int] = {}
    for e in repos.student_activities.all_pending():
        if not e.assignment or not e.assignment.tutor_id:
            continue
        if e.submitted_at and e.submitted_at.date() <= cutoff:
            counts[e.assignment.tutor_id] = counts.get(e.assignment.tutor_id, 0) + 1
    findings: list[AgentFinding] = []
    for tutor_id, count in counts.items():
        if count > settings.tutor_verification_backlog_threshold:
            tutor = repos.tutors.get(tutor_id)
            findings.append(AgentFinding(
                code=ALERT_TUTOR_VERIFICATION_BACKLOG,
                title="Cola de verificación elevada",
                detail=(f"{tutor.user.full_name if tutor else 'Tutor'}: {count} actividades "
                        f"pendientes hace más de {settings.activity_old_pending_days} días."),
                severity="warning", entity_type="tutor", entity_id=tutor_id,
            ))
    return findings


def rule_returned_evaluation(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Evaluations returned for correction, still awaiting tutor action."""
    from app.models.base import EvaluationStatus

    findings: list[AgentFinding] = []
    for ev in repos.evaluations.search(status=EvaluationStatus.RETURNED_FOR_CORRECTION.value):
        findings.append(AgentFinding(
            code=ALERT_RETURNED_EVALUATION,
            title="Evaluación devuelta para corrección",
            detail=(f"La evaluación de {ev.student.full_name if ev.student else 'interno'} "
                    "fue devuelta por el coordinador y requiere corrección del tutor."),
            severity="warning", entity_type="evaluation", entity_id=ev.id,
        ))
    return findings


def rule_submitted_evaluation(
    repos: RepositoryBundle, today: date | None = None
) -> list[AgentFinding]:
    """Evaluations submitted by the tutor, awaiting coordinator approval."""
    from app.models.base import EvaluationStatus

    findings: list[AgentFinding] = []
    for ev in repos.evaluations.search(status=EvaluationStatus.SUBMITTED.value):
        findings.append(AgentFinding(
            code=ALERT_SUBMITTED_EVALUATION,
            title="Evaluación esperando aprobación",
            detail=(f"La evaluación de {ev.student.full_name if ev.student else 'interno'} "
                    "fue enviada por el tutor y espera revisión del coordinador de sede."),
            severity="info", entity_type="evaluation", entity_id=ev.id,
        ))
    return findings


# Registry of rules: name -> callable. The engine iterates this so new rules
# are added in exactly one place.
RuleFn = Callable[[RepositoryBundle, "date | None"], list[AgentFinding]]

RULES: dict[str, RuleFn] = {
    ALERT_ROTATION_ENDING: rule_rotation_ending_soon,
    ALERT_MISSING_TUTOR: rule_missing_tutor,
    ALERT_PENDING_EVALUATION: rule_pending_evaluation,
    ALERT_INCOMPLETE_PROFILE: rule_incomplete_profile,
    ALERT_OVERDUE_EVALUATION: rule_overdue_evaluation,
    ALERT_STUDENT_OVERLAP: rule_student_overlap,
    ALERT_TUTOR_SEDE_MISMATCH: rule_tutor_sede_mismatch,
    ALERT_INSTITUTION_MISMATCH: rule_institution_mismatch,
    ALERT_ACTIVITY_TARGET_AT_RISK: rule_activity_target_at_risk,
    ALERT_OLD_PENDING_ACTIVITY: rule_old_pending_activity,
    ALERT_REJECTED_ACTIVITY_CORRECTION: rule_rejected_activity_requires_correction,
    ALERT_ROTATION_COMPLETED_UNVERIFIED: rule_rotation_completed_with_unverified_activities,
    ALERT_TUTOR_VERIFICATION_BACKLOG: rule_tutor_verification_backlog,
    ALERT_RETURNED_EVALUATION: rule_returned_evaluation,
    ALERT_SUBMITTED_EVALUATION: rule_submitted_evaluation,
}


class RuleEngine:
    """Runs the registered deterministic rules and aggregates findings."""

    def __init__(self, repos: RepositoryBundle) -> None:
        self.repos = repos

    def run_rule(self, code: str, today: date | None = None) -> list[AgentFinding]:
        fn = RULES.get(code)
        if fn is None:
            raise KeyError(f"Unknown rule: {code}")
        return fn(self.repos, today)

    def run_all(self, today: date | None = None) -> list[AgentFinding]:
        """Execute every registered rule and return the combined findings."""
        findings: list[AgentFinding] = []
        for fn in RULES.values():
            findings.extend(fn(self.repos, today))
        return findings
