"""Formal document management routes (Batch 2E). Thin controllers.

Every mutation is POST + CSRF-protected; GET never mutates state. Authorization
and scope live in ``DocumentService`` — routes only translate HTTP to service
calls and render templates.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app.authorization import ensure
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.models.operations import DOCUMENT_TYPES, OWNER_DOCUMENT
from app.services import audit_service as audit
from app.services.attachment_service import AttachmentService
from app.services.audit_service import client_ip
from app.services.document_service import DocumentService
from app.services.export_service import document_to_pdf
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash, paginate

router = APIRouter(tags=["documents"])
PER_PAGE = 15


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


@router.get("/documents")
def list_documents(request: Request, identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db), q: str = "", status: str = "",
                   doc_type: str = "", page: int = 1):
    svc = DocumentService(db, identity)
    rows = svc.list_documents(query=q or None, status=status or None, doc_type=doc_type or None)
    paged = paginate(rows, page, PER_PAGE)
    base_qs = "".join(f"{k}={v}&" for k, v in
                      (("q", q), ("status", status), ("doc_type", doc_type)) if v)
    # Status badge counts from the already role/sede-scoped `rows` — never a
    # global count, which would leak volume outside the caller's scope.
    counts: dict[str, int] = {}
    for d in rows:
        counts[d.status] = counts.get(d.status, 0) + 1
    return render(request, "pages/documents_list.html", identity=identity,
                  page_title="Documentos",
                  page_subtitle="Comunicaciones formales con estados trazables.",
                  page_icon="file-earmark-text", page=paged, q=q, status=status,
                  doc_type=doc_type, doc_types=DOCUMENT_TYPES, base_qs=base_qs,
                  counts=counts)


@router.get("/documents/new")
def new_document(request: Request, identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db), template: str = "", doc_type: str = ""):
    svc = DocumentService(db, identity)
    opts = svc.form_options()
    ensure(bool(opts["doc_types"]), "No tiene permiso para crear documentos.", "create_document_denied")
    prefill = svc.template_prefill(template) if template else {}
    if doc_type:
        prefill.setdefault("doc_type", doc_type)
    return render(request, "pages/document_form.html", identity=identity,
                  page_title="Nuevo documento", page_icon="file-earmark-plus",
                  mode="create", doc=None, values=prefill, errors={}, **opts)


@router.post("/documents")
async def create_document(request: Request, identity: Identity = Depends(require_identity),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = DocumentService(db, identity)
    data = await _form(request)
    try:
        doc = svc.create(data, ip=client_ip(request))
    except ValidationError as e:
        opts = svc.form_options()
        return render(request, "pages/document_form.html", identity=identity,
                      page_title="Nuevo documento", page_icon="file-earmark-plus",
                      mode="create", doc=None, values=data, errors=e.errors,
                      status_code=400, **opts)
    flash(request, f"Documento {doc.code} creado como borrador.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/documents/{doc.id}", status_code=303)


@router.get("/documents/{document_id}")
def document_detail(document_id: int, request: Request,
                    identity: Identity = Depends(require_identity),
                    db: Session = Depends(get_db)):
    svc = DocumentService(db, identity)
    data = svc.build_detail(document_id)
    doc = data["doc"]
    return render(request, "pages/document_detail.html", identity=identity,
                  page_title=f"{doc.code}", page_subtitle=doc.title,
                  page_icon="file-earmark-text", **data)


@router.get("/documents/{document_id}/edit")
def edit_document(document_id: int, request: Request,
                  identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    svc = DocumentService(db, identity)
    doc = svc.get_for_view(document_id)
    ensure(svc.can_edit(doc), "Este documento está bloqueado para edición.", "edit_document_denied")
    opts = svc.form_options()
    return render(request, "pages/document_form.html", identity=identity,
                  page_title=f"Editar {doc.code}", page_icon="pencil-square",
                  mode="edit", doc=doc, values=_doc_values(doc), errors={}, **opts)


def _doc_values(doc) -> dict:
    return {
        "title": doc.title, "doc_type": doc.doc_type, "priority": doc.priority,
        "visibility": doc.visibility, "subject": doc.subject or "",
        "summary": doc.summary or "", "body": doc.body or "",
        "origin": doc.origin or "", "destination": doc.destination or "",
        "internal_notes": doc.internal_notes or "",
        "student_id": doc.student_id or "", "sede_id": doc.sede_id or "",
    }


@router.post("/documents/{document_id}/edit")
async def update_document(document_id: int, request: Request,
                          identity: Identity = Depends(require_identity),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = DocumentService(db, identity)
    data = await _form(request)
    try:
        svc.update_draft(document_id, data, ip=client_ip(request))
    except ValidationError as e:
        doc = svc.get_for_view(document_id)
        opts = svc.form_options()
        return render(request, "pages/document_form.html", identity=identity,
                      page_title=f"Editar {doc.code}", page_icon="pencil-square",
                      mode="edit", doc=doc, values=data, errors=e.errors,
                      status_code=400, **opts)
    flash(request, "Documento actualizado.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/documents/{document_id}", status_code=303)


def _transition_route(path: str, method_name: str, success_msg: str, needs_reason: bool = False):
    @router.post(path)
    async def _handler(document_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                       reason: str = Form(""), note: str = Form("")):
        svc = DocumentService(db, identity)
        method = getattr(svc, method_name)
        try:
            if method_name in ("reject",):
                method(document_id, reason, ip=client_ip(request))
            elif method_name in ("reopen",):
                method(document_id, reason, ip=client_ip(request))
            elif method_name in ("approve",):
                method(document_id, note, ip=client_ip(request))
            else:
                method(document_id, ip=client_ip(request))
        except ValidationError as e:
            flash(request, list(e.errors.values())[0], "danger")
            return RedirectResponse(url=f"/documents/{document_id}", status_code=303)
        flash(request, success_msg, FLASH_SUCCESS)
        return RedirectResponse(url=f"/documents/{document_id}", status_code=303)
    return _handler


_transition_route("/documents/{document_id}/submit", "submit", "Documento enviado.")
_transition_route("/documents/{document_id}/review", "start_review", "Revisión iniciada.")
_transition_route("/documents/{document_id}/approve", "approve", "Documento aprobado.")
_transition_route("/documents/{document_id}/reject", "reject", "Documento rechazado.")
_transition_route("/documents/{document_id}/return", "return_to_draft", "Documento devuelto a borrador.")
_transition_route("/documents/{document_id}/archive", "archive", "Documento archivado.")
_transition_route("/documents/{document_id}/reopen", "reopen", "Documento reabierto.")


@router.get("/documents/{document_id}/print")
def print_document(document_id: int, request: Request,
                   identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db)):
    svc = DocumentService(db, identity)
    data = svc.build_detail(document_id)
    return render(request, "pages/document_print.html", identity=identity,
                  page_title=data["doc"].code, **data)


@router.get("/documents/{document_id}/pdf")
def document_pdf(document_id: int, request: Request,
                 identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    svc = DocumentService(db, identity)
    doc = svc.get_for_view(document_id)
    student = svc.repos.students.get(doc.student_id) if doc.student_id else None
    sede = svc.repos.sedes.get(doc.sede_id) if doc.sede_id else None
    pdf = document_to_pdf(doc, type_label=DOCUMENT_TYPES.get(doc.doc_type, doc.doc_type),
                          student_name=student.full_name if student else None,
                          sede_name=(sede.short_name or sede.name) if sede else None)
    svc.audit.record(audit.GENERATE_DOCUMENT_PDF, identity=identity,
                     entity_type="document", entity_id=doc.id, detail={"code": doc.code},
                     ip_address=client_ip(request))
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{doc.code}.pdf"'})


# --- Attachments -----------------------------------------------------------
@router.post("/documents/{document_id}/attachments")
async def upload_attachment(document_id: int, request: Request,
                            identity: Identity = Depends(require_identity),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = DocumentService(db, identity)
    doc = svc.get_for_view(document_id)
    ensure(svc.can_edit(doc) or svc.identity.role_code == "admin",
           "Solo puede adjuntar archivos en un borrador.", "upload_attachment_denied")
    form = await request.form()
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        flash(request, "Seleccione un archivo.", "danger")
        return RedirectResponse(url=f"/documents/{document_id}", status_code=303)
    raw = await upload.read()
    att_svc = AttachmentService(db, identity)
    try:
        att_svc.store(OWNER_DOCUMENT, doc.id, upload.filename, upload.content_type, raw,
                      audit_action=audit.UPLOAD_DOCUMENT_ATTACHMENT, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/documents/{document_id}", status_code=303)
    flash(request, "Archivo adjuntado de forma segura.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/documents/{document_id}", status_code=303)


@router.get("/documents/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, request: Request,
                        identity: Identity = Depends(require_identity),
                        db: Session = Depends(get_db)):
    svc = DocumentService(db, identity)
    att = svc.repos.attachments.get(attachment_id)
    ensure(att is not None and att.owner_type == OWNER_DOCUMENT and not att.is_deleted,
           "Adjunto no encontrado.", "not_found")
    svc.get_for_view(att.owner_id)  # enforces view scope on the owning document
    att_svc = AttachmentService(db, identity)
    try:
        path = att_svc.resolve_download(att, audit_action=audit.DOWNLOAD_DOCUMENT_ATTACHMENT,
                                        ip=client_ip(request))
    except ValidationError:
        ensure(False, "El archivo no está disponible.", "attachment_missing")
    return StreamingResponse(
        open(path, "rb"), media_type=att.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{att.original_filename}"'})


@router.post("/documents/attachments/{attachment_id}/delete")
async def delete_attachment(attachment_id: int, request: Request,
                            identity: Identity = Depends(require_identity),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                            reason: str = Form("")):
    from app.authorization import is_admin
    from app.models.base import DocumentStatus
    svc = DocumentService(db, identity)
    att = svc.repos.attachments.get(attachment_id)
    ensure(att is not None and att.owner_type == OWNER_DOCUMENT and not att.is_deleted,
           "Adjunto no encontrado.", "not_found")
    doc = svc.get_for_view(att.owner_id)
    is_draft = doc.status == DocumentStatus.DRAFT.value
    if not is_draft:
        # Only an Administrator may delete an attachment on a non-draft document,
        # and only with a documented reason.
        ensure(is_admin(identity), "Solo se pueden eliminar adjuntos en un borrador.",
               "delete_attachment_locked")
        if not reason.strip():
            flash(request, "Debe indicar un motivo para eliminar un adjunto bloqueado.", "danger")
            return RedirectResponse(url=f"/documents/{att.owner_id}", status_code=303)
    else:
        ensure(svc.can_edit(doc), "No puede eliminar este adjunto.", "delete_attachment_denied")
    AttachmentService(db, identity).soft_delete(
        att, audit_action=audit.DELETE_DOCUMENT_ATTACHMENT,
        reason=reason.strip() or None, ip=client_ip(request))
    flash(request, "Adjunto eliminado.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/documents/{att.owner_id}", status_code=303)
