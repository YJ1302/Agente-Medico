"""Tutor management routes (Batch 2A)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import Forbidden, require_management
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.services.audit_service import client_ip
from app.services.staff_service import TutorService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash, paginate

router = APIRouter(tags=["tutors"])
PER_PAGE = 10


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


@router.get("/tutors")
def list_tutors(request: Request, identity: Identity = Depends(require_management),
                db: Session = Depends(get_db),
                q: str = "", sede: str = "", service: str = "", active: str = "",
                assignments: str = "", workload: str = "", page: int = 1):
    svc = TutorService(db, identity)
    rows = svc.list_tutors(
        query=q or None, sede_id=int(sede) if sede else None,
        service=service or None, active={"1": True, "0": False}.get(active, None),
        has_assignments=assignments or None, workload=workload or None)
    paged = paginate(rows, page, PER_PAGE)
    base_qs = "".join(f"{k}={v}&" for k, v in
                      [("q", q), ("sede", sede), ("service", service), ("active", active),
                       ("assignments", assignments), ("workload", workload)] if v)
    return render(request, "pages/tutors_list.html", identity=identity,
                  page_title="Tutores", page_subtitle="Tutores de rotación por sede y servicio.",
                  page_icon="people", page=paged, options=svc.form_options(),
                  filters={"q": q, "sede": sede, "service": service, "active": active,
                           "assignments": assignments, "workload": workload},
                  base_qs=base_qs, can_manage=svc.can_manage(), active_tab="tutors")


@router.get("/tutors/new")
def new_tutor(request: Request, identity: Identity = Depends(require_management),
              db: Session = Depends(get_db)):
    svc = TutorService(db, identity)
    if not svc.can_manage():
        raise Forbidden(reason="create_tutor_denied")
    return render(request, "pages/tutor_form.html", identity=identity,
                  page_title="Nuevo tutor", page_subtitle="Registrar tutor de rotación.",
                  page_icon="person-plus", options=svc.form_options(), form={}, errors={},
                  mode="create")


@router.post("/tutors/new")
async def create_tutor(request: Request, identity: Identity = Depends(require_management),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = TutorService(db, identity)
    if not svc.can_manage():
        raise Forbidden(reason="create_tutor_denied")
    form = await _form(request)
    try:
        tutor, generated = svc.create(form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/tutor_form.html", identity=identity,
                      page_title="Nuevo tutor", page_subtitle="Registrar tutor de rotación.",
                      page_icon="person-plus", options=svc.form_options(), form=form,
                      errors=e.errors, mode="create", status_code=400)
    msg = f"Tutor «{tutor.user.full_name}» creado."
    if generated:
        msg += f" Contraseña temporal: {generated}"
    flash(request, msg, FLASH_SUCCESS)
    return RedirectResponse(url=f"/tutors/{tutor.id}", status_code=303)


@router.get("/tutors/{tutor_id}")
def tutor_detail(tutor_id: int, request: Request,
                 identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    svc = TutorService(db, identity)
    data = svc.build_detail(tutor_id)
    return render(request, "pages/tutor_detail.html", identity=identity,
                  page_title=data["tutor"].user.full_name,
                  page_subtitle="Ficha del tutor.", page_icon="person-badge", **data)


@router.get("/tutors/{tutor_id}/edit")
def edit_tutor(tutor_id: int, request: Request,
               identity: Identity = Depends(require_identity),
               db: Session = Depends(get_db)):
    svc = TutorService(db, identity)
    tutor = svc.get_for_view(tutor_id)
    if not svc.can_manage_sede_fields(tutor):
        raise Forbidden(reason="edit_tutor_denied")
    form = {"full_name": tutor.user.full_name, "email": tutor.user.email,
            "phone": tutor.user.phone, "specialty": tutor.specialty, "service": tutor.service,
            "contact_phone": tutor.contact_phone, "sede_id": tutor.sede_id}
    return render(request, "pages/tutor_form.html", identity=identity,
                  page_title=f"Editar · {tutor.user.full_name}", page_subtitle="Actualizar tutor.",
                  page_icon="pencil", options=svc.form_options(), form=form, errors={},
                  mode="edit", tutor_id=tutor.id, limited=not svc.can_manage())


@router.post("/tutors/{tutor_id}/edit")
async def update_tutor(tutor_id: int, request: Request,
                       identity: Identity = Depends(require_identity),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = TutorService(db, identity)
    form = await _form(request)
    try:
        svc.update(tutor_id, form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/tutor_form.html", identity=identity,
                      page_title="Editar tutor", page_subtitle="Actualizar tutor.",
                      page_icon="pencil", options=svc.form_options(), form=form,
                      errors=e.errors, mode="edit", tutor_id=tutor_id, status_code=400)
    flash(request, "Tutor actualizado correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/tutors/{tutor_id}", status_code=303)


@router.post("/tutors/{tutor_id}/toggle")
async def toggle_tutor(tutor_id: int, request: Request,
                       identity: Identity = Depends(require_management),
                       db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                       active: str = Form("1"), force: str = Form(""), reason: str = Form("")):
    svc = TutorService(db, identity)
    try:
        tutor = svc.set_active(tutor_id, active == "1", force=(force == "1"),
                               reason=reason, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url=f"/tutors/{tutor_id}", status_code=303)
    flash(request, f"Tutor {'activado' if tutor.is_active else 'desactivado'} correctamente.",
          FLASH_SUCCESS)
    return RedirectResponse(url=f"/tutors/{tutor_id}", status_code=303)
