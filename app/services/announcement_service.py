"""Announcement (comunicados) service.

A sede coordinator broadcasts to everyone at their own sede (students,
tutors, coordinators); admin/university coordinators may additionally send
an institution-wide announcement (no sede) or target a specific sede. There
is no per-recipient read state — visibility is scope-only, matching "enviar
comunicados a todos".
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.authorization import coordinator_sede_ids, ensure, is_global_viewer, tutor_sede_ids
from app.models.announcement import Announcement
from app.models.user import ROLE_SEDE_COORDINATOR, ROLE_STUDENT, ROLE_TUTOR
from app.repositories.repositories import RepositoryBundle
from app.services import audit_service as audit
from app.services.audit_service import AuditService
from app.services.auth_service import Identity
from app.services.validators import FieldValidator, ValidationError

MAX_TITLE = 200
MAX_BODY = 4000


class AnnouncementService:
    def __init__(self, db: Session, identity: Identity) -> None:
        self.db = db
        self.identity = identity
        self.repos = RepositoryBundle(db)
        self.audit = AuditService(db)

    def can_create(self) -> bool:
        return is_global_viewer(self.identity) or self.identity.role_code == ROLE_SEDE_COORDINATOR

    def _own_sede_id(self) -> int | None:
        """The Student record's sede for the current identity, if it's a
        student — used only for the read-scope, students never create."""
        student = next((s for s in self.repos.students.search(active=None)
                        if s.user_id == self.identity.user_id), None)
        return student.sede_id if student else None

    def _read_scope(self) -> set[int] | None:
        """Sede ids the identity may read announcements for, or None for
        unrestricted (every announcement, institution-wide or any sede)."""
        if is_global_viewer(self.identity):
            return None
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            return coordinator_sede_ids(self.identity, self.repos)
        if self.identity.role_code == ROLE_TUTOR:
            return tutor_sede_ids(self.identity, self.repos)
        if self.identity.role_code == ROLE_STUDENT:
            sede_id = self._own_sede_id()
            return {sede_id} if sede_id else set()
        return set()

    def list_visible(self) -> list[Announcement]:
        return self.repos.announcements.visible_to(self._read_scope())

    def sede_options(self) -> list[tuple[int, str]]:
        """Sedes the current identity may target when creating. Admin/
        university get every active sede (plus the institution-wide option,
        rendered separately by the form); a sede coordinator gets only their
        own (the form locks it, this just supplies the label)."""
        if is_global_viewer(self.identity):
            return [(s.id, s.short_name or s.name) for s in self.repos.sedes.active()]
        ids = coordinator_sede_ids(self.identity, self.repos)
        return [(s.id, s.short_name or s.name) for s in self.repos.sedes.active() if s.id in ids]

    def create(self, data: dict, ip: str | None = None) -> Announcement:
        ensure(self.can_create(), "No puede enviar comunicados.", "create_announcement_denied")
        v = FieldValidator()
        title = (data.get("title") or "").strip()
        body = (data.get("body") or "").strip()
        if not title:
            v.add("title", "El título es obligatorio.")
        elif len(title) > MAX_TITLE:
            v.add("title", f"El título no puede exceder {MAX_TITLE} caracteres.")
        if not body:
            v.add("body", "El mensaje es obligatorio.")
        elif len(body) > MAX_BODY:
            v.add("body", f"El mensaje no puede exceder {MAX_BODY} caracteres.")

        if is_global_viewer(self.identity):
            raw_sede = (data.get("sede_id") or "").strip()
            sede_id = int(raw_sede) if raw_sede.isdigit() else None
            if sede_id is not None:
                sede = self.repos.sedes.get(sede_id)
                if sede is None or sede.is_deleted:
                    v.add("sede_id", "La sede seleccionada no es válida.")
        else:
            # Sede coordinator — always their own sede, never institution-wide,
            # never another sede, regardless of what the form submitted.
            own = coordinator_sede_ids(self.identity, self.repos)
            ensure(bool(own), "No tiene una sede asignada.", "no_sede_scope")
            sede_id = next(iter(own))
        v.raise_if_errors()

        ann = Announcement(title=title, body=body, sede_id=sede_id,
                           created_by_user_id=self.identity.user_id)
        self.repos.announcements.add(ann)
        self.audit.record(audit.CREATE_ANNOUNCEMENT, identity=self.identity,
                          entity_type="announcement", entity_id=ann.id,
                          detail={"title": title, "sede_id": sede_id}, ip_address=ip, commit=False)
        self.db.commit()
        return ann
