"""Student activity/procedure log service (Batch 2C).

Owns the student entry workflow (create/edit/cancel), tutor verification
(verify/reject/bulk-verify), admin reopen, progress calculations, the tutor
inbox, and coordinator monitoring queries. Conflict/authorization logic mirrors
the patterns established in rotation_service.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin, is_global_viewer
from app.config import settings
from app.models.activity import (
    REVIEW_CORRECTED,
    REVIEW_REJECTED,
    REVIEW_REOPENED,
    REVIEW_VERIFIED,
    STATUS_CANCELLED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_VERIFIED,
    TARGET_COMPLETION_ONLY,
    TARGET_FIXED,
    TARGET_NO_FIXED,
    ActivityReview,
    StudentActivity,
)
from app.models.base import utcnow
from app.models.user import ROLE_SEDE_COORDINATOR, ROLE_STUDENT, ROLE_TUTOR
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.privacy_validator import WARNING_MESSAGE, find_identifier_risk
from app.services.validators import FieldValidator, ValidationError


@dataclass
class ActivityProgress:
    """Progress rollup for one activity definition within an assignment."""

    definition: object
    target_type: str
    target_count: int | None
    verified_count: int
    pending_count: int
    rejected_count: int
    percent: float | None  # None for no_fixed_target
    percent_display: int | None
    completed: bool | None  # only meaningful for completion_only


class StudentActivityService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    # -- scope helpers ------------------------------------------------------
    def _own_student_ids(self) -> set[int]:
        return {s.id for s in self.repos.students.search(active=None)
                if s.user_id == self.identity.user_id}

    def _own_tutor_ids(self) -> set[int]:
        return {t.id for t in self.repos.tutors.active()
                if t.user_id == self.identity.user_id}

    def _own_sede_ids(self) -> set[int]:
        return {c.sede_id for c in self.repos.sede_coordinators.active()
                if c.user_id == self.identity.user_id and c.sede_id}

    def can_view_activity(self, a: StudentActivity) -> bool:
        if is_global_viewer(self.identity):
            return True
        if self.identity.role_code == ROLE_STUDENT:
            return a.student_id in self._own_student_ids()
        if self.identity.role_code == ROLE_TUTOR:
            return bool(a.assignment) and a.assignment.tutor_id in self._own_tutor_ids()
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            return bool(a.assignment) and a.assignment.sede_id in self._own_sede_ids()
        return False

    def get_for_view(self, activity_id: int) -> StudentActivity:
        a = self.repos.student_activities.get_full(activity_id)
        ensure(a is not None, "Actividad no encontrada.", "not_found")
        ensure(self.can_view_activity(a), "No puede ver esta actividad.", "activity_scope_denied")
        return a

    # -- create / edit --------------------------------------------------------
    def _validate_entry(self, assignment, data: dict, *, existing: StudentActivity | None) -> dict:
        v = FieldValidator()
        definition_id = v.int_field("definition_id", data.get("definition_id"), "La actividad")
        if not definition_id:
            v.add("definition_id", "La actividad es obligatoria.")
        logged_on = v.date("logged_on", data.get("logged_on"), "La fecha")
        quantity = v.int_field("performed_count", data.get("performed_count"),
                               "La cantidad", min_v=1)
        if not quantity:
            v.add("performed_count", "La cantidad debe ser un entero positivo.")
        notes = (data.get("notes") or "").strip() or None
        evidence = (data.get("evidence_reference") or "").strip() or None

        if find_identifier_risk(notes, evidence):
            v.add("notes", WARNING_MESSAGE)

        definition = self.repos.activity_definitions.get(definition_id) if definition_id else None
        if definition:
            if not definition.is_active:
                v.add("definition_id", "La definición está inactiva y no admite nuevos registros.")
            allowed_ids = {d.id for d in self.repos.activity_definitions.for_rotation(
                assignment.rotation_type_id, active_only=False)}
            if definition.id not in allowed_ids:
                v.add("definition_id", "La actividad no pertenece a la rotación de esta asignación.")
            if definition.target_type == TARGET_COMPLETION_ONLY and quantity and quantity != 1:
                quantity = 1  # completion-only activities are always quantity=1

        if logged_on and assignment.start_date and assignment.end_date:
            grace = timedelta(days=settings.activity_retrospective_grace_days)
            if logged_on < (assignment.start_date - grace) or logged_on > (assignment.end_date + grace):
                v.add("logged_on", "La fecha debe corresponder al periodo de la rotación "
                                    f"(con {settings.activity_retrospective_grace_days} días de margen).")

        v.raise_if_errors()
        return {"definition_id": definition_id, "logged_on": logged_on,
                "performed_count": quantity, "notes": notes, "evidence_reference": evidence}

    def create(self, assignment_id: int, data: dict, ip: str | None = None) -> StudentActivity:
        assignment = self.repos.assignments.get_full(assignment_id)
        ensure(assignment is not None, "Rotación no encontrada.", "not_found")
        own_ids = self._own_student_ids()
        ensure(assignment.student_id in own_ids,
               "Solo puede registrar actividades en su propia asignación.", "create_activity_denied")
        ensure(assignment.status in ("active", "planned"),
               "La asignación debe estar activa para registrar actividades.", "assignment_not_active")
        clean = self._validate_entry(assignment, data, existing=None)
        entry = StudentActivity(
            student_id=assignment.student_id, assignment_id=assignment.id,
            created_by_user_id=self.identity.user_id, verification_status=STATUS_PENDING,
            submitted_at=utcnow(), **clean,
        )
        self.repos.student_activities.add(entry)
        self.db.flush()
        self.audit.record(audit.CREATE_STUDENT_ACTIVITY, identity=self.identity,
                          entity_type="student_activity", entity_id=entry.id,
                          detail={"assignment_id": assignment.id, "definition_id": entry.definition_id},
                          ip_address=ip, commit=False)
        self.db.commit()
        return entry

    def update(self, activity_id: int, data: dict, ip: str | None = None) -> StudentActivity:
        entry = self.repos.student_activities.get_full(activity_id)
        ensure(entry is not None, "Actividad no encontrada.", "not_found")
        ensure(entry.student_id in self._own_student_ids(),
               "Solo puede editar sus propios registros.", "edit_activity_denied")
        ensure(entry.verification_status in (STATUS_PENDING, STATUS_REJECTED),
               "Solo se pueden editar registros pendientes o rechazados.", "activity_locked")
        was_rejected = entry.verification_status == STATUS_REJECTED
        clean = self._validate_entry(entry.assignment, data, existing=entry)
        for field, value in clean.items():
            setattr(entry, field, value)
        if was_rejected:
            entry.verification_status = STATUS_PENDING
            entry.submitted_at = utcnow()
            self.db.add(ActivityReview(student_activity_id=entry.id, action=REVIEW_CORRECTED,
                                       reviewer_user_id=self.identity.user_id,
                                       comment="Corregido y reenviado por el interno."))
            action = audit.CORRECT_STUDENT_ACTIVITY
        else:
            action = audit.UPDATE_STUDENT_ACTIVITY
        self.db.flush()
        self.audit.record(action, identity=self.identity, entity_type="student_activity",
                          entity_id=entry.id, ip_address=ip, commit=False)
        self.db.commit()
        return entry

    def cancel(self, activity_id: int, ip: str | None = None) -> StudentActivity:
        entry = self.repos.student_activities.get_full(activity_id)
        ensure(entry is not None, "Actividad no encontrada.", "not_found")
        ensure(entry.student_id in self._own_student_ids(),
               "Solo puede cancelar sus propios registros.", "cancel_activity_denied")
        ensure(entry.verification_status == STATUS_PENDING,
               "Solo se pueden cancelar registros pendientes.", "activity_not_cancellable")
        entry.verification_status = STATUS_CANCELLED
        self.db.flush()
        self.audit.record(audit.CANCEL_STUDENT_ACTIVITY, identity=self.identity,
                          entity_type="student_activity", entity_id=entry.id, ip_address=ip, commit=False)
        self.db.commit()
        return entry

    # -- tutor verification ---------------------------------------------------
    def _own_active_tutor(self):
        tutors = [t for t in self.repos.tutors.active() if t.user_id == self.identity.user_id]
        return tutors[0] if tutors else None

    def can_review(self, entry: StudentActivity) -> bool:
        if is_admin(self.identity):
            return True
        if self.identity.role_code != ROLE_TUTOR:
            return False
        tutor = self._own_active_tutor()
        return bool(tutor) and bool(entry.assignment) and entry.assignment.tutor_id == tutor.id

    def verify(self, activity_id: int, ip: str | None = None) -> StudentActivity:
        entry = self.repos.student_activities.get_full(activity_id)
        ensure(entry is not None, "Actividad no encontrada.", "not_found")
        ensure(self.can_review(entry), "No puede verificar esta actividad.", "verify_activity_denied")
        ensure(entry.verification_status == STATUS_PENDING,
               "Solo se pueden verificar registros pendientes.", "activity_not_pending")
        entry.verification_status = STATUS_VERIFIED
        self.db.add(ActivityReview(student_activity_id=entry.id, action=REVIEW_VERIFIED,
                                   reviewer_user_id=self.identity.user_id))
        self.db.flush()
        self.audit.record(audit.VERIFY_STUDENT_ACTIVITY, identity=self.identity,
                          entity_type="student_activity", entity_id=entry.id, ip_address=ip, commit=False)
        self.db.commit()
        return entry

    def reject(self, activity_id: int, comment: str, ip: str | None = None) -> StudentActivity:
        entry = self.repos.student_activities.get_full(activity_id)
        ensure(entry is not None, "Actividad no encontrada.", "not_found")
        ensure(self.can_review(entry), "No puede rechazar esta actividad.", "reject_activity_denied")
        ensure(entry.verification_status == STATUS_PENDING,
               "Solo se pueden rechazar registros pendientes.", "activity_not_pending")
        if not (comment or "").strip():
            raise ValidationError({"comment": "El rechazo requiere un comentario."})
        entry.verification_status = STATUS_REJECTED
        self.db.add(ActivityReview(student_activity_id=entry.id, action=REVIEW_REJECTED,
                                   reviewer_user_id=self.identity.user_id, comment=comment.strip()))
        self.db.flush()
        self.audit.record(audit.REJECT_STUDENT_ACTIVITY, identity=self.identity,
                          entity_type="student_activity", entity_id=entry.id,
                          reason=comment.strip(), ip_address=ip, commit=False)
        self.db.commit()
        return entry

    def bulk_verify(self, activity_ids: list[int], ip: str | None = None) -> int:
        verified = 0
        for aid in activity_ids:
            entry = self.repos.student_activities.get_full(aid)
            if entry is None or not self.can_review(entry) or entry.verification_status != STATUS_PENDING:
                continue
            entry.verification_status = STATUS_VERIFIED
            self.db.add(ActivityReview(student_activity_id=entry.id, action=REVIEW_VERIFIED,
                                       reviewer_user_id=self.identity.user_id,
                                       comment="Verificación masiva."))
            verified += 1
        if verified:
            self.db.flush()
            self.audit.record(audit.BULK_VERIFY_STUDENT_ACTIVITIES, identity=self.identity,
                              entity_type="student_activity", detail={"count": verified},
                              ip_address=ip, commit=False)
            self.db.commit()
        return verified

    def reopen(self, activity_id: int, reason: str, ip: str | None = None) -> StudentActivity:
        ensure(is_admin(self.identity), "Solo un administrador puede reabrir.", "reopen_activity_denied")
        entry = self.repos.student_activities.get_full(activity_id)
        ensure(entry is not None, "Actividad no encontrada.", "not_found")
        ensure(entry.verification_status == STATUS_VERIFIED,
               "Solo se pueden reabrir registros verificados.", "activity_not_verified")
        if not (reason or "").strip():
            raise ValidationError({"reason": "Debe indicar un motivo para reabrir."})
        entry.verification_status = STATUS_PENDING
        self.db.add(ActivityReview(student_activity_id=entry.id, action=REVIEW_REOPENED,
                                   reviewer_user_id=self.identity.user_id, comment=reason.strip()))
        self.db.flush()
        self.audit.record(audit.REOPEN_STUDENT_ACTIVITY, identity=self.identity,
                          entity_type="student_activity", entity_id=entry.id,
                          reason=reason.strip(), ip_address=ip, commit=False)
        self.db.commit()
        return entry

    # -- tutor inbox ----------------------------------------------------------
    def inbox(self) -> list[StudentActivity]:
        if is_admin(self.identity) or self.identity.role_code == "university_coordinator":
            return self.repos.student_activities.all_pending()
        tutor = self._own_active_tutor()
        if not tutor:
            return []
        return self.repos.student_activities.pending_for_tutor(tutor.id)

    # -- progress calculations --------------------------------------------
    def assignment_progress(self, assignment_id: int) -> list[ActivityProgress]:
        assignment = self.repos.assignments.get(assignment_id)
        if assignment is None:
            return []
        definitions = self.repos.activity_definitions.for_rotation(
            assignment.rotation_type_id, active_only=False)
        entries = self.repos.student_activities.for_assignment(assignment_id)
        by_def: dict[int, list[StudentActivity]] = {}
        for e in entries:
            by_def.setdefault(e.definition_id, []).append(e)

        rows = []
        for d in definitions:
            related = by_def.get(d.id, [])
            verified = sum(e.performed_count for e in related if e.verification_status == STATUS_VERIFIED)
            pending = sum(1 for e in related if e.verification_status == STATUS_PENDING)
            rejected = sum(1 for e in related if e.verification_status == STATUS_REJECTED)
            if not related:
                continue  # only show activities the student has actually logged
            percent = None
            percent_display = None
            completed = None
            if d.target_type == TARGET_FIXED and d.target_count:
                percent = round(verified / d.target_count * 100, 1)
                percent_display = min(100, int(percent))
            elif d.target_type == TARGET_COMPLETION_ONLY:
                completed = verified >= 1
            rows.append(ActivityProgress(
                definition=d, target_type=d.target_type, target_count=d.target_count,
                verified_count=verified, pending_count=pending, rejected_count=rejected,
                percent=percent, percent_display=percent_display, completed=completed,
            ))
        return rows

    def assignment_summary(self, assignment_id: int) -> dict:
        rows = self.assignment_progress(assignment_id)
        entries = self.repos.student_activities.for_assignment(assignment_id)
        fixed_rows = [r for r in rows if r.target_type == TARGET_FIXED]
        avg_fixed_pct = (round(sum(r.percent for r in fixed_rows) / len(fixed_rows), 1)
                         if fixed_rows else None)
        return {
            "rows": rows,
            "entries": entries,
            "pending_count": sum(1 for e in entries if e.verification_status == STATUS_PENDING),
            "rejected_count": sum(1 for e in entries if e.verification_status == STATUS_REJECTED),
            "verified_count": sum(1 for e in entries if e.verification_status == STATUS_VERIFIED),
            "fixed_rows": fixed_rows,
            "no_fixed_rows": [r for r in rows if r.target_type == TARGET_NO_FIXED],
            "completion_rows": [r for r in rows if r.target_type == TARGET_COMPLETION_ONLY],
            "avg_fixed_percent": avg_fixed_pct,
        }

    def can_log_activity(self, assignment) -> bool:
        if self.identity.role_code != ROLE_STUDENT:
            return False
        return assignment.student_id in self._own_student_ids() and assignment.status in ("active", "planned")

    def form_options(self, assignment) -> dict:
        defs = self.repos.activity_definitions.for_rotation(assignment.rotation_type_id)
        return {"definitions": [(d.id, f"{d.name}"
                                 + (f" (meta: {d.target_count})" if d.target_type == "fixed" else
                                    " (NA — mayor número posible)" if d.target_type == "no_fixed_target" else ""))
                                for d in defs]}

    # -- coordinator monitoring ---------------------------------------------
    def monitoring_scope_sede_ids(self) -> set[int] | None:
        if is_global_viewer(self.identity):
            return None
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            return self._own_sede_ids()
        return set()

    def build_monitoring(self) -> dict:
        scope = self.monitoring_scope_sede_ids()
        assignments = [a for a in self.repos.assignments.all_with_relations()
                      if scope is None or a.sede_id in scope]
        today = date.today()
        old_pending_cutoff = today - timedelta(days=settings.activity_old_pending_days)
        at_risk_cutoff = today + timedelta(days=settings.activity_at_risk_rotation_days)

        low_progress = []
        old_pending_students = {}
        rejected_students = {}
        at_risk_rotations = []
        tutor_backlog: dict[int, int] = {}

        for a in assignments:
            entries = self.repos.student_activities.for_assignment(a.id)
            fixed_defs = [d for d in self.repos.activity_definitions.for_rotation(a.rotation_type_id)
                         if d.target_type == TARGET_FIXED]
            if fixed_defs:
                verified_by_def = {}
                for e in entries:
                    if e.verification_status == STATUS_VERIFIED:
                        verified_by_def[e.definition_id] = verified_by_def.get(e.definition_id, 0) + e.performed_count
                ratios = [min(1.0, verified_by_def.get(d.id, 0) / d.target_count) for d in fixed_defs]
                avg_ratio = sum(ratios) / len(ratios) if ratios else 0
                if avg_ratio < 0.5:
                    low_progress.append({"assignment": a, "ratio": round(avg_ratio * 100, 1)})
                if a.end_date and a.end_date <= at_risk_cutoff and avg_ratio < settings.activity_at_risk_threshold_ratio \
                        and a.status == "active":
                    at_risk_rotations.append({"assignment": a, "ratio": round(avg_ratio * 100, 1)})

            for e in entries:
                if e.verification_status == "pending" and e.submitted_at and \
                        e.submitted_at.date() <= old_pending_cutoff:
                    old_pending_students.setdefault(a.student_id, []).append(e)
                if e.verification_status == "rejected":
                    rejected_students.setdefault(a.student_id, []).append(e)

            if a.tutor_id:
                pending_old = [e for e in entries if e.verification_status == "pending"
                              and e.submitted_at and e.submitted_at.date() <= old_pending_cutoff]
                if pending_old:
                    tutor_backlog[a.tutor_id] = tutor_backlog.get(a.tutor_id, 0) + len(pending_old)

        backlog_tutors = [
            {"tutor": self.repos.tutors.get(tid), "count": count}
            for tid, count in tutor_backlog.items()
            if count > settings.tutor_verification_backlog_threshold
        ]

        return {
            "low_progress": low_progress,
            "old_pending_students": old_pending_students,
            "rejected_students": rejected_students,
            "at_risk_rotations": at_risk_rotations,
            "backlog_tutors": backlog_tutors,
        }
