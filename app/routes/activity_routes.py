"""Activity catalog + student activity tracking routes (Batch 2C)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import Forbidden, require_admin_or_university
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.models.user import ROLE_STUDENT, ROLE_TUTOR
from app.services.activity_catalog_service import ActivityCatalogService
from app.services.audit_service import client_ip
from app.services.rotation_service import RotationService
from app.services.student_activity_service import StudentActivityService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash, paginate

router = APIRouter(tags=["activities"])
PER_PAGE = 15


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


# --- Catalog -----------------------------------------------------------------
@router.get("/activities")
def catalog_list(request: Request, identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db),
                 q: str = "", rotation: str = "", category: str = "",
                 target_type: str = "", verification: str = "", active: str = "",
                 source: str = "", page: int = 1):
    svc = ActivityCatalogService(db, identity)
    items = svc.list_definitions(
        query=q or None, rotation_type_id=int(rotation) if rotation else None,
        category=category or None, target_type=target_type or None,
        requires_verification={"1": True, "0": False}.get(verification, None),
        active={"1": True, "0": False}.get(active, None), provisional=source or None,
    )
    paged = paginate(items, page, PER_PAGE)
    base_qs = "".join(f"{k}={v}&" for k, v in
                      [("q", q), ("rotation", rotation), ("category", category),
                       ("target_type", target_type), ("verification", verification),
                       ("active", active), ("source", source)] if v)
    return render(request, "pages/activity_catalog_list.html", identity=identity,
                  page_title="Catálogo de Actividades",
                  page_subtitle="Actividades y procedimientos oficiales por rotación.",
                  page_icon="clipboard-check", page=paged, options=svc.form_options(),
                  filters={"q": q, "rotation": rotation, "category": category,
                           "target_type": target_type, "verification": verification,
                           "active": active, "source": source},
                  base_qs=base_qs, can_manage=svc.can_manage())


@router.get("/activities/import")
def import_preview(request: Request, identity: Identity = Depends(require_admin_or_university),
                   db: Session = Depends(get_db)):
    svc = ActivityCatalogService(db, identity)
    data = svc.preview_import()
    return render(request, "pages/activity_catalog_import.html", identity=identity,
                  page_title="Importar catálogo oficial",
                  page_subtitle="Vista previa de sincronización con el catálogo oficial.",
                  page_icon="cloud-download", **data, can_confirm=svc.can_manage())


@router.post("/activities/import/confirm")
async def import_confirm(request: Request, identity: Identity = Depends(require_admin_or_university),
                         db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = ActivityCatalogService(db, identity)
    if not svc.can_manage():
        raise Forbidden(reason="import_catalog_denied")
    created = svc.confirm_import(ip=client_ip(request))
    flash(request, f"Importación completada: {created} definición(es) nueva(s).", FLASH_SUCCESS)
    return RedirectResponse(url="/activities", status_code=303)


@router.get("/activities/new")
def new_definition(request: Request, identity: Identity = Depends(require_admin_or_university),
                   db: Session = Depends(get_db)):
    svc = ActivityCatalogService(db, identity)
    return render(request, "pages/activity_definition_form.html", identity=identity,
                  page_title="Nueva definición", page_subtitle="Registrar actividad/procedimiento.",
                  page_icon="plus-lg", options=svc.form_options(), form={}, errors={}, mode="create")


@router.post("/activities/new")
async def create_definition(request: Request, identity: Identity = Depends(require_admin_or_university),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = ActivityCatalogService(db, identity)
    form = await _form(request)
    try:
        d = svc.create(form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/activity_definition_form.html", identity=identity,
                      page_title="Nueva definición", page_subtitle="Registrar actividad/procedimiento.",
                      page_icon="plus-lg", options=svc.form_options(), form=form, errors=e.errors,
                      mode="create", status_code=400)
    flash(request, f"Definición «{d.name}» creada.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/activities/{d.id}", status_code=303)


@router.get("/activities/mine")
def my_activities(request: Request, identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    svc = StudentActivityService(db, identity)
    if identity.role_code != ROLE_STUDENT:
        raise Forbidden(reason="not_a_student")
    student_ids = svc._own_student_ids()
    entries = []
    for sid in student_ids:
        entries.extend(svc.repos.student_activities.for_student(sid))
    return render(request, "pages/activity_my_list.html", identity=identity,
                  page_title="Mis Actividades", page_subtitle="Registro personal de actividades.",
                  page_icon="journal-check", entries=entries)


@router.get("/activities/verify")
def verify_inbox(request: Request, identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    svc = StudentActivityService(db, identity)
    if identity.role_code not in (ROLE_TUTOR, "admin", "university_coordinator"):
        raise Forbidden(reason="verify_inbox_denied")
    entries = svc.inbox()
    return render(request, "pages/activity_verify_inbox.html", identity=identity,
                  page_title="Bandeja de Verificación",
                  page_subtitle="Actividades pendientes de revisión.",
                  page_icon="inbox", entries=entries)


@router.get("/activities/monitor")
def monitor(request: Request, identity: Identity = Depends(require_identity),
           db: Session = Depends(get_db)):
    if identity.role_code in (ROLE_STUDENT, ROLE_TUTOR):
        raise Forbidden(reason="monitor_denied")
    svc = StudentActivityService(db, identity)
    data = svc.build_monitoring()
    return render(request, "pages/activity_monitor.html", identity=identity,
                  page_title="Monitoreo de Actividades",
                  page_subtitle="Indicadores de progreso y riesgo por interno, tutor y sede.",
                  page_icon="graph-up", **data)


# NOTE: this parameterized route (/activities/{definition_id}) must stay AFTER
# every fixed-path "/activities/..." GET route above (mine, verify, monitor) —
# FastAPI matches path operations in registration order, so a fixed path
# registered later would otherwise be swallowed by this int converter and fail
# with 422 (e.g. "monitor" cannot parse as int).
@router.get("/activities/{definition_id}")
def definition_detail(definition_id: int, request: Request,
                      identity: Identity = Depends(require_identity),
                      db: Session = Depends(get_db)):
    svc = ActivityCatalogService(db, identity)
    d = svc.get_for_view(definition_id)
    return render(request, "pages/activity_definition_detail.html", identity=identity,
                  page_title=d.name, page_subtitle="Definición de actividad.",
                  page_icon="clipboard-check", d=d, can_manage=svc.can_manage())


@router.get("/activities/{definition_id}/edit")
def edit_definition(definition_id: int, request: Request,
                    identity: Identity = Depends(require_admin_or_university),
                    db: Session = Depends(get_db)):
    svc = ActivityCatalogService(db, identity)
    d = svc.get_for_view(definition_id)
    form = {"code": d.code, "name": d.name, "category": d.category,
            "description": d.description, "target_type": d.target_type,
            "target_count": d.target_count, "unit_label": d.unit_label,
            "rotation_type_id": d.rotation_type_id,
            "requires_tutor_verification": "1" if d.requires_tutor_verification else "",
            "evidence_policy": d.evidence_policy,
            "supervision_required": "1" if d.supervision_required else "",
            "is_provisional": "1" if d.is_provisional else "", "display_order": d.display_order}
    return render(request, "pages/activity_definition_form.html", identity=identity,
                  page_title=f"Editar · {d.name}", page_subtitle="Actualizar definición.",
                  page_icon="pencil", options=svc.form_options(), form=form, errors={},
                  mode="edit", definition_id=d.id)


@router.post("/activities/{definition_id}/edit")
async def update_definition(definition_id: int, request: Request,
                            identity: Identity = Depends(require_admin_or_university),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = ActivityCatalogService(db, identity)
    form = await _form(request)
    try:
        svc.update(definition_id, form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/activity_definition_form.html", identity=identity,
                      page_title="Editar definición", page_subtitle="Actualizar definición.",
                      page_icon="pencil", options=svc.form_options(), form=form, errors=e.errors,
                      mode="edit", definition_id=definition_id, status_code=400)
    flash(request, "Definición actualizada.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/activities/{definition_id}", status_code=303)


@router.post("/activities/{definition_id}/toggle")
async def toggle_definition(definition_id: int, request: Request,
                            identity: Identity = Depends(require_admin_or_university),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                            active: str = Form("1")):
    svc = ActivityCatalogService(db, identity)
    d = svc.set_active(definition_id, active == "1", ip=client_ip(request))
    flash(request, f"Definición {'activada' if d.is_active else 'desactivada'}.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/activities/{definition_id}", status_code=303)


# --- Student entries -----------------------------------------------------------
@router.post("/rotations/{assignment_id}/activities/new")
async def create_entry(assignment_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = StudentActivityService(db, identity)
    form = await _form(request)
    try:
        svc.create(assignment_id, form, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/rotations/{assignment_id}#actividades", status_code=303)
    flash(request, "Actividad registrada y enviada a verificación.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/rotations/{assignment_id}#actividades", status_code=303)


@router.get("/activities/entries/{activity_id}")
def entry_detail(activity_id: int, request: Request,
                 identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    svc = StudentActivityService(db, identity)
    entry = svc.get_for_view(activity_id)
    return render(request, "pages/activity_entry_detail.html", identity=identity,
                  page_title=entry.definition.name, page_subtitle="Registro de actividad.",
                  page_icon="journal-check", entry=entry,
                  can_edit=(entry.student_id in svc._own_student_ids()
                           and entry.verification_status in ("pending", "rejected")),
                  can_cancel=(entry.student_id in svc._own_student_ids()
                             and entry.verification_status == "pending"),
                  can_review=svc.can_review(entry))


@router.get("/activities/entries/{activity_id}/edit")
def edit_entry(activity_id: int, request: Request,
               identity: Identity = Depends(require_identity),
               db: Session = Depends(get_db)):
    svc = StudentActivityService(db, identity)
    entry = svc.get_for_view(activity_id)
    if entry.student_id not in svc._own_student_ids() or \
            entry.verification_status not in ("pending", "rejected"):
        raise Forbidden(reason="edit_activity_denied")
    form = {"definition_id": entry.definition_id,
            "logged_on": entry.logged_on.isoformat() if entry.logged_on else "",
            "performed_count": entry.performed_count, "notes": entry.notes or "",
            "evidence_reference": entry.evidence_reference or ""}
    opts = svc.form_options(entry.assignment)
    return render(request, "pages/activity_entry_form.html", identity=identity,
                  page_title="Editar actividad", page_subtitle="Actualizar registro.",
                  page_icon="pencil", options=opts, form=form, errors={}, mode="edit",
                  activity_id=entry.id, assignment=entry.assignment)


@router.post("/activities/entries/{activity_id}/edit")
async def update_entry(activity_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = StudentActivityService(db, identity)
    form = await _form(request)
    try:
        svc.update(activity_id, form, ip=client_ip(request))
    except ValidationError as e:
        entry = svc.repos.student_activities.get_full(activity_id)
        opts = svc.form_options(entry.assignment) if entry else {}
        return render(request, "pages/activity_entry_form.html", identity=identity,
                      page_title="Editar actividad", page_subtitle="Actualizar registro.",
                      page_icon="pencil", options=opts, form=form, errors=e.errors, mode="edit",
                      activity_id=activity_id, assignment=entry.assignment if entry else None,
                      status_code=400)
    flash(request, "Actividad actualizada.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/activities/entries/{activity_id}", status_code=303)


@router.post("/activities/entries/{activity_id}/cancel")
async def cancel_entry(activity_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = StudentActivityService(db, identity)
    try:
        svc.cancel(activity_id, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url=f"/activities/entries/{activity_id}", status_code=303)
    flash(request, "Actividad cancelada.", FLASH_SUCCESS)
    return RedirectResponse(url="/activities/mine", status_code=303)


# --- Tutor verification --------------------------------------------------------
@router.post("/activities/entries/{activity_id}/verify")
async def verify_entry(activity_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = StudentActivityService(db, identity)
    try:
        svc.verify(activity_id, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url="/activities/verify", status_code=303)
    flash(request, "Actividad verificada.", FLASH_SUCCESS)
    return RedirectResponse(url="/activities/verify", status_code=303)


@router.post("/activities/entries/{activity_id}/reject")
async def reject_entry(activity_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                       comment: str = Form("")):
    svc = StudentActivityService(db, identity)
    try:
        svc.reject(activity_id, comment, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url="/activities/verify", status_code=303)
    flash(request, "Actividad rechazada.", FLASH_SUCCESS)
    return RedirectResponse(url="/activities/verify", status_code=303)


@router.post("/activities/verify/bulk")
async def bulk_verify(request: Request, identity: Identity = Depends(require_identity),
                      db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                      activity_ids: list[str] = Form(default=[])):
    svc = StudentActivityService(db, identity)
    ids = [int(i) for i in activity_ids]
    count = svc.bulk_verify(ids, ip=client_ip(request))
    flash(request, f"{count} actividad(es) verificada(s) en lote.", FLASH_SUCCESS)
    return RedirectResponse(url="/activities/verify", status_code=303)


@router.post("/activities/entries/{activity_id}/reopen")
async def reopen_entry(activity_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                       reason: str = Form("")):
    svc = StudentActivityService(db, identity)
    try:
        svc.reopen(activity_id, reason, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url=f"/activities/entries/{activity_id}", status_code=303)
    flash(request, "Actividad reabierta.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/activities/entries/{activity_id}", status_code=303)
