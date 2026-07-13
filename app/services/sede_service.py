"""Sede management service (Batch 2A).

Handles CRUD, detail summaries, the deactivation guard (blocked when active or
planned rotations exist), administrator forced deactivation with a mandatory
reason, and administrator soft-delete. Enforces role scope and writes audit
entries for every mutation.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin, is_global_viewer
from app.models.base import InstitutionCode, utcnow
from app.models.organization import Sede
from app.models.user import ROLE_SEDE_COORDINATOR
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import FieldValidator, ValidationError

VALID_SEDE_TYPES = {"hospital", "health_center"}
SEDE_TYPE_LABELS = {"hospital": "Hospital", "health_center": "Centro de salud"}


class SedeService:
    """Business logic for teaching sites (sedes)."""

    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    # -- scope ------------------------------------------------------------
    def _scope_sede_ids(self) -> set[int] | None:
        """Sede ids the identity is limited to, or None for global viewers."""
        if is_global_viewer(self.identity):
            return None
        ids: set[int] = set()
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            for c in self.repos.sede_coordinators.active():
                if c.user_id == self.identity.user_id and c.sede_id:
                    ids.add(c.sede_id)
        return ids

    def can_view(self, sede: Sede) -> bool:
        scope = self._scope_sede_ids()
        return scope is None or sede.id in scope

    def can_manage(self) -> bool:
        """Create/edit rights (admin or university coordinator)."""
        return is_global_viewer(self.identity)

    # -- listing / detail -------------------------------------------------
    def list_sedes(self, *, has_coordinator: str | None = None, **filters) -> list[Sede]:
        scope = self._scope_sede_ids()
        if scope is not None:
            filters["sede_ids"] = scope
        sedes = self.repos.sedes.search(**filters)
        if has_coordinator in ("1", "0"):
            want = has_coordinator == "1"
            sedes = [
                s for s in sedes
                if bool(self.repos.sede_coordinators.active_principal_for_sede(s.id)) == want
            ]
        return sedes

    def get_for_view(self, sede_id: int) -> Sede:
        sede = self.repos.sedes.get_full(sede_id)
        ensure(sede is not None and not sede.is_deleted, "Sede no encontrada.", "not_found")
        ensure(self.can_view(sede), "No puede ver esta sede.", "sede_scope_denied")
        return sede

    def build_detail(self, sede_id: int) -> dict:
        sede = self.get_for_view(sede_id)
        coordinator = self.repos.sede_coordinators.active_principal_for_sede(sede.id)
        tutors = self.repos.tutors.by_sede(sede.id)
        students = [s for s in sede.students if not s.is_deleted]
        active_rotations = [
            a for a in sede.rotation_assignments
            if not a.is_deleted and a.status == "active"
        ]
        pending_evals = [
            e for e in self.repos.evaluations.pending()
            if e.assignment and e.assignment.sede_id == sede.id
        ]
        alerts = [
            a for a in self.repos.alerts.open_alerts()
            if a.related_entity_type == "sede" and a.related_entity_id == sede.id
        ]
        audit_rows = [
            r for r in self.repos.audit_logs.recent(limit=200)
            if r.entity_type == "sede" and r.entity_id == sede.id
        ][:10]
        return {
            "sede": sede,
            "coordinator": coordinator,
            "tutors": tutors,
            "students": students,
            "student_count": len(students),
            "active_rotations": active_rotations,
            "active_rotation_count": len(active_rotations),
            "pending_eval_count": len(pending_evals),
            "alerts": alerts,
            "audit_rows": audit_rows,
            "can_manage": self.can_manage(),
            "can_delete": is_admin(self.identity),
            "can_deactivate": self.can_manage(),
            "sede_type_label": SEDE_TYPE_LABELS.get(sede.sede_type, sede.sede_type),
        }

    # -- validation -------------------------------------------------------
    def _validate(self, data: dict, *, existing: Sede | None) -> dict:
        v = FieldValidator()
        name = " ".join((data.get("name") or "").split())
        short_name = " ".join((data.get("short_name") or "").split())
        if not name:
            v.add("name", "El nombre completo es obligatorio.")
        if not short_name:
            v.add("short_name", "El nombre corto es obligatorio.")
        sede_type = v.choice("sede_type", data.get("sede_type"), VALID_SEDE_TYPES,
                             "El tipo de sede")
        if not sede_type:
            v.add("sede_type", "El tipo de sede es obligatorio.")
        institution_id = v.int_field("institution_type_id", data.get("institution_type_id"),
                                     "La institución")
        if not institution_id:
            v.add("institution_type_id", "La institución es obligatoria.")
        city = " ".join((data.get("city") or "").split()) or None
        address = " ".join((data.get("address") or "").split()) or None

        if name:
            dup = self.repos.sedes.get_by_name(name)
            if dup and (existing is None or dup.id != existing.id):
                v.add("name", "Ya existe una sede con ese nombre.")
        if short_name:
            dup = self.repos.sedes.get_by_short_name(short_name)
            if dup and (existing is None or dup.id != existing.id):
                v.add("short_name", "Ya existe una sede con ese nombre corto.")

        v.raise_if_errors()
        return {
            "name": name, "short_name": short_name, "sede_type": sede_type,
            "institution_type_id": institution_id, "city": city, "address": address,
        }

    # -- create / update --------------------------------------------------
    def create(self, data: dict, ip: str | None = None) -> Sede:
        ensure(self.can_manage(), "No puede crear sedes.", "create_sede_denied")
        clean = self._validate(data, existing=None)
        sede = Sede(**clean)
        self.repos.sedes.add(sede)
        self.db.flush()
        self.audit.record(audit.CREATE_SEDE, identity=self.identity, entity_type="sede",
                          entity_id=sede.id, detail={"name": sede.name}, ip_address=ip,
                          commit=False)
        self.db.commit()
        return sede

    def update(self, sede_id: int, data: dict, ip: str | None = None) -> Sede:
        sede = self.repos.sedes.get_full(sede_id)
        ensure(sede is not None and not sede.is_deleted, "Sede no encontrada.", "not_found")
        ensure(self.can_manage(), "No puede editar esta sede.", "edit_sede_denied")
        clean = self._validate(data, existing=sede)
        for field, value in clean.items():
            setattr(sede, field, value)
        self.db.flush()
        self.audit.record(audit.UPDATE_SEDE, identity=self.identity, entity_type="sede",
                          entity_id=sede.id, detail={"name": sede.name}, ip_address=ip,
                          commit=False)
        self.db.commit()
        return sede

    # -- lifecycle --------------------------------------------------------
    def set_active(self, sede_id: int, active: bool, *, force: bool = False,
                   reason: str | None = None, ip: str | None = None) -> Sede:
        sede = self.repos.sedes.get_full(sede_id)
        ensure(sede is not None and not sede.is_deleted, "Sede no encontrada.", "not_found")
        ensure(self.can_manage(), "No puede modificar esta sede.", "toggle_sede_denied")

        if active:
            sede.is_active = True
            self.db.flush()
            self.audit.record(audit.REACTIVATE_SEDE, identity=self.identity,
                              entity_type="sede", entity_id=sede.id, ip_address=ip,
                              commit=False)
            self.db.commit()
            return sede

        # Deactivation path — blocked when active/planned rotations exist.
        blocking = self.repos.sedes.active_planned_assignment_count(sede.id)
        if blocking > 0 and not force:
            raise ValidationError({
                "sede": f"No se puede desactivar: la sede tiene {blocking} "
                        "rotación(es) activa(s) o planificada(s). Un administrador "
                        "puede forzar la desactivación indicando un motivo."
            })
        if blocking > 0 and force:
            # Only an administrator may force, and a reason is mandatory.
            ensure(is_admin(self.identity),
                   "Solo un administrador puede forzar la desactivación.",
                   "force_deactivate_sede_denied")
            if not (reason or "").strip():
                raise ValidationError({"reason": "Debe indicar un motivo para forzar."})
            sede.is_active = False
            self.db.flush()
            self.audit.record(audit.FORCE_DEACTIVATE_SEDE, identity=self.identity,
                              entity_type="sede", entity_id=sede.id,
                              detail={"blocking_assignments": blocking},
                              reason=reason.strip(), ip_address=ip, commit=False)
            self.db.commit()
            return sede

        sede.is_active = False
        self.db.flush()
        self.audit.record(audit.DEACTIVATE_SEDE, identity=self.identity,
                          entity_type="sede", entity_id=sede.id, ip_address=ip,
                          commit=False)
        self.db.commit()
        return sede

    def soft_delete(self, sede_id: int, reason: str, ip: str | None = None) -> None:
        ensure(is_admin(self.identity), "Solo un administrador puede eliminar sedes.",
               "delete_sede_denied")
        sede = self.repos.sedes.get_full(sede_id)
        ensure(sede is not None and not sede.is_deleted, "Sede no encontrada.", "not_found")
        if not (reason or "").strip():
            raise ValidationError({"reason": "Debe indicar un motivo para eliminar."})
        blocking = self.repos.sedes.active_planned_assignment_count(sede.id)
        active_staff = (
            len(self.repos.tutors.by_sede(sede.id))
            + (1 if self.repos.sede_coordinators.active_principal_for_sede(sede.id) else 0)
        )
        if blocking > 0 or active_staff > 0:
            raise ValidationError({
                "sede": "No se puede eliminar: existen relaciones activas "
                        f"({blocking} rotación(es), {active_staff} miembro(s) de personal). "
                        "Desactive o reasigne primero."
            })
        sede.is_deleted = True
        sede.is_active = False
        sede.deleted_at = utcnow()
        self.db.flush()
        self.audit.record(audit.SOFT_DELETE_SEDE, identity=self.identity,
                          entity_type="sede", entity_id=sede.id,
                          reason=reason.strip(), ip_address=ip, commit=False)
        self.db.commit()

    # -- form options -----------------------------------------------------
    def form_options(self) -> dict:
        return {
            "institutions": [(i.id, i.name) for i in self.repos.institution_types.list()],
            "institution_codes": [(c.value, c.value) for c in InstitutionCode],
            "sede_types": [("hospital", "Hospital"), ("health_center", "Centro de salud")],
        }
