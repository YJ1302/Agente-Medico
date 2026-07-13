"""Sede Coordinator and Tutor management services (Batch 2A).

Both roles are backed by a ``User`` account (role ``sede_coordinator`` /
``tutor``) plus a profile row, created atomically in a single transaction.
Includes the principal-coordinator replacement workflow, the configurable tutor
workload indicator, and reassignment/deactivation guards. Passwords are hashed
and never returned or logged.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin, is_global_viewer
from app.config import settings
from app.models.base import utcnow
from app.models.organization import SedeCoordinatorProfile, TutorProfile
from app.models.user import ROLE_SEDE_COORDINATOR, ROLE_TUTOR, User
from app.repositories.repositories import RepositoryBundle
from app.security import hash_password
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import FieldValidator, ValidationError


@dataclass
class Workload:
    """Tutor workload indicator relative to the configurable threshold."""

    count: int
    threshold: int
    level: str  # 'normal' | 'near' | 'above'
    label: str


def compute_workload(count: int, threshold: int | None = None) -> Workload:
    threshold = threshold or settings.tutor_assignment_warning_threshold
    if count >= threshold:
        return Workload(count, threshold, "above", "Sobre el umbral")
    if count >= threshold - 1:
        return Workload(count, threshold, "near", "Cerca del umbral")
    return Workload(count, threshold, "normal", "Normal")


class _StaffBase:
    """Shared helpers for coordinator/tutor services."""

    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    def _scope_sede_ids(self) -> set[int] | None:
        if is_global_viewer(self.identity):
            return None
        ids: set[int] = set()
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            for c in self.repos.sede_coordinators.active():
                if c.user_id == self.identity.user_id and c.sede_id:
                    ids.add(c.sede_id)
        return ids

    def _validate_sede(self, v: FieldValidator, sede_id: int | None) -> None:
        if not sede_id:
            v.add("sede_id", "La sede es obligatoria.")
            return
        sede = self.repos.sedes.get(sede_id)
        if sede is None or sede.is_deleted or not sede.is_active:
            v.add("sede_id", "La sede debe existir y estar activa.")

    def _create_user(self, *, full_name: str, email: str, phone: str | None,
                     role_code: str, password: str | None) -> tuple[User, str]:
        """Create a hashed-password user account. Returns (user, generated_pwd?)."""
        role = self.repos.roles.get_by_code(role_code)
        ensure(role is not None, "Rol no configurado.", "role_missing")
        generated = ""
        if not (password or "").strip():
            password = "Demo123!" if settings.demo_mode else secrets.token_urlsafe(9)
            generated = password
        user = User(email=email, full_name=full_name, phone=phone,
                    hashed_password=hash_password(password), role_id=role.id)
        self.repos.users.add(user)
        self.db.flush()
        return user, generated

    def _email_taken(self, email: str) -> bool:
        return self.repos.users.get_by_email(email) is not None


class CoordinatorService(_StaffBase):
    """CRUD + assignment/replacement workflow for sede coordinators."""

    def can_manage(self) -> bool:
        return is_global_viewer(self.identity)

    def can_view(self, coord: SedeCoordinatorProfile) -> bool:
        scope = self._scope_sede_ids()
        return scope is None or coord.sede_id in scope

    def list_coordinators(self, **filters) -> list[SedeCoordinatorProfile]:
        scope = self._scope_sede_ids()
        if scope is not None:
            filters["sede_ids"] = scope
        return self.repos.sede_coordinators.search(**filters)

    def get_for_view(self, coord_id: int) -> SedeCoordinatorProfile:
        coord = self.repos.sede_coordinators.get_full(coord_id)
        ensure(coord is not None, "Coordinador no encontrado.", "not_found")
        ensure(self.can_view(coord), "No puede ver este coordinador.", "coord_scope_denied")
        return coord

    def build_detail(self, coord_id: int) -> dict:
        coord = self.get_for_view(coord_id)
        sede = coord.sede
        tutors = self.repos.tutors.by_sede(sede.id) if sede else []
        students = [s for s in self.repos.students.active() if s.sede_id == (sede.id if sede else None)]
        active_rotations = [a for a in self.repos.assignments.all_with_relations()
                            if sede and a.sede_id == sede.id and a.status == "active"]
        pending = [e for e in self.repos.evaluations.pending()
                   if e.assignment and sede and e.assignment.sede_id == sede.id]
        alerts = [a for a in self.repos.alerts.open_alerts()
                  if sede and a.related_entity_type == "sede" and a.related_entity_id == sede.id]
        audit_rows = [r for r in self.repos.audit_logs.recent(limit=200)
                      if r.entity_type == "sede_coordinator" and r.entity_id == coord.id][:10]
        return {"coord": coord, "sede": sede, "tutors": tutors, "students": students,
                "active_rotations": active_rotations, "pending_eval_count": len(pending),
                "alerts": alerts, "audit_rows": audit_rows,
                "can_manage": self.can_manage(), "can_deactivate": self.can_manage()}

    def _validate(self, data: dict, *, existing: SedeCoordinatorProfile | None) -> dict:
        v = FieldValidator()
        full_name = v.required("full_name", data.get("full_name"), "El nombre")
        email = v.email("email", data.get("email"))
        if not email:
            v.add("email", "El correo es obligatorio.")
        elif existing is None or email.lower() != (existing.user.email.lower() if existing else ""):
            if self._email_taken(email):
                v.add("email", "El correo ya está registrado.")
        sede_id = v.int_field("sede_id", data.get("sede_id"), "La sede")
        self._validate_sede(v, sede_id)
        v.raise_if_errors()
        return {"full_name": full_name, "email": email, "sede_id": sede_id,
                "phone": (data.get("phone") or "").strip() or None,
                "specialty": (data.get("specialty") or "").strip() or None,
                "office_phone": (data.get("office_phone") or "").strip() or None}

    def create(self, data: dict, *, replace: bool = False, ip: str | None = None):
        ensure(self.can_manage(), "No puede crear coordinadores.", "create_coord_denied")
        clean = self._validate(data, existing=None)
        # Principal replacement guard.
        current = self.repos.sede_coordinators.active_principal_for_sede(clean["sede_id"])
        if current and not replace:
            raise ValidationError({
                "sede_id": "La sede ya tiene un coordinador principal activo "
                           f"({current.user.full_name}). Marque «reemplazar» para continuar."
            })
        user, generated = self._create_user(
            full_name=clean["full_name"], email=clean["email"], phone=clean["phone"],
            role_code=ROLE_SEDE_COORDINATOR, password=data.get("password"))
        coord = SedeCoordinatorProfile(
            user_id=user.id, sede_id=clean["sede_id"], specialty=clean["specialty"],
            office_phone=clean["office_phone"], is_principal=True, is_active=True)
        self.repos.sede_coordinators.add(coord)
        self.db.flush()
        if current and replace:
            current.is_active = False
            self.audit.record(audit.REPLACE_SEDE_COORDINATOR, identity=self.identity,
                              entity_type="sede_coordinator", entity_id=current.id,
                              detail={"replaced_by": coord.id, "sede_id": clean["sede_id"]},
                              reason="Reemplazo de coordinador principal", ip_address=ip,
                              commit=False)
        self.audit.record(audit.CREATE_SEDE_COORDINATOR, identity=self.identity,
                          entity_type="sede_coordinator", entity_id=coord.id,
                          detail={"email": user.email, "sede_id": clean["sede_id"]},
                          ip_address=ip, commit=False)
        self.db.commit()
        return coord, generated

    def update(self, coord_id: int, data: dict, ip: str | None = None):
        coord = self.repos.sede_coordinators.get_full(coord_id)
        ensure(coord is not None, "Coordinador no encontrado.", "not_found")
        ensure(self.can_manage(), "No puede editar coordinadores.", "edit_coord_denied")
        clean = self._validate(data, existing=coord)
        reassigned = clean["sede_id"] != coord.sede_id
        if reassigned:
            # Reassigning to a sede that already has an active principal needs care.
            other = self.repos.sede_coordinators.active_principal_for_sede(clean["sede_id"])
            if other and other.id != coord.id and data.get("replace") != "1":
                raise ValidationError({
                    "sede_id": "La sede destino ya tiene coordinador principal activo. "
                               "Marque «reemplazar» para continuar."})
        coord.user.full_name = clean["full_name"]
        coord.user.email = clean["email"]
        coord.user.phone = clean["phone"]
        coord.specialty = clean["specialty"]
        coord.office_phone = clean["office_phone"]
        coord.sede_id = clean["sede_id"]
        self.db.flush()
        action = audit.REASSIGN_SEDE_COORDINATOR if reassigned else audit.UPDATE_SEDE_COORDINATOR
        self.audit.record(action, identity=self.identity, entity_type="sede_coordinator",
                          entity_id=coord.id, detail={"sede_id": clean["sede_id"]},
                          reason="Reasignación de sede" if reassigned else None,
                          ip_address=ip, commit=False)
        self.db.commit()
        return coord

    def set_active(self, coord_id: int, active: bool, ip: str | None = None):
        coord = self.repos.sede_coordinators.get_full(coord_id)
        ensure(coord is not None, "Coordinador no encontrado.", "not_found")
        ensure(self.can_manage(), "No puede modificar coordinadores.", "toggle_coord_denied")
        coord.is_active = active
        coord.user.is_active = active
        self.db.flush()
        self.audit.record(audit.REACTIVATE_SEDE_COORDINATOR if active else audit.DEACTIVATE_SEDE_COORDINATOR,
                          identity=self.identity, entity_type="sede_coordinator",
                          entity_id=coord.id, ip_address=ip, commit=False)
        self.db.commit()
        return coord

    def form_options(self) -> dict:
        return {"sedes": [(s.id, s.short_name or s.name) for s in self.repos.sedes.active()]}


class TutorService(_StaffBase):
    """CRUD + reassignment/deactivation guards + workload for tutors."""

    def can_manage(self) -> bool:
        return is_global_viewer(self.identity)

    def can_manage_sede_fields(self, tutor: TutorProfile) -> bool:
        """Sede coordinators may update limited contact fields for own-sede tutors."""
        if self.can_manage():
            return True
        scope = self._scope_sede_ids()
        return scope is not None and tutor.sede_id in scope

    def can_view(self, tutor: TutorProfile) -> bool:
        if is_global_viewer(self.identity):
            return True
        # A tutor may view only their own profile (checked before sede scope,
        # since _scope_sede_ids returns an empty set for the tutor role).
        if self.identity.role_code == ROLE_TUTOR:
            return tutor.user_id == self.identity.user_id
        scope = self._scope_sede_ids()
        if scope is not None:  # sede coordinator
            return tutor.sede_id in scope
        return False

    def list_tutors(self, *, workload: str | None = None,
                    has_assignments: str | None = None, **filters) -> list[TutorProfile]:
        scope = self._scope_sede_ids()
        if scope is not None:
            filters["sede_ids"] = scope
        if self.identity.role_code == ROLE_TUTOR:
            filters["sede_ids"] = set()  # a tutor manages nobody; only sees self below
        tutors = self.repos.tutors.search(**filters)
        if self.identity.role_code == ROLE_TUTOR:
            tutors = [t for t in self.repos.tutors.active() if t.user_id == self.identity.user_id]
        rows = []
        for t in tutors:
            wl = compute_workload(self.repos.tutors.workload_count(t.id))
            if has_assignments == "1" and wl.count == 0:
                continue
            if has_assignments == "0" and wl.count > 0:
                continue
            if workload and wl.level != workload:
                continue
            rows.append((t, wl))
        return rows

    def get_for_view(self, tutor_id: int) -> TutorProfile:
        tutor = self.repos.tutors.get_full(tutor_id)
        ensure(tutor is not None, "Tutor no encontrado.", "not_found")
        ensure(self.can_view(tutor), "No puede ver este tutor.", "tutor_scope_denied")
        return tutor

    def build_detail(self, tutor_id: int) -> dict:
        tutor = self.get_for_view(tutor_id)
        assignments = [a for a in tutor.rotation_assignments if not a.is_deleted]
        active = [a for a in assignments if a.status in ("active", "planned")]
        students = {a.student_id: a.student for a in assignments if a.student}
        pending = [e for e in self.repos.evaluations.pending() if e.tutor_id == tutor.id]
        wl = compute_workload(self.repos.tutors.workload_count(tutor.id))
        alerts = [a for a in self.repos.alerts.open_alerts()
                  if a.related_entity_type == "rotation_assignment"
                  and a.related_entity_id in {x.id for x in assignments}]
        audit_rows = [r for r in self.repos.audit_logs.recent(limit=200)
                      if r.entity_type == "tutor" and r.entity_id == tutor.id][:10]
        return {"tutor": tutor, "assignments": assignments, "active_assignments": active,
                "students": list(students.values()), "pending_eval_count": len(pending),
                "workload": wl, "alerts": alerts, "audit_rows": audit_rows,
                "can_manage": self.can_manage(),
                "can_edit_fields": self.can_manage_sede_fields(tutor)}

    def _validate(self, data: dict, *, existing: TutorProfile | None) -> dict:
        v = FieldValidator()
        full_name = v.required("full_name", data.get("full_name"), "El nombre")
        email = v.email("email", data.get("email"))
        if not email:
            v.add("email", "El correo es obligatorio.")
        elif existing is None or email.lower() != (existing.user.email.lower() if existing else ""):
            if self._email_taken(email):
                v.add("email", "El correo ya está registrado.")
        sede_id = v.int_field("sede_id", data.get("sede_id"), "La sede")
        self._validate_sede(v, sede_id)
        v.raise_if_errors()
        return {"full_name": full_name, "email": email, "sede_id": sede_id,
                "phone": (data.get("phone") or "").strip() or None,
                "specialty": (data.get("specialty") or "").strip() or None,
                "service": (data.get("service") or "").strip() or None,
                "contact_phone": (data.get("contact_phone") or "").strip() or None}

    def create(self, data: dict, ip: str | None = None):
        ensure(self.can_manage(), "No puede crear tutores.", "create_tutor_denied")
        clean = self._validate(data, existing=None)
        user, generated = self._create_user(
            full_name=clean["full_name"], email=clean["email"], phone=clean["phone"],
            role_code=ROLE_TUTOR, password=data.get("password"))
        tutor = TutorProfile(
            user_id=user.id, sede_id=clean["sede_id"], specialty=clean["specialty"],
            service=clean["service"], contact_phone=clean["contact_phone"], is_active=True)
        self.repos.tutors.add(tutor)
        self.db.flush()
        self.audit.record(audit.CREATE_TUTOR, identity=self.identity, entity_type="tutor",
                          entity_id=tutor.id, detail={"email": user.email, "sede_id": clean["sede_id"]},
                          ip_address=ip, commit=False)
        self.db.commit()
        return tutor, generated

    def update(self, tutor_id: int, data: dict, ip: str | None = None):
        tutor = self.repos.tutors.get_full(tutor_id)
        ensure(tutor is not None, "Tutor no encontrado.", "not_found")
        ensure(self.can_manage_sede_fields(tutor), "No puede editar este tutor.",
               "edit_tutor_denied")
        # Sede coordinators may only touch limited contact fields.
        if not self.can_manage():
            tutor.contact_phone = (data.get("contact_phone") or "").strip() or None
            tutor.service = (data.get("service") or "").strip() or tutor.service
            self.db.flush()
            self.audit.record(audit.UPDATE_TUTOR, identity=self.identity, entity_type="tutor",
                              entity_id=tutor.id, detail={"limited": True}, ip_address=ip,
                              commit=False)
            self.db.commit()
            return tutor

        clean = self._validate(data, existing=tutor)
        reassigned = clean["sede_id"] != tutor.sede_id
        if reassigned:
            # Block reassignment while active assignments still belong to the old sede.
            active_old = [a for a in tutor.rotation_assignments
                          if not a.is_deleted and a.sede_id == tutor.sede_id
                          and a.status in ("active", "planned")]
            if active_old:
                raise ValidationError({
                    "sede_id": f"No se puede reasignar: el tutor tiene {len(active_old)} "
                               "asignación(es) activa(s)/planificada(s) en la sede actual."})
        tutor.user.full_name = clean["full_name"]
        tutor.user.email = clean["email"]
        tutor.user.phone = clean["phone"]
        tutor.specialty = clean["specialty"]
        tutor.service = clean["service"]
        tutor.contact_phone = clean["contact_phone"]
        tutor.sede_id = clean["sede_id"]
        self.db.flush()
        action = audit.REASSIGN_TUTOR if reassigned else audit.UPDATE_TUTOR
        self.audit.record(action, identity=self.identity, entity_type="tutor",
                          entity_id=tutor.id, detail={"sede_id": clean["sede_id"]},
                          reason="Reasignación de sede" if reassigned else None,
                          ip_address=ip, commit=False)
        self.db.commit()
        return tutor

    def set_active(self, tutor_id: int, active: bool, *, force: bool = False,
                   reason: str | None = None, ip: str | None = None):
        tutor = self.repos.tutors.get_full(tutor_id)
        ensure(tutor is not None, "Tutor no encontrado.", "not_found")
        ensure(self.can_manage(), "No puede modificar tutores.", "toggle_tutor_denied")
        if active:
            tutor.is_active = True
            tutor.user.is_active = True
            self.db.flush()
            self.audit.record(audit.REACTIVATE_TUTOR, identity=self.identity,
                              entity_type="tutor", entity_id=tutor.id, ip_address=ip, commit=False)
            self.db.commit()
            return tutor
        active_count = self.repos.tutors.workload_count(tutor.id)
        if active_count > 0 and not force:
            raise ValidationError({
                "tutor": f"No se puede desactivar: el tutor tiene {active_count} "
                         "asignación(es) activa(s)/planificada(s). Un administrador puede "
                         "forzar la desactivación con un motivo."})
        if active_count > 0 and force:
            ensure(is_admin(self.identity),
                   "Solo un administrador puede forzar la desactivación.",
                   "force_deactivate_tutor_denied")
            if not (reason or "").strip():
                raise ValidationError({"reason": "Debe indicar un motivo para forzar."})
            tutor.is_active = False
            tutor.user.is_active = False
            self.db.flush()
            self.audit.record(audit.FORCE_DEACTIVATE_TUTOR, identity=self.identity,
                              entity_type="tutor", entity_id=tutor.id,
                              detail={"active_assignments": active_count},
                              reason=reason.strip(), ip_address=ip, commit=False)
            self.db.commit()
            return tutor
        tutor.is_active = False
        tutor.user.is_active = False
        self.db.flush()
        self.audit.record(audit.DEACTIVATE_TUTOR, identity=self.identity,
                          entity_type="tutor", entity_id=tutor.id, ip_address=ip, commit=False)
        self.db.commit()
        return tutor

    def form_options(self) -> dict:
        return {"sedes": [(s.id, s.short_name or s.name) for s in self.repos.sedes.active()]}
