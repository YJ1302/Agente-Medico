"""Sede Coordinator management routes (Batch 2A)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import Forbidden, require_management
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.services.audit_service import client_ip
from app.services.staff_service import CoordinatorService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, FLASH_WARNING, flash, paginate

router = APIRouter(tags=["coordinators"])
PER_PAGE = 10


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


@router.get("/coordinators")
def list_coordinators(request: Request, identity: Identity = Depends(require_management),
                      db: Session = Depends(get_db),
                      q: str = "", sede: str = "", active: str = "", page: int = 1):
    service = CoordinatorService(db, identity)
    coords = service.list_coordinators(
        query=q or None, sede_id=int(sede) if sede else None,
        active={"1": True, "0": False}.get(active, None))
    paged = paginate(coords, page, PER_PAGE)
    base_qs = "".join(f"{k}={v}&" for k, v in
                      [("q", q), ("sede", sede), ("active", active)] if v)
    return render(request, "pages/coordinators_list.html", identity=identity,
                  page_title="Coordinadores de Sede",
                  page_subtitle="Docentes coordinadores de las sedes hospitalarias.",
                  page_icon="person-badge", page=paged, options=service.form_options(),
                  filters={"q": q, "sede": sede, "active": active}, base_qs=base_qs,
                  can_manage=service.can_manage(), active_tab="coordinators")


@router.get("/coordinators/new")
def new_coordinator(request: Request, identity: Identity = Depends(require_management),
                    db: Session = Depends(get_db)):
    service = CoordinatorService(db, identity)
    if not service.can_manage():
        raise Forbidden(reason="create_coord_denied")
    return render(request, "pages/coordinator_form.html", identity=identity,
                  page_title="Nuevo coordinador", page_subtitle="Registrar coordinador de sede.",
                  page_icon="person-plus", options=service.form_options(), form={},
                  errors={}, mode="create")


@router.post("/coordinators/new")
async def create_coordinator(request: Request, identity: Identity = Depends(require_management),
                             db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    service = CoordinatorService(db, identity)
    if not service.can_manage():
        raise Forbidden(reason="create_coord_denied")
    form = await _form(request)
    try:
        coord, generated = service.create(form, replace=(form.get("replace") == "1"),
                                          ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/coordinator_form.html", identity=identity,
                      page_title="Nuevo coordinador", page_subtitle="Registrar coordinador de sede.",
                      page_icon="person-plus", options=service.form_options(),
                      form=form, errors=e.errors, mode="create", status_code=400)
    msg = f"Coordinador «{coord.user.full_name}» creado."
    if generated:
        msg += f" Contraseña temporal: {generated}"
    flash(request, msg, FLASH_SUCCESS)
    return RedirectResponse(url=f"/coordinators/{coord.id}", status_code=303)


@router.get("/coordinators/{coord_id}")
def coordinator_detail(coord_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db)):
    service = CoordinatorService(db, identity)
    data = service.build_detail(coord_id)
    return render(request, "pages/coordinator_detail.html", identity=identity,
                  page_title=data["coord"].user.full_name,
                  page_subtitle="Ficha del coordinador de sede.", page_icon="person-badge", **data)


@router.get("/coordinators/{coord_id}/edit")
def edit_coordinator(coord_id: int, request: Request,
                     identity: Identity = Depends(require_management),
                     db: Session = Depends(get_db)):
    service = CoordinatorService(db, identity)
    coord = service.get_for_view(coord_id)
    if not service.can_manage():
        raise Forbidden(reason="edit_coord_denied")
    form = {"full_name": coord.user.full_name, "email": coord.user.email,
            "phone": coord.user.phone, "specialty": coord.specialty,
            "office_phone": coord.office_phone, "sede_id": coord.sede_id}
    return render(request, "pages/coordinator_form.html", identity=identity,
                  page_title=f"Editar · {coord.user.full_name}",
                  page_subtitle="Actualizar coordinador.", page_icon="pencil",
                  options=service.form_options(), form=form, errors={}, mode="edit",
                  coord_id=coord.id)


@router.post("/coordinators/{coord_id}/edit")
async def update_coordinator(coord_id: int, request: Request,
                             identity: Identity = Depends(require_management),
                             db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    service = CoordinatorService(db, identity)
    form = await _form(request)
    try:
        service.update(coord_id, form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/coordinator_form.html", identity=identity,
                      page_title="Editar coordinador", page_subtitle="Actualizar coordinador.",
                      page_icon="pencil", options=service.form_options(), form=form,
                      errors=e.errors, mode="edit", coord_id=coord_id, status_code=400)
    flash(request, "Coordinador actualizado correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/coordinators/{coord_id}", status_code=303)


@router.post("/coordinators/{coord_id}/toggle")
async def toggle_coordinator(coord_id: int, request: Request,
                             identity: Identity = Depends(require_management),
                             db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                             active: str = Form("1")):
    service = CoordinatorService(db, identity)
    coord = service.set_active(coord_id, active == "1", ip=client_ip(request))
    flash(request, f"Coordinador {'activado' if coord.is_active else 'desactivado'} correctamente.",
          FLASH_SUCCESS)
    return RedirectResponse(url=f"/coordinators/{coord_id}", status_code=303)
