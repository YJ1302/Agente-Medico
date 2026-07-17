"""Incident management routes (Batch 2E). Thin controllers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.authorization import ensure, is_admin
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.models.base import IncidentStatus
from app.models.operations import INCIDENT_TYPES, OWNER_INCIDENT
from app.services import audit_service as audit
from app.services.attachment_service import AttachmentService
from app.services.audit_service import client_ip
from app.services.incident_service import IncidentService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash, paginate

router = APIRouter(tags=["incidents"])
PER_PAGE = 15


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


@router.get("/incidents")
def list_incidents(request: Request, identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db), q: str = "", status: str = "",
                   severity: str = "", incident_type: str = "", page: int = 1):
    svc = IncidentService(db, identity)
    rows = svc.list_incidents(query=q or None, status=status or None,
                              severity=severity or None, incident_type=incident_type or None)
    paged = paginate(rows, page, PER_PAGE)
    base_qs = "".join(f"{k}={v}&" for k, v in
                      (("q", q), ("status", status), ("severity", severity),
                       ("incident_type", incident_type)) if v)
    # Open-by-severity badge counts from the caller's own scoped, unfiltered
    # incident list — never a global count, which would leak volume outside
    # the caller's scope (sede/student/tutor/confidentiality).
    from app.services.incident_service import TERMINAL
    counts: dict[str, int] = {}
    for inc in svc.list_incidents():
        if inc.status not in TERMINAL:
            counts[inc.severity] = counts.get(inc.severity, 0) + 1
    return render(request, "pages/incidents_list.html", identity=identity,
                  page_title="Incidencias",
                  page_subtitle="Situaciones que afectan el desarrollo del internado.",
                  page_icon="exclamation-triangle", page=paged, q=q, status=status,
                  severity=severity, incident_type=incident_type,
                  incident_types=INCIDENT_TYPES, base_qs=base_qs, can_create=svc.can_create(),
                  counts=counts)


@router.get("/incidents/new")
def new_incident(request: Request, identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    svc = IncidentService(db, identity)
    ensure(svc.can_create(), "No tiene permiso para registrar incidencias.", "create_incident_denied")
    return render(request, "pages/incident_form.html", identity=identity,
                  page_title="Nueva incidencia", page_icon="exclamation-triangle",
                  mode="create", inc=None, values={}, errors={}, **svc.form_options())


@router.post("/incidents")
async def create_incident(request: Request, identity: Identity = Depends(require_identity),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = IncidentService(db, identity)
    data = await _form(request)
    try:
        inc = svc.create(data, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/incident_form.html", identity=identity,
                      page_title="Nueva incidencia", page_icon="exclamation-triangle",
                      mode="create", inc=None, values=data, errors=e.errors,
                      status_code=400, **svc.form_options())
    flash(request, f"Incidencia {inc.code} registrada.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/incidents/{inc.id}", status_code=303)


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: int, request: Request,
                    identity: Identity = Depends(require_identity),
                    db: Session = Depends(get_db)):
    svc = IncidentService(db, identity)
    data = svc.build_detail(incident_id)
    inc = data["inc"]
    return render(request, "pages/incident_detail.html", identity=identity,
                  page_title=inc.code, page_subtitle=inc.title,
                  page_icon="exclamation-triangle", **data)


@router.get("/incidents/{incident_id}/edit")
def edit_incident(incident_id: int, request: Request,
                  identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    svc = IncidentService(db, identity)
    inc = svc.get_for_view(incident_id)
    ensure(svc.can_manage(inc) and inc.status not in ("closed", "dismissed"),
           "No puede editar esta incidencia.", "edit_incident_denied")
    values = {
        "title": inc.title, "incident_type": inc.incident_type, "severity": inc.severity,
        "visibility": inc.visibility, "description": inc.description,
        "internal_notes": inc.internal_notes or "", "student_id": inc.student_id or "",
        "sede_id": inc.sede_id or "", "due_date": inc.due_date.isoformat() if inc.due_date else "",
    }
    return render(request, "pages/incident_form.html", identity=identity,
                  page_title=f"Editar {inc.code}", page_icon="pencil-square",
                  mode="edit", inc=inc, values=values, errors={}, **svc.form_options())


@router.post("/incidents/{incident_id}/edit")
async def update_incident(incident_id: int, request: Request,
                          identity: Identity = Depends(require_identity),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = IncidentService(db, identity)
    data = await _form(request)
    try:
        svc.update(incident_id, data, ip=client_ip(request))
    except ValidationError as e:
        inc = svc.get_for_view(incident_id)
        return render(request, "pages/incident_form.html", identity=identity,
                      page_title=f"Editar {inc.code}", page_icon="pencil-square",
                      mode="edit", inc=inc, values=data, errors=e.errors,
                      status_code=400, **svc.form_options())
    flash(request, "Incidencia actualizada.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)


def _transition_route(path: str, method_name: str, success_msg: str):
    @router.post(path)
    async def _handler(incident_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                       reason: str = Form(""), resolution: str = Form("")):
        svc = IncidentService(db, identity)
        method = getattr(svc, method_name)
        try:
            if method_name == "resolve":
                method(incident_id, resolution, ip=client_ip(request))
            elif method_name in ("dismiss", "reopen"):
                method(incident_id, reason, ip=client_ip(request))
            else:
                method(incident_id, ip=client_ip(request))
        except ValidationError as e:
            flash(request, list(e.errors.values())[0], "danger")
            return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)
        flash(request, success_msg, FLASH_SUCCESS)
        return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)
    return _handler


_transition_route("/incidents/{incident_id}/review", "start_review", "Incidencia en revisión.")
_transition_route("/incidents/{incident_id}/action", "mark_action_required", "Marcada como requiere acción.")
_transition_route("/incidents/{incident_id}/resolve", "resolve", "Incidencia resuelta.")
_transition_route("/incidents/{incident_id}/close", "close", "Incidencia cerrada.")
_transition_route("/incidents/{incident_id}/dismiss", "dismiss", "Incidencia descartada.")
_transition_route("/incidents/{incident_id}/reopen", "reopen", "Incidencia reabierta.")


@router.post("/incidents/{incident_id}/assign")
async def assign_incident(incident_id: int, request: Request,
                          identity: Identity = Depends(require_identity),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                          responsible_user_id: str = Form("")):
    svc = IncidentService(db, identity)
    rid = int(responsible_user_id) if responsible_user_id.strip() else None
    svc.assign(incident_id, rid, ip=client_ip(request))
    flash(request, "Responsable actualizado.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)


# --- Attachments -----------------------------------------------------------
@router.post("/incidents/{incident_id}/attachments")
async def upload_attachment(incident_id: int, request: Request,
                            identity: Identity = Depends(require_identity),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = IncidentService(db, identity)
    inc = svc.get_for_view(incident_id)
    ensure((svc.can_manage(inc) or inc.reported_by_user_id == identity.user_id)
           and inc.status not in (IncidentStatus.CLOSED.value, IncidentStatus.DISMISSED.value),
           "No puede adjuntar archivos a esta incidencia.", "upload_attachment_denied")
    form = await request.form()
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        flash(request, "Seleccione un archivo.", "danger")
        return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)
    raw = await upload.read()
    try:
        AttachmentService(db, identity).store(
            OWNER_INCIDENT, inc.id, upload.filename, upload.content_type, raw,
            audit_action=audit.UPLOAD_INCIDENT_ATTACHMENT, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)
    flash(request, "Archivo adjuntado de forma segura.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/incidents/{incident_id}", status_code=303)


@router.get("/incidents/attachments/{attachment_id}/download")
def download_attachment(attachment_id: int, request: Request,
                        identity: Identity = Depends(require_identity),
                        db: Session = Depends(get_db)):
    svc = IncidentService(db, identity)
    att = svc.repos.attachments.get(attachment_id)
    ensure(att is not None and att.owner_type == OWNER_INCIDENT and not att.is_deleted,
           "Adjunto no encontrado.", "not_found")
    svc.get_for_view(att.owner_id)
    try:
        path = AttachmentService(db, identity).resolve_download(
            att, audit_action=audit.DOWNLOAD_INCIDENT_ATTACHMENT, ip=client_ip(request))
    except ValidationError:
        ensure(False, "El archivo no está disponible.", "attachment_missing")
    return StreamingResponse(
        open(path, "rb"), media_type=att.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{att.original_filename}"'})


@router.post("/incidents/attachments/{attachment_id}/delete")
async def delete_attachment(attachment_id: int, request: Request,
                            identity: Identity = Depends(require_identity),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                            reason: str = Form("")):
    svc = IncidentService(db, identity)
    att = svc.repos.attachments.get(attachment_id)
    ensure(att is not None and att.owner_type == OWNER_INCIDENT and not att.is_deleted,
           "Adjunto no encontrado.", "not_found")
    inc = svc.get_for_view(att.owner_id)
    is_open = inc.status not in (IncidentStatus.CLOSED.value, IncidentStatus.DISMISSED.value)
    if not is_open:
        ensure(is_admin(identity), "No se pueden eliminar adjuntos de una incidencia cerrada.",
               "delete_attachment_locked")
        if not reason.strip():
            flash(request, "Debe indicar un motivo para eliminar un adjunto bloqueado.", "danger")
            return RedirectResponse(url=f"/incidents/{att.owner_id}", status_code=303)
    else:
        ensure(svc.can_manage(inc) or att.uploaded_by_user_id == identity.user_id,
               "No puede eliminar este adjunto.", "delete_attachment_denied")
    AttachmentService(db, identity).soft_delete(
        att, audit_action=audit.DELETE_INCIDENT_ATTACHMENT,
        reason=reason.strip() or None, ip=client_ip(request))
    flash(request, "Adjunto eliminado.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/incidents/{att.owner_id}", status_code=303)
