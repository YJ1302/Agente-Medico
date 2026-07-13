"""Sede management routes (Batch 2A). Thin controllers over ``SedeService``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import Forbidden
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.services.audit_service import client_ip
from app.services.sede_service import SedeService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash, paginate

router = APIRouter(tags=["sedes"])
PER_PAGE = 10


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


@router.get("/sedes")
def list_sedes(request: Request, identity: Identity = Depends(require_identity),
               db: Session = Depends(get_db),
               q: str = "", institution: str = "", sede_type: str = "",
               active: str = "", coordinator: str = "", page: int = 1):
    service = SedeService(db, identity)
    sedes = service.list_sedes(
        query=q or None, institution_code=institution or None,
        sede_type=sede_type or None,
        active={"1": True, "0": False}.get(active, None),
        has_coordinator=coordinator or None,
    )
    paged = paginate(sedes, page, PER_PAGE)
    base_qs = "".join(f"{k}={v}&" for k, v in
                      [("q", q), ("institution", institution), ("sede_type", sede_type),
                       ("active", active), ("coordinator", coordinator)] if v)
    # Precompute coordinator presence for the list rows.
    coord_map = {
        s.id: service.repos.sede_coordinators.active_principal_for_sede(s.id)
        for s in paged.items
    }
    return render(request, "pages/sedes_list.html", identity=identity,
                  page_title="Sedes",
                  page_subtitle="Hospitales y centros de salud (MINSA / EsSalud).",
                  page_icon="hospital", page=paged, options=service.form_options(),
                  filters={"q": q, "institution": institution, "sede_type": sede_type,
                           "active": active, "coordinator": coordinator},
                  base_qs=base_qs, can_manage=service.can_manage(), coord_map=coord_map)


@router.get("/sedes/new")
def new_sede(request: Request, identity: Identity = Depends(require_identity),
             db: Session = Depends(get_db)):
    service = SedeService(db, identity)
    if not service.can_manage():
        raise Forbidden(reason="create_sede_denied")
    return render(request, "pages/sede_form.html", identity=identity,
                  page_title="Nueva sede", page_subtitle="Registrar una sede docente.",
                  page_icon="hospital-add" if False else "hospital",
                  options=service.form_options(), form={}, errors={}, mode="create")


@router.post("/sedes/new")
async def create_sede(request: Request, identity: Identity = Depends(require_identity),
                      db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    service = SedeService(db, identity)
    if not service.can_manage():
        raise Forbidden(reason="create_sede_denied")
    form = await _form(request)
    try:
        sede = service.create(form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/sede_form.html", identity=identity,
                      page_title="Nueva sede", page_subtitle="Registrar una sede docente.",
                      page_icon="hospital", options=service.form_options(),
                      form=form, errors=e.errors, mode="create", status_code=400)
    flash(request, f"Sede «{sede.name}» creada correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/sedes/{sede.id}", status_code=303)


@router.get("/sedes/{sede_id}")
def sede_detail(sede_id: int, request: Request,
                identity: Identity = Depends(require_identity),
                db: Session = Depends(get_db)):
    service = SedeService(db, identity)
    data = service.build_detail(sede_id)
    return render(request, "pages/sede_detail.html", identity=identity,
                  page_title=data["sede"].name, page_subtitle="Ficha de la sede.",
                  page_icon="hospital", **data)


@router.get("/sedes/{sede_id}/edit")
def edit_sede(sede_id: int, request: Request,
              identity: Identity = Depends(require_identity),
              db: Session = Depends(get_db)):
    service = SedeService(db, identity)
    sede = service.get_for_view(sede_id)
    if not service.can_manage():
        raise Forbidden(reason="edit_sede_denied")
    form = {"name": sede.name, "short_name": sede.short_name, "sede_type": sede.sede_type,
            "institution_type_id": sede.institution_type_id, "city": sede.city,
            "address": sede.address}
    return render(request, "pages/sede_form.html", identity=identity,
                  page_title=f"Editar · {sede.name}", page_subtitle="Actualizar datos de la sede.",
                  page_icon="pencil", options=service.form_options(), form=form,
                  errors={}, mode="edit", sede_id=sede.id)


@router.post("/sedes/{sede_id}/edit")
async def update_sede(sede_id: int, request: Request,
                      identity: Identity = Depends(require_identity),
                      db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    service = SedeService(db, identity)
    form = await _form(request)
    try:
        service.update(sede_id, form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/sede_form.html", identity=identity,
                      page_title="Editar sede", page_subtitle="Actualizar datos de la sede.",
                      page_icon="pencil", options=service.form_options(),
                      form=form, errors=e.errors, mode="edit", sede_id=sede_id,
                      status_code=400)
    flash(request, "Sede actualizada correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/sedes/{sede_id}", status_code=303)


@router.post("/sedes/{sede_id}/toggle")
async def toggle_sede(sede_id: int, request: Request,
                      identity: Identity = Depends(require_identity),
                      db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                      active: str = Form("1"), force: str = Form(""),
                      reason: str = Form("")):
    service = SedeService(db, identity)
    try:
        sede = service.set_active(sede_id, active == "1", force=(force == "1"),
                                  reason=reason, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url=f"/sedes/{sede_id}", status_code=303)
    state = "activada" if sede.is_active else "desactivada"
    flash(request, f"Sede {state} correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/sedes/{sede_id}", status_code=303)


@router.post("/sedes/{sede_id}/delete")
async def delete_sede(sede_id: int, request: Request,
                      identity: Identity = Depends(require_identity),
                      db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                      reason: str = Form("")):
    service = SedeService(db, identity)
    try:
        service.soft_delete(sede_id, reason, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/sedes/{sede_id}", status_code=303)
    flash(request, "Sede eliminada (baja lógica).", FLASH_SUCCESS)
    return RedirectResponse(url="/sedes", status_code=303)
