"""Student management service — business logic for the intern CRUD workflows.

Enforces validation (D), uniqueness, the ~365-day duration rule, record-level
scope (A), and writes audit entries (J). Routes are thin controllers over this.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.authorization import (
    can_edit_student,
    can_view_student,
    ensure,
    is_admin,
    is_global_viewer,
)
from app.models.base import InstitutionCode, StudentCycle
from app.models.student import Student
from app.models.user import ROLE_SEDE_COORDINATOR, ROLE_STUDENT, ROLE_TUTOR
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import FieldValidator, ValidationError

# Duration tolerance: internship should be ~365 days. Outside this band we warn
# but still allow an authorized save with a recorded reason.
DURATION_MIN_DAYS = 300
DURATION_MAX_DAYS = 420

VALID_CYCLES = {c.value for c in StudentCycle}
VALID_PROFILE = {"complete", "incomplete"}


class StudentService:
    """CRUD + scope + audit for intern students."""

    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    # -- scope helpers ----------------------------------------------------
    def _scope_sede_ids(self) -> set[int] | None:
        """Sede ids the current identity is limited to, or None for global."""
        if is_global_viewer(self.identity):
            return None
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            ids = set()
            for c in self.repos.sede_coordinators.active():
                if c.user_id == self.identity.user_id and c.sede_id:
                    ids.add(c.sede_id)
            return ids
        return set()  # tutors/students handled separately in listing

    # -- listing ----------------------------------------------------------
    def list_students(self, **filters) -> list[Student]:
        """Return students visible to the current identity, filtered."""
        role = self.identity.role_code
        if role == ROLE_STUDENT:
            # A student only ever sees themselves.
            me = self.repos.students.search(active=None)
            return [s for s in me if s.user_id == self.identity.user_id]
        if role == ROLE_TUTOR:
            tutor_ids = {t.id for t in self.repos.tutors.active()
                         if t.user_id == self.identity.user_id}
            student_ids = {
                a.student_id for a in self.repos.assignments.all_with_relations()
                if a.tutor_id in tutor_ids
            }
            results = self.repos.students.search(**filters)
            return [s for s in results if s.id in student_ids]
        # Admin / University see all; Sede Coordinator limited to their sede(s).
        scope = self._scope_sede_ids()
        if scope is not None:
            filters["sede_ids"] = scope
        return self.repos.students.search(**filters)

    # -- detail -----------------------------------------------------------
    def get_for_view(self, student_id: int) -> Student:
        student = self.repos.students.get_full(student_id)
        ensure(student is not None, "Interno no encontrado.", "not_found")
        ensure(can_view_student(self.identity, student, self.repos),
               "No puede ver este interno.", "student_scope_denied")
        return student

    def build_detail(self, student_id: int) -> dict:
        """Assemble the student detail view-model (timeline, tutor, alerts...)."""
        student = self.get_for_view(student_id)
        assignments = sorted(
            [a for a in student.rotation_assignments if not a.is_deleted],
            key=lambda a: (a.start_date or date.min),
        )
        today = date.today()
        current = [a for a in assignments if a.status == "active"]
        upcoming = [a for a in assignments if a.status == "planned"
                    and (a.start_date or date.max) >= today]
        previous = [a for a in assignments if a.status in ("completed", "cancelled")]

        # Related open alerts.
        alerts = [a for a in self.repos.alerts.open_alerts()
                  if a.related_entity_type == "student" and a.related_entity_id == student.id]

        # Activity progress rollup.
        acts = [a for a in student.activities]
        verified = sum(a.performed_count for a in acts if a.verification_status == "verified")
        pending = sum(1 for a in acts if a.verification_status == "pending")

        # Audit history summary for this student.
        audit_rows = [r for r in self.repos.audit_logs.recent(limit=200)
                      if r.entity_type == "student" and r.entity_id == student.id][:10]

        return {
            "student": student,
            "assignments": assignments,
            "current": current,
            "upcoming": upcoming,
            "previous": previous,
            "alerts": alerts,
            "evaluations": [e for e in student.evaluations if not e.is_deleted],
            "activity_verified": verified,
            "activity_pending": pending,
            "audit_rows": audit_rows,
            "can_edit": can_edit_student(self.identity, student, self.repos),
            "can_delete": is_admin(self.identity),
        }

    # -- create / update --------------------------------------------------
    def _validate(self, data: dict, *, existing: Student | None) -> tuple[dict, list[str]]:
        """Validate and normalize form data. Returns (clean, warnings)."""
        v = FieldValidator()
        warnings: list[str] = []

        code = v.required("student_code", data.get("student_code"), "El código")
        full_name = v.required("full_name", data.get("full_name"), "El nombre completo")
        email = v.email("email", data.get("email"))
        document_id = (data.get("document_id") or "").strip() or None
        phone = (data.get("phone") or "").strip() or None
        cycle = v.choice("cycle", data.get("cycle"), VALID_CYCLES, "El ciclo")
        if not cycle:
            v.add("cycle", "El ciclo es obligatorio (13 o 14).")
        profile_status = v.choice("profile_status", data.get("profile_status"),
                                  VALID_PROFILE, "El estado de perfil") or "complete"
        institution_id = v.int_field("institution_type_id", data.get("institution_type_id"),
                                     "La institución")
        sede_id = v.int_field("sede_id", data.get("sede_id"), "La sede")
        start = v.date("internship_start", data.get("internship_start"), "La fecha de inicio")
        end = v.date("internship_end", data.get("internship_end"), "La fecha de término")

        # Uniqueness checks.
        if code:
            dup = self.repos.students.get_by_code(code)
            if dup and (existing is None or dup.id != existing.id):
                v.add("student_code", "El código de interno ya existe.")
        if email:
            dup = self.repos.students.get_by_email(email)
            if dup and (existing is None or dup.id != existing.id):
                v.add("email", "El correo ya está registrado.")
        if document_id:
            dup = self.repos.students.get_by_document(document_id)
            if dup and (existing is None or dup.id != existing.id):
                v.add("document_id", "El documento ya está registrado.")

        # Date ordering + duration band.
        if start and end:
            if end <= start:
                v.add("internship_end", "La fecha de término debe ser posterior al inicio.")
            else:
                duration = (end - start).days
                if not (DURATION_MIN_DAYS <= duration <= DURATION_MAX_DAYS):
                    warnings.append(
                        f"La duración del internado es de {duration} días "
                        f"(lo normal es ~365). Puede guardar registrando el motivo."
                    )

        v.raise_if_errors()
        clean = {
            "student_code": code, "full_name": full_name, "email": email,
            "document_id": document_id, "phone": phone, "cycle": cycle,
            "profile_status": profile_status, "institution_type_id": institution_id,
            "sede_id": sede_id, "internship_start": start, "internship_end": end,
        }
        return clean, warnings

    def create(self, data: dict, ip: str | None = None,
               override_reason: str | None = None) -> Student:
        ensure(is_global_viewer(self.identity) or self.identity.role_code == ROLE_SEDE_COORDINATOR,
               "No puede crear internos.", "create_student_denied")
        clean, warnings = self._validate(data, existing=None)
        if warnings and not override_reason:
            raise ValidationError({"internship_end": " ".join(warnings)
                                   + " Indique un motivo para continuar."})
        student = Student(**clean)
        self.repos.students.add(student)
        self.db.flush()
        self.audit.record(audit.CREATE_STUDENT, identity=self.identity,
                          entity_type="student", entity_id=student.id,
                          detail={"student_code": student.student_code},
                          reason=override_reason, ip_address=ip, commit=False)
        self.db.commit()
        return student

    def update(self, student_id: int, data: dict, ip: str | None = None,
               override_reason: str | None = None) -> Student:
        student = self.repos.students.get_full(student_id)
        ensure(student is not None, "Interno no encontrado.", "not_found")
        ensure(can_edit_student(self.identity, student, self.repos),
               "No puede editar este interno.", "edit_student_denied")

        # Sede Coordinators may edit only limited operational fields.
        clean, warnings = self._validate(data, existing=student)
        if warnings and not override_reason:
            raise ValidationError({"internship_end": " ".join(warnings)
                                   + " Indique un motivo para continuar."})
        if self.identity.role_code == ROLE_SEDE_COORDINATOR and not is_global_viewer(self.identity):
            # Restrict mutable fields for sede coordinators.
            for field in ("phone", "profile_status"):
                setattr(student, field, clean[field])
        else:
            for field, value in clean.items():
                setattr(student, field, value)
        self.db.flush()
        self.audit.record(audit.UPDATE_STUDENT, identity=self.identity,
                          entity_type="student", entity_id=student.id,
                          detail={"student_code": student.student_code},
                          reason=override_reason, ip_address=ip, commit=False)
        self.db.commit()
        return student

    def set_active(self, student_id: int, active: bool, ip: str | None = None) -> Student:
        student = self.repos.students.get_full(student_id)
        ensure(student is not None, "Interno no encontrado.", "not_found")
        ensure(can_edit_student(self.identity, student, self.repos),
               "No puede modificar este interno.", "toggle_student_denied")
        student.is_active = active
        self.db.flush()
        self.audit.record(audit.DEACTIVATE_STUDENT if not active else audit.UPDATE_STUDENT,
                          identity=self.identity, entity_type="student", entity_id=student.id,
                          detail={"is_active": active}, ip_address=ip, commit=False)
        self.db.commit()
        return student

    def soft_delete(self, student_id: int, reason: str, ip: str | None = None) -> None:
        ensure(is_admin(self.identity), "Solo un administrador puede eliminar internos.",
               "delete_student_denied")
        student = self.repos.students.get_full(student_id)
        ensure(student is not None, "Interno no encontrado.", "not_found")
        if not (reason or "").strip():
            raise ValidationError({"reason": "Debe indicar un motivo para eliminar."})
        student.is_deleted = True
        student.is_active = False
        from app.models.base import utcnow
        student.deleted_at = utcnow()
        self.db.flush()
        self.audit.record(audit.DEACTIVATE_STUDENT, identity=self.identity,
                          entity_type="student", entity_id=student.id,
                          detail={"soft_deleted": True}, reason=reason.strip(),
                          ip_address=ip, commit=False)
        self.db.commit()

    # -- form option data -------------------------------------------------
    def form_options(self) -> dict:
        return {
            "institutions": [(i.id, i.name) for i in self.repos.institution_types.list()],
            "sedes": [(s.id, s.short_name or s.name) for s in self.repos.sedes.active()],
            "cycles": [(c.value, f"Ciclo {c.value}") for c in StudentCycle],
            "profile_statuses": [("complete", "Completo"), ("incomplete", "Incompleto")],
            "institution_codes": [(c.value, c.value) for c in InstitutionCode],
        }
