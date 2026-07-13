"""Digital evaluation workflow service (Batch 2D).

Owns the full lifecycle: pending → in_progress (tutor starts) → submitted
(tutor submits, server recalculates all totals — the browser total is never
trusted) → approved (sede coordinator) or returned_for_correction (sede
coordinator, mandatory comment) → in_progress (tutor corrects and resubmits).
Administrator may reopen an approved evaluation with a mandatory reason.
Record-level scope, audit logging and alert refresh follow the same pattern as
rotation_service.py / student_activity_service.py.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin, is_global_viewer
from app.models.base import EvaluationStatus, utcnow
from app.models.evaluation import AREA_ATTITUDE, AREA_KNOWLEDGE, AREA_PERFORMANCE, Evaluation
from app.models.user import ROLE_SEDE_COORDINATOR, ROLE_STUDENT, ROLE_TUTOR
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import ValidationError

AREAS = [AREA_KNOWLEDGE, AREA_PERFORMANCE, AREA_ATTITUDE]
CRITERIA_PER_AREA = 5
TOTAL_CRITERIA = CRITERIA_PER_AREA * len(AREAS)

# Allowed status transitions.
TRANSITIONS = {
    EvaluationStatus.PENDING.value: {EvaluationStatus.IN_PROGRESS.value},
    EvaluationStatus.IN_PROGRESS.value: {EvaluationStatus.SUBMITTED.value},
    EvaluationStatus.SUBMITTED.value: {
        EvaluationStatus.APPROVED.value, EvaluationStatus.RETURNED_FOR_CORRECTION.value,
    },
    EvaluationStatus.RETURNED_FOR_CORRECTION.value: {EvaluationStatus.IN_PROGRESS.value},
    EvaluationStatus.APPROVED.value: set(),  # only reachable via admin reopen (special-cased)
}
LOCKED_STATUSES = {EvaluationStatus.APPROVED.value}
EDITABLE_STATUSES = {
    EvaluationStatus.PENDING.value, EvaluationStatus.IN_PROGRESS.value,
    EvaluationStatus.RETURNED_FOR_CORRECTION.value,
}


class EvaluationService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    # -- scope ------------------------------------------------------------
    def _own_tutor_ids(self) -> set[int]:
        return {t.id for t in self.repos.tutors.active() if t.user_id == self.identity.user_id}

    def _own_sede_ids(self) -> set[int]:
        return {c.sede_id for c in self.repos.sede_coordinators.active()
                if c.user_id == self.identity.user_id and c.sede_id}

    def _own_student_ids(self) -> set[int]:
        return {s.id for s in self.repos.students.search(active=None)
                if s.user_id == self.identity.user_id}

    def can_view(self, ev: Evaluation) -> bool:
        role = self.identity.role_code
        if is_global_viewer(self.identity):
            return True
        if role == ROLE_TUTOR:
            return ev.tutor_id in self._own_tutor_ids()
        if role == ROLE_SEDE_COORDINATOR:
            return bool(ev.assignment) and ev.assignment.sede_id in self._own_sede_ids()
        if role == ROLE_STUDENT:
            return (ev.student_id in self._own_student_ids()
                   and ev.status == EvaluationStatus.APPROVED.value)
        return False

    def can_edit(self, ev: Evaluation) -> bool:
        """Tutor may fill/submit only their own, editable-status evaluations."""
        if self.identity.role_code != ROLE_TUTOR:
            return False
        return ev.tutor_id in self._own_tutor_ids() and ev.status in EDITABLE_STATUSES

    def can_review(self, ev: Evaluation) -> bool:
        """Sede Coordinator may approve/return only own-sede submitted evaluations."""
        if self.identity.role_code != ROLE_SEDE_COORDINATOR:
            return False
        return (bool(ev.assignment) and ev.assignment.sede_id in self._own_sede_ids()
               and ev.status == EvaluationStatus.SUBMITTED.value)

    # -- listing / detail ---------------------------------------------------
    def list_evaluations(self, **filters) -> list[Evaluation]:
        role = self.identity.role_code
        if role == ROLE_STUDENT:
            filters["student_ids"] = self._own_student_ids() or {-1}
            filters["status"] = EvaluationStatus.APPROVED.value
        elif role == ROLE_TUTOR:
            filters["tutor_ids"] = self._own_tutor_ids() or {-1}
        elif role == ROLE_SEDE_COORDINATOR:
            filters["sede_ids"] = self._own_sede_ids() or {-1}
        return self.repos.evaluations.search(**filters)

    def get_for_view(self, evaluation_id: int) -> Evaluation:
        ev = self.repos.evaluations.get_full(evaluation_id)
        ensure(ev is not None, "Evaluación no encontrada.", "not_found")
        ensure(self.can_view(ev), "No puede ver esta evaluación.", "evaluation_scope_denied")
        return ev

    def build_detail(self, evaluation_id: int) -> dict:
        ev = self.get_for_view(evaluation_id)
        criteria_by_area = {area: sorted(
            [c for c in ev.criteria if c.area == area], key=lambda c: c.order_index
        ) for area in AREAS}
        audit_rows = [r for r in self.repos.audit_logs.recent(limit=300)
                      if r.entity_type == "evaluation" and r.entity_id == ev.id][:12]
        return {
            "ev": ev, "criteria_by_area": criteria_by_area,
            "can_edit": self.can_edit(ev), "can_review": self.can_review(ev),
            "can_reopen": is_admin(self.identity) and ev.status == EvaluationStatus.APPROVED.value,
            "audit_rows": audit_rows,
        }

    # -- server-side, authoritative recompute --------------------------------
    @staticmethod
    def _recompute(ev: Evaluation) -> dict[str, float | None]:
        """Recompute area totals and final score from criteria scores only.

        Never trusts any client-submitted total. Returns None for an area with
        any unscored criterion (used to detect incompleteness at submit time).
        """
        totals: dict[str, float | None] = {}
        for area in AREAS:
            scores = [c.score for c in ev.criteria if c.area == area]
            if len(scores) != CRITERIA_PER_AREA or any(s is None for s in scores):
                totals[area] = None
            else:
                totals[area] = float(sum(scores))
        return totals

    def _apply_scores(self, ev: Evaluation, scores: dict[int, int | None]) -> None:
        """Apply {criterion_id: score} to the evaluation's criteria rows."""
        for c in ev.criteria:
            if c.id in scores:
                c.score = scores[c.id]

    def _parse_scores(self, ev: Evaluation, data: dict) -> dict[int, int | None]:
        parsed: dict[int, int | None] = {}
        errors: dict[str, str] = {}
        for c in ev.criteria:
            key = f"score_{c.id}"
            raw = (data.get(key) or "").strip()
            if raw == "":
                parsed[c.id] = None
                continue
            try:
                val = int(raw)
            except ValueError:
                errors[key] = "El puntaje debe ser un número entero."
                continue
            if val < 0 or val > 4:
                errors[key] = "El puntaje debe estar entre 0 y 4."
                continue
            parsed[c.id] = val
        if errors:
            raise ValidationError(errors)
        return parsed

    # -- transitions --------------------------------------------------------
    def start(self, evaluation_id: int, ip: str | None = None) -> Evaluation:
        ev = self.repos.evaluations.get_full(evaluation_id)
        ensure(ev is not None, "Evaluación no encontrada.", "not_found")
        ensure(self.can_edit(ev), "No puede iniciar esta evaluación.", "start_evaluation_denied")
        ensure(ev.status == EvaluationStatus.PENDING.value,
               "Solo se puede iniciar una evaluación pendiente.", "invalid_transition")
        ev.status = EvaluationStatus.IN_PROGRESS.value
        self.db.flush()
        self.audit.record(audit.START_EVALUATION, identity=self.identity,
                          entity_type="evaluation", entity_id=ev.id, ip_address=ip, commit=False)
        self.db.commit()
        return ev

    def save_draft(self, evaluation_id: int, data: dict, ip: str | None = None) -> Evaluation:
        ev = self.repos.evaluations.get_full(evaluation_id)
        ensure(ev is not None, "Evaluación no encontrada.", "not_found")
        ensure(self.can_edit(ev), "No puede editar esta evaluación.", "edit_evaluation_denied")
        scores = self._parse_scores(ev, data)
        self._apply_scores(ev, scores)
        ev.comments = (data.get("comments") or "").strip() or None
        if ev.status == EvaluationStatus.PENDING.value:
            ev.status = EvaluationStatus.IN_PROGRESS.value
        totals = self._recompute(ev)
        ev.score_knowledge = totals[AREA_KNOWLEDGE]
        ev.score_performance = totals[AREA_PERFORMANCE]
        ev.score_attitude = totals[AREA_ATTITUDE]
        self.db.flush()
        self.audit.record(audit.SAVE_EVALUATION_DRAFT, identity=self.identity,
                          entity_type="evaluation", entity_id=ev.id, ip_address=ip, commit=False)
        self.db.commit()
        return ev

    def submit(self, evaluation_id: int, data: dict, ip: str | None = None) -> Evaluation:
        ev = self.repos.evaluations.get_full(evaluation_id)
        ensure(ev is not None, "Evaluación no encontrada.", "not_found")
        ensure(self.can_edit(ev), "No puede enviar esta evaluación.", "submit_evaluation_denied")
        scores = self._parse_scores(ev, data)
        self._apply_scores(ev, scores)
        ev.comments = (data.get("comments") or "").strip() or None

        # Authoritative server-side recompute — the browser's live totals are
        # for convenience only and are never trusted.
        totals = self._recompute(ev)
        missing = [c.description for area in AREAS for c in ev.criteria
                  if c.area == area and c.score is None]
        if missing or any(v is None for v in totals.values()):
            raise ValidationError({"criteria": "Debe calificar los 15 criterios "
                                                "(0 a 4) antes de enviar la evaluación."})

        ev.score_knowledge = totals[AREA_KNOWLEDGE]
        ev.score_performance = totals[AREA_PERFORMANCE]
        ev.score_attitude = totals[AREA_ATTITUDE]
        ev.final_score = round(sum(totals.values()) / len(AREAS), 2)
        ev.status = EvaluationStatus.SUBMITTED.value
        ev.submitted_at = utcnow()
        ev.submitted_by_user_id = self.identity.user_id
        self.db.flush()
        self.audit.record(audit.SUBMIT_EVALUATION, identity=self.identity,
                          entity_type="evaluation", entity_id=ev.id,
                          detail={"final_score": ev.final_score}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return ev

    def return_for_correction(self, evaluation_id: int, comments: str,
                              ip: str | None = None) -> Evaluation:
        ev = self.repos.evaluations.get_full(evaluation_id)
        ensure(ev is not None, "Evaluación no encontrada.", "not_found")
        ensure(self.can_review(ev), "No puede devolver esta evaluación.", "return_evaluation_denied")
        if not (comments or "").strip():
            raise ValidationError({"comments": "Debe indicar el motivo de la devolución."})
        ev.status = EvaluationStatus.RETURNED_FOR_CORRECTION.value
        ev.reviewed_at = utcnow()
        ev.reviewed_by_user_id = self.identity.user_id
        ev.review_comments = comments.strip()
        self.db.flush()
        self.audit.record(audit.RETURN_EVALUATION, identity=self.identity,
                          entity_type="evaluation", entity_id=ev.id,
                          reason=comments.strip(), ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return ev

    def approve(self, evaluation_id: int, comments: str = "", ip: str | None = None) -> Evaluation:
        ev = self.repos.evaluations.get_full(evaluation_id)
        ensure(ev is not None, "Evaluación no encontrada.", "not_found")
        ensure(self.can_review(ev), "No puede aprobar esta evaluación.", "approve_evaluation_denied")
        ev.status = EvaluationStatus.APPROVED.value
        ev.reviewed_at = utcnow()
        ev.reviewed_by_user_id = self.identity.user_id
        if comments.strip():
            ev.review_comments = comments.strip()
        self.db.flush()
        self.audit.record(audit.APPROVE_EVALUATION, identity=self.identity,
                          entity_type="evaluation", entity_id=ev.id,
                          detail={"final_score": ev.final_score}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return ev

    def reopen(self, evaluation_id: int, reason: str, ip: str | None = None) -> Evaluation:
        ensure(is_admin(self.identity), "Solo un administrador puede reabrir.", "reopen_evaluation_denied")
        ev = self.repos.evaluations.get_full(evaluation_id)
        ensure(ev is not None, "Evaluación no encontrada.", "not_found")
        ensure(ev.status == EvaluationStatus.APPROVED.value,
               "Solo se puede reabrir una evaluación aprobada.", "invalid_transition")
        if not (reason or "").strip():
            raise ValidationError({"reason": "Debe indicar un motivo para reabrir."})
        ev.status = EvaluationStatus.IN_PROGRESS.value
        ev.reopened_at = utcnow()
        ev.reopened_reason = reason.strip()
        self.db.flush()
        self.audit.record(audit.REOPEN_EVALUATION, identity=self.identity,
                          entity_type="evaluation", entity_id=ev.id,
                          reason=reason.strip(), ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return ev

    def _refresh_alerts(self) -> None:
        from app.services.alert_service import AlertService
        AlertService(self.db).refresh_from_rules()
