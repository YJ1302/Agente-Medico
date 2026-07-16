"""Formal document management service (Batch 2E).

Owns the full document lifecycle and the confidentiality/scope model:

    draft → submitted → under_review → approved | rejected
    rejected → draft            (correction loop)
    approved → archived
    approved|archived → draft   (Administrator reopen, reason required)

Design mirrors evaluation_service.py: record-level scope helpers, guard-clause
transitions, append-only ``StatusHistory`` + audit logging, and an alert refresh
after any state change. No document is ever sent automatically — a human always
approves (SECURITY_AND_PRIVACY_RULES.md / DECISIONS_LOG.md).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin, is_global_viewer, is_university
from app.models.base import DocumentPriority, DocumentStatus, VisibilityLevel, utcnow
from app.models.operations import (
    DOCUMENT_TYPES,
    OWNER_DOCUMENT,
    STUDENT_DOCUMENT_TYPES,
    DocumentRecord,
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

# Allowed status transitions (approved→draft / archived→draft handled by reopen).
TRANSITIONS = {
    DocumentStatus.DRAFT.value: {DocumentStatus.SUBMITTED.value},
    DocumentStatus.SUBMITTED.value: {DocumentStatus.UNDER_REVIEW.value},
    DocumentStatus.UNDER_REVIEW.value: {
        DocumentStatus.APPROVED.value, DocumentStatus.REJECTED.value,
    },
    DocumentStatus.REJECTED.value: {DocumentStatus.DRAFT.value},
    DocumentStatus.APPROVED.value: {DocumentStatus.ARCHIVED.value},
    DocumentStatus.ARCHIVED.value: set(),
}
# A document is locked (no field edits) once out of draft.
EDITABLE_STATUSES = {DocumentStatus.DRAFT.value}
_PRIORITIES = {p.value for p in DocumentPriority}
_VISIBILITIES = {v.value for v in VisibilityLevel}


class DocumentService:
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
        """Students supervised by the current tutor via any assignment."""
        tutor_ids = self._own_tutor_ids()
        if not tutor_ids:
            return set()
        return {a.student_id for a in self.repos.assignments.search(tutor_ids=tutor_ids)}

    # -- visibility / permission ------------------------------------------
    def is_student(self) -> bool:
        return self.identity.role_code == ROLE_STUDENT

    def can_view(self, doc: DocumentRecord) -> bool:
        role = self.identity.role_code
        confidential = doc.visibility == VisibilityLevel.CONFIDENTIAL.value
        if is_global_viewer(self.identity):
            return True
        # Confidential: only the explicit creator may see it besides globals.
        if confidential:
            return doc.created_by_user_id == self.identity.user_id
        if role == ROLE_SEDE_COORDINATOR:
            return (doc.sede_id in self._own_sede_ids()
                    or doc.created_by_user_id == self.identity.user_id)
        if role == ROLE_TUTOR:
            return (doc.created_by_user_id == self.identity.user_id
                    or (doc.student_id in self._tutor_student_ids()))
        if role == ROLE_STUDENT:
            return (doc.student_id in self._own_student_ids()
                    or doc.created_by_user_id == self.identity.user_id)
        return False

    def can_see_internal(self, doc: DocumentRecord) -> bool:
        """Restricted internal notes are hidden from students."""
        return not self.is_student()

    def can_create_type(self, doc_type: str) -> bool:
        role = self.identity.role_code
        if role in (ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR):
            return True
        if role == ROLE_STUDENT:
            return doc_type in STUDENT_DOCUMENT_TYPES
        return False  # tutors do not originate formal documents

    def can_edit(self, doc: DocumentRecord) -> bool:
        if doc.status not in EDITABLE_STATUSES:
            return False
        if is_global_viewer(self.identity):
            return True
        if self.identity.role_code == ROLE_SEDE_COORDINATOR:
            return doc.sede_id in self._own_sede_ids() or doc.created_by_user_id == self.identity.user_id
        return doc.created_by_user_id == self.identity.user_id

    def can_submit(self, doc: DocumentRecord) -> bool:
        return doc.status == DocumentStatus.DRAFT.value and self.can_edit(doc)

    def can_review_flow(self, doc: DocumentRecord) -> bool:
        """May move submitted → under_review (start review)."""
        role = self.identity.role_code
        if doc.status != DocumentStatus.SUBMITTED.value:
            return False
        if role in (ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR):
            return True
        if role == ROLE_SEDE_COORDINATOR:
            return doc.sede_id in self._own_sede_ids()
        return False

    def can_decide(self, doc: DocumentRecord) -> bool:
        """May approve/reject an under_review document (Admin/University only)."""
        return (doc.status == DocumentStatus.UNDER_REVIEW.value
                and self.identity.role_code in (ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR))

    def can_archive(self, doc: DocumentRecord) -> bool:
        return (doc.status == DocumentStatus.APPROVED.value
                and self.identity.role_code in (ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR))

    def can_reopen(self, doc: DocumentRecord) -> bool:
        return (is_admin(self.identity)
                and doc.status in (DocumentStatus.APPROVED.value, DocumentStatus.ARCHIVED.value))

    # -- listing / detail --------------------------------------------------
    def list_documents(self, **filters) -> list[DocumentRecord]:
        role = self.identity.role_code
        # Confidential documents are only listed for global viewers.
        if not is_global_viewer(self.identity):
            filters["visibility_in"] = {VisibilityLevel.NORMAL.value,
                                        VisibilityLevel.RESTRICTED.value}
        if role == ROLE_SEDE_COORDINATOR:
            filters["sede_ids"] = self._own_sede_ids() or {-1}
        elif role == ROLE_STUDENT:
            filters["student_ids"] = self._own_student_ids() or {-1}
        elif role == ROLE_TUTOR:
            ids = self._tutor_student_ids()
            filters["student_ids"] = ids or {-1}
        rows = self.repos.documents.search(**filters)
        # Final defensive per-row filter (covers created_by edge cases).
        return [d for d in rows if self.can_view(d)]

    def get_for_view(self, document_id: int) -> DocumentRecord:
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(self.can_view(doc), "No puede ver este documento.", "document_scope_denied")
        return doc

    def build_detail(self, document_id: int) -> dict:
        doc = self.get_for_view(document_id)
        history = self.repos.status_history.for_owner(OWNER_DOCUMENT, doc.id)
        attachments = self.repos.attachments.for_owner(OWNER_DOCUMENT, doc.id)
        audit_rows = [r for r in self.repos.audit_logs.recent(limit=400)
                      if r.entity_type == "document" and r.entity_id == doc.id][:15]
        return {
            "doc": doc,
            "history": history,
            "attachments": attachments,
            "audit_rows": audit_rows,
            "type_label": DOCUMENT_TYPES.get(doc.doc_type, doc.doc_type),
            "can_edit": self.can_edit(doc),
            "can_submit": self.can_submit(doc),
            "can_review_flow": self.can_review_flow(doc),
            "can_decide": self.can_decide(doc),
            "can_archive": self.can_archive(doc),
            "can_reopen": self.can_reopen(doc),
            "can_see_internal": self.can_see_internal(doc),
            "can_upload": self.can_edit(doc) or is_admin(self.identity),
        }

    def form_options(self) -> dict:
        """Scoped dropdown data + allowed vocabularies for the create/edit form."""
        role = self.identity.role_code
        if is_global_viewer(self.identity):
            students = self.repos.students.search()
            sedes = self.repos.sedes.active()
        elif role == ROLE_SEDE_COORDINATOR:
            ids = self._own_sede_ids() or {-1}
            students = self.repos.students.search(sede_ids=ids)
            sedes = [s for s in self.repos.sedes.active() if s.id in ids]
        else:  # student / tutor: no free selection (auto-linked to self)
            students, sedes = [], []
        allowed_types = {k: v for k, v in DOCUMENT_TYPES.items()
                         if self.can_create_type(k)}
        return {
            "students": students, "sedes": sedes,
            "templates": self.repos.document_templates.active(),
            "doc_types": allowed_types,
            "priorities": [p.value for p in DocumentPriority],
            "visibilities": [v.value for v in VisibilityLevel],
            "is_student": self.is_student(),
        }

    def template_prefill(self, code: str) -> dict:
        """Return initial draft field values from a template (editable, never approved)."""
        tpl = self.repos.document_templates.get_by_code(code)
        if not tpl:
            return {}
        return {
            "doc_type": tpl.doc_type,
            "title": tpl.name,
            "subject": tpl.subject_template or "",
            "body": tpl.body_template,
            "template_code": tpl.code,
        }

    # -- workflow trail ----------------------------------------------------
    def _record_history(self, doc: DocumentRecord, from_status: str | None,
                        to_status: str, action: str, note: str | None = None) -> None:
        self.db.add(StatusHistory(
            owner_type=OWNER_DOCUMENT, owner_id=doc.id,
            from_status=from_status, to_status=to_status, action=action,
            actor_user_id=self.identity.user_id, actor_label=self.identity.email,
            note=note,
        ))

    def _refresh_alerts(self) -> None:
        from app.services.alert_service import AlertService
        AlertService(self.db).refresh_from_rules()

    # -- validation --------------------------------------------------------
    def _clean(self, data: dict) -> dict:
        errors: dict[str, str] = {}
        title = (data.get("title") or "").strip()
        doc_type = (data.get("doc_type") or "").strip()
        if not title:
            errors["title"] = "El título es obligatorio."
        if doc_type not in DOCUMENT_TYPES:
            errors["doc_type"] = "Seleccione un tipo de documento válido."
        priority = (data.get("priority") or DocumentPriority.NORMAL.value).strip()
        if priority not in _PRIORITIES:
            priority = DocumentPriority.NORMAL.value
        visibility = (data.get("visibility") or VisibilityLevel.NORMAL.value).strip()
        if visibility not in _VISIBILITIES:
            visibility = VisibilityLevel.NORMAL.value
        # Students may never mark a document confidential.
        if self.is_student():
            visibility = VisibilityLevel.NORMAL.value
        if errors:
            raise ValidationError(errors)
        return {
            "title": title, "doc_type": doc_type, "priority": priority,
            "visibility": visibility,
            "subject": (data.get("subject") or "").strip() or None,
            "summary": (data.get("summary") or "").strip() or None,
            "body": (data.get("body") or "").strip() or None,
            "origin": (data.get("origin") or "").strip() or None,
            "destination": (data.get("destination") or "").strip() or None,
            "internal_notes": (data.get("internal_notes") or "").strip() or None,
        }

    def _resolve_links(self, data: dict) -> dict:
        """Validate optional student/sede/assignment links against scope."""
        out: dict = {"student_id": None, "sede_id": None, "assignment_id": None}
        student_id = (data.get("student_id") or "").strip()
        sede_id = (data.get("sede_id") or "").strip()
        assignment_id = (data.get("assignment_id") or "").strip()
        if self.is_student():
            own = self._own_student_ids()
            out["student_id"] = next(iter(own)) if own else None
            st = self.repos.students.get(out["student_id"]) if out["student_id"] else None
            out["sede_id"] = st.sede_id if st else None
            return out
        if student_id:
            out["student_id"] = int(student_id)
        if sede_id:
            out["sede_id"] = int(sede_id)
        if assignment_id:
            out["assignment_id"] = int(assignment_id)
        return out

    # -- create / update ---------------------------------------------------
    def create(self, data: dict, ip: str | None = None) -> DocumentRecord:
        cleaned = self._clean(data)
        ensure(self.can_create_type(cleaned["doc_type"]),
               "No tiene permiso para crear este tipo de documento.", "create_document_type_denied")
        links = self._resolve_links(data)
        # Retry once on the (extremely unlikely) code collision.
        for _ in range(3):
            code = allocate_code(self.repos, "document")
            if not self.repos.documents.get_by_code(code):
                break
        year, number = int(code.split("-")[1]), int(code.split("-")[2])
        doc = DocumentRecord(
            code=code, seq_year=year, seq_number=number,
            status=DocumentStatus.DRAFT.value,
            created_by_user_id=self.identity.user_id,
            **cleaned, **links,
        )
        self.repos.documents.add(doc)
        self._record_history(doc, None, DocumentStatus.DRAFT.value, "create")
        self.audit.record(audit.CREATE_DOCUMENT, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          detail={"code": doc.code, "doc_type": doc.doc_type}, ip_address=ip, commit=False)
        self.db.commit()
        return doc

    def update_draft(self, document_id: int, data: dict, ip: str | None = None) -> DocumentRecord:
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(self.can_edit(doc), "No puede editar este documento.", "edit_document_denied")
        cleaned = self._clean(data)
        # Students cannot edit internal notes.
        if self.is_student():
            cleaned.pop("internal_notes", None)
        for k, v in cleaned.items():
            setattr(doc, k, v)
        links = self._resolve_links(data)
        if not self.is_student():
            for k, v in links.items():
                setattr(doc, k, v)
        self.db.flush()
        self.audit.record(audit.UPDATE_DOCUMENT, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          detail={"code": doc.code}, ip_address=ip, commit=False)
        self.db.commit()
        return doc

    # -- transitions -------------------------------------------------------
    def _transition(self, doc: DocumentRecord, to_status: str) -> None:
        allowed = TRANSITIONS.get(doc.status, set())
        ensure(to_status in allowed,
               f"Transición no permitida ({doc.status} → {to_status}).", "invalid_transition")

    def submit(self, document_id: int, ip: str | None = None) -> DocumentRecord:
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(self.can_submit(doc), "No puede enviar este documento.", "submit_document_denied")
        self._transition(doc, DocumentStatus.SUBMITTED.value)
        prev = doc.status
        doc.status = DocumentStatus.SUBMITTED.value
        doc.submitted_by_user_id = self.identity.user_id
        doc.submitted_at = utcnow()
        self._record_history(doc, prev, doc.status, "submit")
        self.db.flush()
        self.audit.record(audit.SUBMIT_DOCUMENT, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          detail={"code": doc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return doc

    def start_review(self, document_id: int, ip: str | None = None) -> DocumentRecord:
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(self.can_review_flow(doc), "No puede iniciar la revisión.", "review_document_denied")
        self._transition(doc, DocumentStatus.UNDER_REVIEW.value)
        prev = doc.status
        doc.status = DocumentStatus.UNDER_REVIEW.value
        doc.reviewed_by_user_id = self.identity.user_id
        doc.reviewed_at = utcnow()
        self._record_history(doc, prev, doc.status, "start_review")
        self.db.flush()
        self.audit.record(audit.START_DOCUMENT_REVIEW, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          detail={"code": doc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return doc

    def approve(self, document_id: int, note: str = "", ip: str | None = None) -> DocumentRecord:
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(self.can_decide(doc), "No puede aprobar este documento.", "approve_document_denied")
        self._transition(doc, DocumentStatus.APPROVED.value)
        prev = doc.status
        doc.status = DocumentStatus.APPROVED.value
        doc.approved_by_user_id = self.identity.user_id
        doc.approved_at = utcnow()
        self._record_history(doc, prev, doc.status, "approve", (note or "").strip() or None)
        self.db.flush()
        self.audit.record(audit.APPROVE_DOCUMENT, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          detail={"code": doc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return doc

    def reject(self, document_id: int, reason: str, ip: str | None = None) -> DocumentRecord:
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(self.can_decide(doc), "No puede rechazar este documento.", "reject_document_denied")
        if not (reason or "").strip():
            raise ValidationError({"reason": "Debe indicar el motivo del rechazo."})
        self._transition(doc, DocumentStatus.REJECTED.value)
        prev = doc.status
        doc.status = DocumentStatus.REJECTED.value
        doc.rejected_by_user_id = self.identity.user_id
        doc.rejected_at = utcnow()
        doc.rejection_reason = reason.strip()
        self._record_history(doc, prev, doc.status, "reject", reason.strip())
        self.db.flush()
        self.audit.record(audit.REJECT_DOCUMENT, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          reason=reason.strip(), detail={"code": doc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return doc

    def return_to_draft(self, document_id: int, ip: str | None = None) -> DocumentRecord:
        """Move a rejected document back to draft so its author can correct it."""
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(doc.status == DocumentStatus.REJECTED.value,
               "Solo un documento rechazado puede volver a borrador.", "invalid_transition")
        ensure(is_global_viewer(self.identity)
               or doc.created_by_user_id == self.identity.user_id
               or (self.identity.role_code == ROLE_SEDE_COORDINATOR and doc.sede_id in self._own_sede_ids()),
               "No puede corregir este documento.", "correct_document_denied")
        self._transition(doc, DocumentStatus.DRAFT.value)
        prev = doc.status
        doc.status = DocumentStatus.DRAFT.value
        self._record_history(doc, prev, doc.status, "return_to_draft")
        self.db.flush()
        self.audit.record(audit.UPDATE_DOCUMENT, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          detail={"code": doc.code, "action": "return_to_draft"}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return doc

    def archive(self, document_id: int, ip: str | None = None) -> DocumentRecord:
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(self.can_archive(doc), "No puede archivar este documento.", "archive_document_denied")
        self._transition(doc, DocumentStatus.ARCHIVED.value)
        prev = doc.status
        doc.status = DocumentStatus.ARCHIVED.value
        doc.archived_by_user_id = self.identity.user_id
        doc.archived_at = utcnow()
        self._record_history(doc, prev, doc.status, "archive")
        self.db.flush()
        self.audit.record(audit.ARCHIVE_DOCUMENT, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          detail={"code": doc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return doc

    def reopen(self, document_id: int, reason: str, ip: str | None = None) -> DocumentRecord:
        ensure(is_admin(self.identity), "Solo un administrador puede reabrir.", "reopen_document_denied")
        doc = self.repos.documents.get_full(document_id)
        ensure(doc is not None, "Documento no encontrado.", "not_found")
        ensure(doc.status in (DocumentStatus.APPROVED.value, DocumentStatus.ARCHIVED.value),
               "Solo se puede reabrir un documento aprobado o archivado.", "invalid_transition")
        if not (reason or "").strip():
            raise ValidationError({"reason": "Debe indicar un motivo para reabrir."})
        prev = doc.status
        doc.status = DocumentStatus.DRAFT.value
        doc.reopened_by_user_id = self.identity.user_id
        doc.reopened_at = utcnow()
        doc.reopen_reason = reason.strip()
        self._record_history(doc, prev, doc.status, "reopen", reason.strip())
        self.db.flush()
        self.audit.record(audit.REOPEN_DOCUMENT, identity=self.identity,
                          entity_type="document", entity_id=doc.id,
                          reason=reason.strip(), detail={"code": doc.code}, ip_address=ip, commit=False)
        self.db.commit()
        self._refresh_alerts()
        return doc
