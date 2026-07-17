"""Incident management service (Batch 2E).

Lifecycle:

    open → under_review → action_required → resolved → closed
    under_review → dismissed          (reason required)
    resolved|closed → reopened        (Administrator, reason required)

Rules enforced here (BUSINESS_RULES.md):
* Resolution requires comments; closing requires a resolution present.
* Dismissal requires a reason; reopen requires Administrator + reason.
* High/critical incidents drive alerts (refreshed after each change).
* History is append-only (``StatusHistory``) — never silently overwritten.
* Confidential incidents and restricted internal notes are scope-limited.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin, is_global_viewer
from app.models.base import IncidentSeverity, IncidentStatus, VisibilityLevel, utcnow
from app.models.operations import (
    INCIDENT_TYPES,
    OWNER_INCIDENT,
    Incident,
    StatusHistory,
)
from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_STUDENT,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
)
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.numbering import allocate_code
from app.services.validators import ValidationError

TRANSITIONS = {
    IncidentStatus.OPEN.value: {IncidentStatus.UNDER_REVIEW.value, IncidentStatus.DISMISSED.value},
    IncidentStatus.UNDER_REVIEW.value: {
        IncidentStatus.ACTION_REQUIRED.value, IncidentStatus.RESOLVED.value,
        IncidentStatus.DISMISSED.value,
    },
    IncidentStatus.ACTION_REQUIRED.value: {
        IncidentStatus.RESOLVED.value, IncidentStatus.UNDER_REVIEW.value,
    },
    IncidentStatus.RESOLVED.value: {IncidentStatus.CLOSED.value, IncidentStatus.REOPENED.value},
    IncidentStatus.CLOSED.value: {IncidentStatus.REOPENED.value},
    IncidentStatus.REOPENED.value: {
        IncidentStatus.UNDER_REVIEW.value, IncidentStatus.ACTION_REQUIRED.value,
    },
    IncidentStatus.DISMISSED.value: set(),
}
TERMINAL = {IncidentStatus.CLOSED.value, IncidentStatus.DISMISSED.value}
_SEVERITIES = {s.value for s in IncidentSeverity}
_ALERTING_SEVERITIES = {IncidentSeverity.HIGH.value, IncidentSeverity.CRITICAL.value}


class IncidentService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    # -- scope helpers ----------------------------------------------------
    def _own_sede_ids(self) -> set[int]:
        return {c.sede_id for c in self.repos.sede_coordinators.active()
                if c.user_id == self.identity.user_id and c.sede_id}

    def _own_tutor_ids(self) -> set[int]:
        return {t.id for t in self.repos.tutors.active() if t.user_id == self.identity.user_id}

    def _own_student_ids(self) -> set[int]:
        return {s.id for s in self.repos.students.search(active=None)
                if s.user_id == self.identity.user_id}

    def _tutor_student_ids(self) -> set[int]:
        tutor_ids = self._own_tutor_ids()
        if not tutor_ids:
            return set()
        return {a.student_id for a in self.repos.assignments.search(tutor_ids=tutor_ids)}

    def is_student(self) -> bool:
        return self.identity.role_code == ROLE_STUDENT

    # -- visibility / permission ------------------------------------------
    def can_view(self, inc: Incident) -> bool:
        role = self.identity.role_code
        confidential = inc.visibility == VisibilityLevel.CONFIDENTIAL.value
        if is_global_viewer(self.identity):
            return True
        if confidential:
            return inc.responsible_user_id == self.identity.user_id \
                or inc.reported_by_user_id == self.identity.user_id
        if role == ROLE_SEDE_COORDINATOR:
            return inc.sede_id in self._own_sede_ids() \
                or inc.reported_by_user_id == self.identity.user_id
        if role == ROLE_TUTOR:
            return inc.reported_by_user_id == self.identity.user_id \
                or inc.student_id in self._tutor_student_ids()
        if role == ROLE_STUDENT:
            return inc.student_id in self._own_student_ids()
        return False

    def can_see_internal(self, inc: Incident) -> bool:
        return not self.is_student()

    def can_create(self) -> bool:
        return self.identity.role_code in (
            ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR, ROLE_TUTOR)

    def can_manage(self, inc: Incident) -> bool:
        """May drive status transitions (review/action/resolve/close/dismiss)."""
        role = self.identity.role_code
        if role in (ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR):
            return True
        # Same confidentiality gate as can_view(): a Sede Coordinator's own-
        # sede scope never overrides confidentiality — only the responsible
        # user, the reporter, or a global viewer (above) may manage it.
        if inc.visibility == VisibilityLevel.CONFIDENTIAL.value:
            return inc.responsible_user_id == self.identity.user_id \
                or inc.reported_by_user_id == self.identity.user_id
        if role == ROLE_SEDE_COORDINATOR:
            return inc.sede_id in self._own_sede_ids()
        return False

    def can_reopen(self, inc: Incident) -> bool:
        return is_admin(self.identity) and inc.status in (
            IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value)

    # -- listing / detail --------------------------------------------------
    def list_incidents(self, **filters) -> list[Incident]:
        role = self.identity.role_code
        if not is_global_viewer(self.identity):
            filters["visibility_in"] = {VisibilityLevel.NORMAL.value,
                                        VisibilityLevel.RESTRICTED.value}
        if role == ROLE_SEDE_COORDINATOR:
            filters["sede_ids"] = self._own_sede_ids() or {-1}
        elif role == ROLE_STUDENT:
            filters["student_ids"] = self._own_student_ids() or {-1}
        elif role == ROLE_TUTOR:
            filters["student_ids"] = self._tutor_student_ids() or {-1}
        rows = self.repos.incidents.search(**filters)
        return [i for i in rows if self.can_view(i)]

    def get_for_view(self, incident_id: int) -> Incident:
        inc = self.repos.incidents.get_full(incident_id)
        ensure(inc is not None, "No tiene permiso para ver esta incidencia.", "not_found")
        ensure(self.can_view(inc),
              "No tiene permiso para ver esta incidencia.", "incident_scope_denied")
        return inc

    def build_detail(self, incident_id: int) -> dict:
        inc = self.get_for_view(incident_id)
        history = self.repos.status_history.for_owner(OWNER_INCIDENT, inc.id)
        attachments = self.repos.attachments.for_owner(OWNER_INCIDENT, inc.id)
        audit_rows = [r for r in self.repos.audit_logs.recent(limit=400)
                      if r.entity_type == "incident" and r.entity_id == inc.id][:15]
        return {
            "inc": inc, "history": history, "attachments": attachments,
            "audit_rows": audit_rows,
            "type_label": INCIDENT_TYPES.get(inc.incident_type, inc.incident_type),
            "can_manage": self.can_manage(inc),
            "can_reopen": self.can_reopen(inc),
            "can_see_internal": self.can_see_internal(inc),
            "can_upload": (self.can_manage(inc) or inc.reported_by_user_id == self.identity.user_id)
                          and inc.status not in TERMINAL,
        }

    def form_options(self) -> dict:
        role = self.identity.role_code
        if is_global_viewer(self.identity):
            students = self.repos.students.search()
            sedes = self.repos.sedes.active()
        elif role == ROLE_SEDE_COORDINATOR:
            ids = self._own_sede_ids() or {-1}
            students = self.repos.students.search(sede_ids=ids)
            sedes = [s for s in self.repos.sedes.active() if s.id in ids]
        elif role == ROLE_TUTOR:
            ids = self._tutor_student_ids()
            students = [s for s in self.repos.students.search() if s.id in ids]
            sedes = self.repos.sedes.active()
        else:
            students, sedes = [], []
        return {
            "students": students, "sedes": sedes,
            "incident_types": INCIDENT_TYPES,
            "severities": [s.value for s in IncidentSeverity],
            "visibilities": [v.value for v in VisibilityLevel],
            "is_student": self.is_student(),
        }

    # -- trail -------------------------------------------------------------
    def _record_history(self, inc: Incident, from_status: str | None, to_status: str,
                        action: str, note: str | None = None) -> None:
        self.db.add(StatusHistory(
            owner_type=OWNER_INCIDENT, owner_id=inc.id,
            from_status=from_status, to_status=to_status, action=action,
            actor_user_id=self.identity.user_id, actor_label=self.identity.email, note=note,
        ))

    def _refresh_alerts(self) -> None:
        from app.services.alert_service import AlertService
        AlertService(self.db).refresh_from_rules()

    # -- validation --------------------------------------------------------
    def _clean(self, data: dict) -> dict:
        errors: dict[str, str] = {}
        title = (data.get("title") or "").strip()
        itype = (data.get("incident_type") or "").strip()
        description = (data.get("description") or "").strip()
        severity = (data.get("severity") or IncidentSeverity.MEDIUM.value).strip()
        if not title:
            errors["title"] = "El título es obligatorio."
        if itype not in INCIDENT_TYPES:
            errors["incident_type"] = "Seleccione un tipo de incidencia válido."
        if not description:
            errors["description"] = "La descripción es obligatoria."
        if severity not in _SEVERITIES:
            severity = IncidentSeverity.MEDIUM.value
        visibility = (data.get("visibility") or VisibilityLevel.NORMAL.value).strip()
        if visibility not in {v.value for v in VisibilityLevel}:
            visibility = VisibilityLevel.NORMAL.value
        due = (data.get("due_date") or "").strip()
        due_date = None
        if due:
            try:
                due_date = date.fromisoformat(due)
            except ValueError:
                errors["due_date"] = "Fecha inválida (use AAAA-MM-DD)."
        if errors:
            raise ValidationError(errors)
        return {
            "title": title, "incident_type": itype, "description": description,
            "severity": severity, "visibility": visibility, "due_date": due_date,
            "internal_notes": (data.get("internal_notes") or "").strip() or None,
        }

    def _resolve_links(self, data: dict) -> dict:
        """Validate optional student/sede links against scope.

        Values arrive as raw POST fields — the create/edit forms only ever
        *display* a scoped dropdown, so the server must independently reject
        a student/sede outside the actor's own scope (the form is not the
        security boundary).
        """
        out = {"student_id": None, "sede_id": None}
        student_id = (data.get("student_id") or "").strip()
        sede_id = (data.get("sede_id") or "").strip()
        if student_id:
            out["student_id"] = int(student_id)
            st = self.repos.students.get(out["student_id"])
            if st and not sede_id:
                out["sede_id"] = st.sede_id
        if sede_id:
            out["sede_id"] = int(sede_id)
        if self.identity.role_code == ROLE_SEDE_COORDINATOR and not is_global_viewer(self.identity):
            own_sede_ids = self._own_sede_ids()
            if out["sede_id"] is not None:
                ensure(out["sede_id"] in own_sede_ids,
                      "No puede vincular esta incidencia a otra sede.", "incident_sede_scope_denied")
            if out["student_id"] is not None:
                st = self.repos.students.get(out["student_id"])
                ensure(st is not None and st.sede_id in own_sede_ids,
                      "No puede vincular esta incidencia a un interno de otra sede.",
                      "incident_student_scope_denied")
        return out

    # -- create / update ---------------------------------------------------
    def create(self, data: dict, ip: str | None = None) -> Incident:
        ensure(self.can_create(), "No tiene permiso para registrar incidencias.", "create_incident_denied")
        cleaned = self._clean(data)
        if self.is_student():
            cleaned.pop("internal_notes", None)
            cleaned["visibility"] = VisibilityLevel.NORMAL.value
        links = self._resolve_links(data)
        # Tutors may only report for their own assigned students.
        if self.identity.role_code == ROLE_TUTOR and links["student_id"]:
            ensure(links["student_id"] in self._tutor_student_ids(),
                   "Solo puede reportar incidencias de sus internos asignados.", "incident_student_denied")
        for _ in range(3):
            code = allocate_code(self.repos, "incident")
            if not self.repos.incidents.get_by_code(code):
                break
        year, number = int(code.split("-")[1]), int(code.split("-")[2])
        inc = Incident(
            code=code, seq_year=year, seq_number=number,
            status=IncidentStatus.OPEN.value,
            reported_by_user_id=self.identity.user_id,
            reported_by=self.identity.email,
            report_date=date.today(),
            **cleaned, **links,
        )
        self.repos.incidents.add(inc)
        self._record_history(inc, None, IncidentStatus.OPEN.value, "create")
        self.audit.record(audit.CREATE_INCIDENT, identity=self.identity,
                          entity_type="incident", entity_id=inc.id,
                          detail={"code": inc.code, "severity": inc.severity,
                                  "incident_type": inc.incident_type}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return inc

    def update(self, incident_id: int, data: dict, ip: str | None = None) -> Incident:
        inc = self.repos.incidents.get_full(incident_id)
        ensure(inc is not None, "Incidencia no encontrada.", "not_found")
        ensure(self.can_manage(inc), "No puede editar esta incidencia.", "edit_incident_denied")
        ensure(inc.status not in TERMINAL, "La incidencia está cerrada.", "incident_locked")
        cleaned = self._clean(data)
        for k, v in cleaned.items():
            setattr(inc, k, v)
        links = self._resolve_links(data)
        for k, v in links.items():
            if v is not None:
                setattr(inc, k, v)
        self.db.flush()
        self.audit.record(audit.UPDATE_INCIDENT, identity=self.identity,
                          entity_type="incident", entity_id=inc.id,
                          detail={"code": inc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return inc

    def assign(self, incident_id: int, responsible_user_id: int | None, ip: str | None = None) -> Incident:
        inc = self.repos.incidents.get_full(incident_id)
        ensure(inc is not None, "Incidencia no encontrada.", "not_found")
        ensure(self.can_manage(inc), "No puede asignar esta incidencia.", "assign_incident_denied")
        inc.responsible_user_id = responsible_user_id
        self.db.flush()
        self.audit.record(audit.ASSIGN_INCIDENT, identity=self.identity,
                          entity_type="incident", entity_id=inc.id,
                          detail={"code": inc.code, "responsible_user_id": responsible_user_id},
                          ip_address=ip, commit=False)
        self.db.commit()
        return inc

    # -- transitions -------------------------------------------------------
    def _transition(self, inc: Incident, to_status: str) -> None:
        ensure(to_status in TRANSITIONS.get(inc.status, set()),
               f"Transición no permitida ({inc.status} → {to_status}).", "invalid_transition")

    def _change(self, incident_id: int, to_status: str, action: str, audit_action: str,
                note: str | None = None, ip: str | None = None) -> Incident:
        inc = self.repos.incidents.get_full(incident_id)
        ensure(inc is not None, "Incidencia no encontrada.", "not_found")
        ensure(self.can_manage(inc), "No puede gestionar esta incidencia.", "manage_incident_denied")
        self._transition(inc, to_status)
        prev = inc.status
        inc.status = to_status
        self._record_history(inc, prev, to_status, action, note)
        self.db.flush()
        self.audit.record(audit_action, identity=self.identity, entity_type="incident",
                          entity_id=inc.id, detail={"code": inc.code}, reason=note, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return inc

    def start_review(self, incident_id: int, ip: str | None = None) -> Incident:
        return self._change(incident_id, IncidentStatus.UNDER_REVIEW.value,
                            "start_review", audit.CHANGE_INCIDENT_STATUS, ip=ip)

    def mark_action_required(self, incident_id: int, ip: str | None = None) -> Incident:
        return self._change(incident_id, IncidentStatus.ACTION_REQUIRED.value,
                            "mark_action_required", audit.CHANGE_INCIDENT_STATUS, ip=ip)

    def resolve(self, incident_id: int, resolution: str, ip: str | None = None) -> Incident:
        inc = self.repos.incidents.get_full(incident_id)
        ensure(inc is not None, "Incidencia no encontrada.", "not_found")
        ensure(self.can_manage(inc), "No puede resolver esta incidencia.", "resolve_incident_denied")
        if not (resolution or "").strip():
            raise ValidationError({"resolution": "La resolución requiere comentarios."})
        self._transition(inc, IncidentStatus.RESOLVED.value)
        prev = inc.status
        inc.status = IncidentStatus.RESOLVED.value
        inc.resolution = resolution.strip()
        inc.resolved_by_user_id = self.identity.user_id
        inc.resolved_at = utcnow()
        self._record_history(inc, prev, inc.status, "resolve", resolution.strip())
        self.db.flush()
        self.audit.record(audit.RESOLVE_INCIDENT, identity=self.identity, entity_type="incident",
                          entity_id=inc.id, detail={"code": inc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return inc

    def close(self, incident_id: int, ip: str | None = None) -> Incident:
        inc = self.repos.incidents.get_full(incident_id)
        ensure(inc is not None, "Incidencia no encontrada.", "not_found")
        ensure(self.can_manage(inc), "No puede cerrar esta incidencia.", "close_incident_denied")
        if not (inc.resolution or "").strip():
            raise ValidationError({"resolution": "No se puede cerrar sin una resolución registrada."})
        self._transition(inc, IncidentStatus.CLOSED.value)
        prev = inc.status
        inc.status = IncidentStatus.CLOSED.value
        inc.closed_by_user_id = self.identity.user_id
        inc.closed_at = utcnow()
        self._record_history(inc, prev, inc.status, "close")
        self.db.flush()
        self.audit.record(audit.CLOSE_INCIDENT, identity=self.identity, entity_type="incident",
                          entity_id=inc.id, detail={"code": inc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return inc

    def dismiss(self, incident_id: int, reason: str, ip: str | None = None) -> Incident:
        inc = self.repos.incidents.get_full(incident_id)
        ensure(inc is not None, "Incidencia no encontrada.", "not_found")
        ensure(self.can_manage(inc), "No puede descartar esta incidencia.", "dismiss_incident_denied")
        if not (reason or "").strip():
            raise ValidationError({"reason": "El descarte requiere un motivo."})
        self._transition(inc, IncidentStatus.DISMISSED.value)
        prev = inc.status
        inc.status = IncidentStatus.DISMISSED.value
        inc.dismissed_by_user_id = self.identity.user_id
        inc.dismissed_at = utcnow()
        inc.dismiss_reason = reason.strip()
        self._record_history(inc, prev, inc.status, "dismiss", reason.strip())
        self.db.flush()
        self.audit.record(audit.DISMISS_INCIDENT, identity=self.identity, entity_type="incident",
                          entity_id=inc.id, reason=reason.strip(), detail={"code": inc.code},
                          ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return inc

    def reopen(self, incident_id: int, reason: str, ip: str | None = None) -> Incident:
        ensure(is_admin(self.identity), "Solo un administrador puede reabrir.", "reopen_incident_denied")
        inc = self.repos.incidents.get_full(incident_id)
        ensure(inc is not None, "Incidencia no encontrada.", "not_found")
        ensure(inc.status in (IncidentStatus.RESOLVED.value, IncidentStatus.CLOSED.value),
               "Solo se puede reabrir una incidencia resuelta o cerrada.", "invalid_transition")
        if not (reason or "").strip():
            raise ValidationError({"reason": "Debe indicar un motivo para reabrir."})
        prev = inc.status
        inc.status = IncidentStatus.REOPENED.value
        inc.reopened_by_user_id = self.identity.user_id
        inc.reopened_at = utcnow()
        inc.reopen_reason = reason.strip()
        self._record_history(inc, prev, inc.status, "reopen", reason.strip())
        self.db.flush()
        self.audit.record(audit.REOPEN_INCIDENT, identity=self.identity, entity_type="incident",
                          entity_id=inc.id, reason=reason.strip(), detail={"code": inc.code},
                          ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return inc
