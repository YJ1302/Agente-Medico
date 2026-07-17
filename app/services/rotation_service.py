"""Rotation assignment service (Batch 2B).

Owns the full lifecycle: create/edit, status transitions (planned → active →
completed / cancelled, admin reopen), tutor assign/reassign/remove, automatic
pending-evaluation creation on completion, record-level scope, audit logging and
alert refresh. Conflict logic is delegated to ``RotationConflictService``.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin, is_global_viewer
from app.models.base import AssignmentStatus, InstitutionCode, utcnow
from app.models.academic import RotationAssignment
from app.models.user import (
    ROLE_SEDE_COORDINATOR,
    ROLE_STUDENT,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
)
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.alert_service import AlertService
from app.services.evaluation_catalog import ensure_pending_evaluation
from app.services.rotation_conflict_service import (
    Conflict,
    RotationConflictService,
    RotationInput,
)
from app.services.validators import FieldValidator, ValidationError

# Allowed status transitions (target reachable from source).
TRANSITIONS = {
    "planned": {"active", "cancelled"},
    "active": {"completed", "cancelled"},
    "completed": {"active"},   # admin reopen only
    "cancelled": {"planned"},  # admin reopen only
}
LOCKED_STATUSES = {"completed", "cancelled"}


class ConflictError(Exception):
    """Raised when conflicts block a save (or require confirmation)."""

    def __init__(self, conflicts: list[Conflict], needs_confirmation: bool = False,
                 errors: dict | None = None) -> None:
        self.conflicts = conflicts
        self.needs_confirmation = needs_confirmation
        self.errors = errors or {}
        super().__init__("rotation conflicts")


class RotationService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)
        self.conflicts = RotationConflictService(self.repos)

    # -- scope ------------------------------------------------------------
    def _own_tutor_ids(self) -> set[int]:
        return {t.id for t in self.repos.tutors.active()
                if t.user_id == self.identity.user_id}

    def _own_sede_ids(self) -> set[int]:
        ids = set()
        for c in self.repos.sede_coordinators.active():
            if c.user_id == self.identity.user_id and c.sede_id:
                ids.add(c.sede_id)
        return ids

    def list_assignments(self, **filters) -> list[RotationAssignment]:
        role = self.identity.role_code
        if role == ROLE_STUDENT:
            mine = [s for s in self.repos.students.search(active=None)
                    if s.user_id == self.identity.user_id]
            filters["student_ids"] = {s.id for s in mine} or {-1}
        elif role == ROLE_TUTOR:
            filters["tutor_ids"] = self._own_tutor_ids() or {-1}
        elif role == ROLE_SEDE_COORDINATOR:
            filters["sede_ids"] = self._own_sede_ids() or {-1}
        return self.repos.assignments.search(**filters)

    def can_view(self, a: RotationAssignment) -> bool:
        role = self.identity.role_code
        if is_global_viewer(self.identity):
            return True
        if role == ROLE_SEDE_COORDINATOR:
            return a.sede_id in self._own_sede_ids()
        if role == ROLE_TUTOR:
            return a.tutor_id in self._own_tutor_ids()
        if role == ROLE_STUDENT:
            return a.student and a.student.user_id == self.identity.user_id
        return False

    def can_create(self, sede_id: int | None = None) -> bool:
        role = self.identity.role_code
        if is_global_viewer(self.identity):
            return True
        if role == ROLE_SEDE_COORDINATOR:
            return sede_id is None or sede_id in self._own_sede_ids()
        return False

    def can_manage(self, a: RotationAssignment) -> bool:
        """Whether the identity may change this assignment (status/tutor)."""
        if is_global_viewer(self.identity):
            return True
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            return a.sede_id in self._own_sede_ids()
        return False

    def get_for_view(self, assignment_id: int) -> RotationAssignment:
        a = self.repos.assignments.get_full(assignment_id)
        ensure(a is not None, "No tiene permiso para ver esta rotación.", "not_found")
        ensure(self.can_view(a),
              "No tiene permiso para ver esta rotación.", "rotation_scope_denied")
        return a

    # -- conflict preview -------------------------------------------------
    def preview(self, data: dict) -> list[Conflict]:
        return self.conflicts.check(self._to_input(data))

    def build_detail(self, assignment_id: int) -> dict:
        a = self.get_for_view(assignment_id)
        # Current live conflicts for this assignment (shown in the panel).
        conflicts = self.conflicts.check(RotationInput(
            student_id=a.student_id, rotation_type_id=a.rotation_type_id,
            sede_id=a.sede_id, period_id=a.period_id, tutor_id=a.tutor_id,
            start_date=a.start_date, end_date=a.end_date, assignment_id=a.id))
        evaluation = self.repos.evaluations.get_by_assignment(a.id)
        alerts = [al for al in self.repos.alerts.open_alerts()
                  if (al.related_entity_type == "rotation_assignment" and al.related_entity_id == a.id)
                  or (al.related_entity_type == "student" and al.related_entity_id == a.student_id)]
        audit_rows = [r for r in self.repos.audit_logs.recent(limit=300)
                      if r.entity_type == "rotation_assignment" and r.entity_id == a.id][:12]
        duration = (a.end_date - a.start_date).days if (a.start_date and a.end_date) else None
        available_tutors = [t for t in self.repos.tutors.by_sede(a.sede_id) if t.is_active]
        return {
            "a": a, "conflicts": conflicts, "evaluation": evaluation, "alerts": alerts,
            "audit_rows": audit_rows, "duration": duration,
            "available_tutors": available_tutors,
            "can_manage": self.can_manage(a), "is_admin": is_admin(self.identity),
            "locked": a.status in LOCKED_STATUSES,
            "allowed_targets": sorted(TRANSITIONS.get(a.status, set())),
        }

    # -- create -----------------------------------------------------------
    def create(self, data: dict, *, ip: str | None = None) -> RotationAssignment:
        clean = self._validate_basic(data)
        ensure(self.can_create(clean["sede_id"]),
               "No puede crear asignaciones para esta sede.", "create_rotation_denied")

        conflicts = self.conflicts.check(self._to_input(data))
        self._enforce_conflicts(conflicts, data, entity_id=None, ip=ip)

        a = RotationAssignment(
            student_id=clean["student_id"], rotation_type_id=clean["rotation_type_id"],
            sede_id=clean["sede_id"], period_id=clean["period_id"],
            tutor_id=clean["tutor_id"], start_date=clean["start_date"],
            end_date=clean["end_date"], status=clean["status"],
            notes=clean["notes"], override_reason=(data.get("override_reason") or None),
            created_by_user_id=self.identity.user_id,
            updated_by_user_id=self.identity.user_id,
        )
        self.repos.assignments.add(a)
        self.db.flush()
        self.audit.record(audit.CREATE_ROTATION_ASSIGNMENT, identity=self.identity,
                          entity_type="rotation_assignment", entity_id=a.id,
                          detail={"student_id": a.student_id, "status": a.status,
                                  "sede_id": a.sede_id}, ip_address=ip, commit=False)
        self.db.commit()
        AlertService(self.db).refresh_from_rules()
        return a

    # -- edit -------------------------------------------------------------
    def update(self, assignment_id: int, data: dict, *, ip: str | None = None) -> RotationAssignment:
        a = self.repos.assignments.get_full(assignment_id)
        ensure(a is not None, "Rotación no encontrada.", "not_found")
        ensure(self.can_manage(a), "No puede editar esta rotación.", "edit_rotation_denied")
        ensure(a.status not in LOCKED_STATUSES,
               "La rotación está bloqueada (completada/cancelada). Use reabrir.",
               "rotation_locked")

        before = {"tutor_id": a.tutor_id, "end_date": str(a.end_date), "status": a.status}
        if a.status == AssignmentStatus.PLANNED.value:
            # Full edit allowed.
            clean = self._validate_basic(data)
            conflicts = self.conflicts.check(self._to_input(data, exclude_id=a.id))
            self._enforce_conflicts(conflicts, data, entity_id=a.id, ip=ip)
            a.student_id = clean["student_id"]; a.rotation_type_id = clean["rotation_type_id"]
            a.sede_id = clean["sede_id"]; a.period_id = clean["period_id"]
            a.start_date = clean["start_date"]; a.end_date = clean["end_date"]
            a.tutor_id = clean["tutor_id"]; a.notes = clean["notes"]
        else:  # active — limited fields: tutor, end_date, notes
            v = FieldValidator()
            end = v.date("end_date", data.get("end_date"), "La fecha de término")
            if a.start_date and end and end <= a.start_date:
                v.add("end_date", "La fecha de término debe ser posterior al inicio.")
            v.raise_if_errors()
            tutor_id = int(data["tutor_id"]) if data.get("tutor_id") else None
            self._validate_tutor_for_sede(tutor_id, a.sede_id)
            a.end_date = end or a.end_date
            a.tutor_id = tutor_id
            a.notes = (data.get("notes") or "").strip() or None

        a.updated_by_user_id = self.identity.user_id
        self.db.flush()
        self.audit.record(audit.UPDATE_ROTATION_ASSIGNMENT, identity=self.identity,
                          entity_type="rotation_assignment", entity_id=a.id,
                          detail={"before": str(before), "after_status": a.status},
                          ip_address=ip, commit=False)
        self.db.commit()
        AlertService(self.db).refresh_from_rules()
        return a

    # -- status transitions ----------------------------------------------
    def transition(self, assignment_id: int, target: str, *, reason: str = "",
                   ip: str | None = None) -> RotationAssignment:
        a = self.repos.assignments.get_full(assignment_id)
        ensure(a is not None, "Rotación no encontrada.", "not_found")
        ensure(self.can_manage(a), "No puede modificar esta rotación.", "transition_denied")

        source = a.status
        if target not in TRANSITIONS.get(source, set()):
            raise ValidationError({"status": f"Transición no permitida: {source} → {target}."})

        reopening = source in LOCKED_STATUSES
        if reopening:
            ensure(is_admin(self.identity),
                   "Solo un administrador puede reabrir una rotación.", "reopen_denied")
            if not reason.strip():
                raise ValidationError({"reason": "Debe indicar un motivo para reabrir."})

        if target == "cancelled" and not reason.strip():
            raise ValidationError({"reason": "La cancelación requiere un motivo."})

        # University Coordinator cannot reopen (covered by is_admin check above).
        action = {
            "active": audit.ACTIVATE_ROTATION_ASSIGNMENT,
            "completed": audit.COMPLETE_ROTATION_ASSIGNMENT,
            "cancelled": audit.CANCEL_ROTATION_ASSIGNMENT,
        }.get(target)

        if reopening:
            a.reopened_reason = reason.strip()
            a.reopened_at = utcnow()
            action = audit.REOPEN_ROTATION_ASSIGNMENT

        a.status = target
        eval_created = False
        if target == "completed":
            a.completed_at = utcnow()
            _, eval_created = ensure_pending_evaluation(self.db, a)
        elif target == "cancelled":
            a.cancellation_reason = reason.strip()
            a.cancelled_at = utcnow()
        a.updated_by_user_id = self.identity.user_id
        self.db.flush()

        self.audit.record(action, identity=self.identity,
                          entity_type="rotation_assignment", entity_id=a.id,
                          detail={"from": source, "to": target},
                          reason=reason.strip() or None, ip_address=ip, commit=False)
        if eval_created:
            self.audit.record(audit.CREATE_PENDING_EVALUATION, identity=self.identity,
                              entity_type="evaluation", entity_id=a.evaluation.id if a.evaluation else None,
                              detail={"assignment_id": a.id}, ip_address=ip, commit=False)
        self.db.commit()
        AlertService(self.db).refresh_from_rules()
        return a

    # -- tutor assignment -------------------------------------------------
    def set_tutor(self, assignment_id: int, tutor_id: int | None, *,
                  ip: str | None = None) -> RotationAssignment:
        a = self.repos.assignments.get_full(assignment_id)
        ensure(a is not None, "Rotación no encontrada.", "not_found")
        ensure(self.can_manage(a), "No puede modificar esta rotación.", "assign_tutor_denied")
        ensure(a.status not in LOCKED_STATUSES,
               "No se puede cambiar el tutor de una rotación bloqueada. Reabra primero.",
               "rotation_locked")
        previous = a.tutor_id
        if tutor_id is not None:
            self._validate_tutor_for_sede(tutor_id, a.sede_id)
        a.tutor_id = tutor_id
        a.updated_by_user_id = self.identity.user_id
        self.db.flush()
        if tutor_id is None:
            action = audit.REMOVE_TUTOR
        elif previous is None:
            action = audit.ASSIGN_TUTOR
        else:
            action = audit.REASSIGN_TUTOR_ROTATION
        self.audit.record(action, identity=self.identity, entity_type="rotation_assignment",
                          entity_id=a.id, detail={"previous_tutor": previous, "new_tutor": tutor_id},
                          ip_address=ip, commit=False)
        self.db.commit()
        AlertService(self.db).refresh_from_rules()  # creates missing-tutor alert if removed
        return a

    # -- helpers ----------------------------------------------------------
    def _validate_tutor_for_sede(self, tutor_id: int | None, sede_id: int) -> None:
        if tutor_id is None:
            return
        tutor = self.repos.tutors.get(tutor_id)
        if tutor is None or tutor.is_deleted or not tutor.is_active:
            raise ValidationError({"tutor_id": "El tutor debe existir y estar activo."})
        if tutor.sede_id != sede_id:
            raise ValidationError({"tutor_id": "El tutor debe pertenecer a la sede de la rotación."})

    def _validate_basic(self, data: dict) -> dict:
        v = FieldValidator()
        student_id = v.int_field("student_id", data.get("student_id"), "El interno")
        if not student_id:
            v.add("student_id", "El interno es obligatorio.")
        rotation_type_id = v.int_field("rotation_type_id", data.get("rotation_type_id"), "La rotación")
        if not rotation_type_id:
            v.add("rotation_type_id", "La rotación es obligatoria.")
        sede_id = v.int_field("sede_id", data.get("sede_id"), "La sede")
        if not sede_id:
            v.add("sede_id", "La sede es obligatoria.")
        period_id = v.int_field("period_id", data.get("period_id"), "El periodo")
        if not period_id:
            v.add("period_id", "El periodo es obligatorio.")
        start = v.date("start_date", data.get("start_date"), "La fecha de inicio")
        end = v.date("end_date", data.get("end_date"), "La fecha de término")
        if start and end and end <= start:
            v.add("end_date", "La fecha de término debe ser posterior al inicio.")
        status = v.choice("status", data.get("status"),
                          {AssignmentStatus.PLANNED.value, AssignmentStatus.ACTIVE.value},
                          "El estado") or AssignmentStatus.PLANNED.value
        tutor_id = v.int_field("tutor_id", data.get("tutor_id"), "El tutor")
        v.raise_if_errors()
        return {"student_id": student_id, "rotation_type_id": rotation_type_id,
                "sede_id": sede_id, "period_id": period_id, "start_date": start,
                "end_date": end, "status": status, "tutor_id": tutor_id,
                "notes": (data.get("notes") or "").strip() or None}

    def _to_input(self, data: dict, exclude_id: int | None = None) -> RotationInput:
        def _int(key):
            return int(data[key]) if data.get(key) else None
        def _date(key):
            v = (data.get(key) or "").strip()
            if not v:
                return None
            try:
                return date.fromisoformat(v)
            except ValueError:
                return None
        return RotationInput(
            student_id=_int("student_id"), rotation_type_id=_int("rotation_type_id"),
            sede_id=_int("sede_id"), period_id=_int("period_id"), tutor_id=_int("tutor_id"),
            start_date=_date("start_date"), end_date=_date("end_date"),
            assignment_id=exclude_id)

    def _enforce_conflicts(self, conflicts: list[Conflict], data: dict,
                           *, entity_id: int | None, ip: str | None) -> None:
        blocking_hard = [c for c in conflicts if c.blocking and not c.can_override]
        blocking_override = [c for c in conflicts if c.blocking and c.can_override]
        warnings = [c for c in conflicts if not c.blocking]

        if blocking_hard:
            self.audit.record(audit.CONFLICT_VALIDATION_FAILED, identity=self.identity,
                              entity_type="rotation_assignment", entity_id=entity_id,
                              detail={"codes": ",".join(c.code for c in blocking_hard)},
                              ip_address=ip)
            raise ConflictError(conflicts)

        if blocking_override:
            override_reason = (data.get("override_reason") or "").strip()
            if not (is_admin(self.identity) and override_reason):
                self.audit.record(audit.CONFLICT_VALIDATION_FAILED, identity=self.identity,
                                  entity_type="rotation_assignment", entity_id=entity_id,
                                  detail={"codes": ",".join(c.code for c in blocking_override),
                                          "override_available": True}, ip_address=ip)
                raise ConflictError(conflicts)
            # Admin override with reason — record it.
            self.audit.record(audit.OVERRIDE_ROTATION_CONFLICT, identity=self.identity,
                              entity_type="rotation_assignment", entity_id=entity_id,
                              detail={"codes": ",".join(c.code for c in blocking_override)},
                              reason=override_reason, ip_address=ip, commit=False)

        # Warnings require an explicit confirmation, but never hard-block.
        if warnings and data.get("confirm") != "1":
            raise ConflictError(conflicts, needs_confirmation=True)

    # -- form options -----------------------------------------------------
    def form_options(self) -> dict:
        sedes = self.repos.sedes.active()
        if self.identity.role_code == ROLE_SEDE_COORDINATOR and not is_global_viewer(self.identity):
            allowed = self._own_sede_ids()
            sedes = [s for s in sedes if s.id in allowed]
        return {
            "students": [(s.id, f"{s.student_code} · {s.full_name}")
                         for s in self.repos.students.active()],
            "rotation_types": [(r.id, r.name) for r in self.repos.rotation_types.list()],
            "sedes": [(s.id, s.short_name or s.name) for s in sedes],
            "periods": [(p.id, p.name) for p in self.repos.periods.ordered()],
            "tutors": [(t.id, f"{t.user.full_name} · {t.sede.short_name if t.sede else ''}")
                       for t in self.repos.tutors.active()],
            "statuses": [("planned", "Planificada"), ("active", "Activa")],
        }
