"""Shared evaluation instrument catalog and pending-evaluation creation.

The 15 official criteria (three areas × five) from 'FORMATO DE EVALUACION
INTERNO' live here as the single source of truth, reused by the seed and by the
automatic pending-evaluation creation on rotation completion (Batch 2B).

Full score capture/approval is a later batch; here we only ensure a ``pending``
evaluation with its criteria exists.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.base import EvaluationStatus
from app.models.evaluation import (
    AREA_ATTITUDE,
    AREA_KNOWLEDGE,
    AREA_PERFORMANCE,
    Evaluation,
    EvaluationCriterion,
)

# The exact 15 criteria from the official 2026 instrument.
EVAL_CRITERIA: dict[str, list[str]] = {
    AREA_KNOWLEDGE: [
        "Explica la fisiopatología de los hallazgos clínicos según conocimientos científicos actuales",
        "Explica el fundamento de las medidas terapéuticas según conocimientos científicos actuales",
        "Participa activamente en sesiones académicas programadas",
        "Expone guías clínicas actualizadas sobre el manejo de las patologías",
        "Expone de forma clara y coherente artículos de revistas en relación a temas designados",
    ],
    AREA_PERFORMANCE: [
        "Elabora historias clínicas según las normas de la institución de salud",
        "Reporta clara y oportunamente los datos del paciente que se le solicita",
        "Propone exámenes auxiliares y tratamiento según guías clínicas",
        "Enumera posibles complicaciones y propone medidas preventivas",
        "Usa las normas de bioseguridad de la institución",
    ],
    AREA_ATTITUDE: [
        "Evidencia pulcritud, esmero y limpieza",
        "Cumple con el horario establecido y asiste puntualmente a las actividades programadas",
        "Establece una relación médico-paciente con empatía y respeto",
        "Trabaja de manera responsable y respetuosa con el equipo multidisciplinario de salud",
        "Manifiesta iniciativa y deseos de superación en su trabajo",
    ],
}


def seed_criteria(db: Session, evaluation: Evaluation, *, scored: bool = False) -> None:
    """Attach the 15 official criteria to an evaluation (idempotent per call)."""
    if evaluation.criteria:  # already has criteria — do not duplicate
        return
    for area, items in EVAL_CRITERIA.items():
        for idx, desc in enumerate(items):
            db.add(EvaluationCriterion(
                evaluation_id=evaluation.id, area=area, order_index=idx,
                description=desc,
                score=(4 if scored and idx % 2 == 0 else 3) if scored else None,
            ))


def ensure_pending_evaluation(db: Session, assignment) -> tuple[Evaluation, bool]:
    """Ensure a pending evaluation exists for a completed assignment.

    Returns ``(evaluation, created)``. Never duplicates: if the assignment
    already has an evaluation, that one is returned untouched.
    """
    existing = db.query(Evaluation).filter(
        Evaluation.assignment_id == assignment.id
    ).one_or_none()
    if existing is not None:
        return existing, False

    evaluation = Evaluation(
        assignment_id=assignment.id,
        student_id=assignment.student_id,
        tutor_id=assignment.tutor_id,
        status=EvaluationStatus.PENDING.value,
    )
    db.add(evaluation)
    db.flush()
    seed_criteria(db, evaluation)
    return evaluation, True
