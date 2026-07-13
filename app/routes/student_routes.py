"""Intern student management routes (Part 2).

Thin controllers over ``StudentService``. All mutations are POST and depend on
``csrf_protect``; list/detail are GET. Scope and validation live in the service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import Forbidden, is_global_viewer
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.models.user import ROLE_SEDE_COORDINATOR
from app.services.audit_service import client_ip
from app.services.student_service import StudentService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash, paginate

router = APIRouter(tags=["students"])

PER_PAGE = 10


def _can_manage(identity: Identity) -> bool:
    return is_global_viewer(identity) or identity.role_code == ROLE_SEDE_COORDINATOR


@router.get("/students")
def list_students(request: Request, identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db),
                  q: str = "", cycle: str = "", institution: str = "",
                  sede: str = "", profile: str = "", active: str = "", page: int = 1):
    service = StudentService(db, identity)
    filters = {
        "query": q or None,
        "cycle": cycle or None,
        "institution_code": institution or None,
        "sede_id": int(sede) if sede else None,
        "profile_status": profile or None,
        "active": {"1": True, "0": False}.get(active, None),
    }
    students = service.list_students(**filters)
    paged = paginate(students, page, PER_PAGE)
    opts = service.form_options()
    # Preserve filter state in pagination links.
    base_qs = "".join(
        f"{k}={v}&" for k, v in
        [("q", q), ("cycle", cycle), ("institution", institution),
         ("sede", sede), ("profile", profile), ("active", active)] if v
    )
    return render(request, "pages/students_list.html", identity=identity,
                  page_title="Internos",
                  page_subtitle="Registro de internos de medicina (ciclos 13 y 14).",
                  page_icon="mortarboard", page=paged, options=opts,
                  filters={"q": q, "cycle": cycle, "institution": institution,
                           "sede": sede, "profile": profile, "active": active},
                  base_qs=base_qs, can_manage=_can_manage(identity))


@router.get("/students/new")
def new_student(request: Request, identity: Identity = Depends(require_identity),
                db: Session = Depends(get_db)):
    if not _can_manage(identity):
        raise Forbidden(reason="create_student_denied")
    service = StudentService(db, identity)
    return render(request, "pages/student_form.html", identity=identity,
                  page_title="Nuevo interno", page_subtitle="Registrar un interno.",
                  page_icon="person-plus", options=service.form_options(),
                  form={}, errors={}, mode="create")


@router.post("/students/new")
async def create_student(request: Request, identity: Identity = Depends(require_identity),
                         db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    if not _can_manage(identity):
        raise Forbidden(reason="create_student_denied")
    service = StudentService(db, identity)
    form = await _read_form(request)
    try:
        student = service.create(form, ip=client_ip(request),
                                 override_reason=form.get("override_reason") or None)
    except ValidationError as e:
        return render(request, "pages/student_form.html", identity=identity,
                      page_title="Nuevo interno", page_subtitle="Registrar un interno.",
                      page_icon="person-plus", options=service.form_options(),
                      form=form, errors=e.errors, mode="create", status_code=400)
    flash(request, f"Interno «{student.full_name}» creado correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/students/{student.id}", status_code=303)


@router.get("/students/{student_id}")
def student_detail(student_id: int, request: Request,
                   identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db)):
    service = StudentService(db, identity)
    data = service.build_detail(student_id)
    return render(request, "pages/student_detail.html", identity=identity,
                  page_title=data["student"].full_name,
                  page_subtitle="Ficha del interno.", page_icon="mortarboard", **data)


@router.get("/students/{student_id}/edit")
def edit_student(student_id: int, request: Request,
                 identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    service = StudentService(db, identity)
    student = service.get_for_view(student_id)  # also checks view scope
    from app.authorization import can_edit_student
    if not can_edit_student(identity, student, service.repos):
        raise Forbidden(reason="edit_student_denied")
    form = {
        "student_code": student.student_code, "full_name": student.full_name,
        "email": student.email, "document_id": student.document_id,
        "phone": student.phone, "cycle": student.cycle,
        "profile_status": student.profile_status,
        "institution_type_id": student.institution_type_id, "sede_id": student.sede_id,
        "internship_start": student.internship_start.isoformat() if student.internship_start else "",
        "internship_end": student.internship_end.isoformat() if student.internship_end else "",
    }
    return render(request, "pages/student_form.html", identity=identity,
                  page_title=f"Editar · {student.full_name}",
                  page_subtitle="Actualizar datos del interno.", page_icon="pencil",
                  options=service.form_options(), form=form, errors={},
                  mode="edit", student_id=student.id,
                  limited=(identity.role_code == ROLE_SEDE_COORDINATOR and not is_global_viewer(identity)))


@router.post("/students/{student_id}/edit")
async def update_student(student_id: int, request: Request,
                         identity: Identity = Depends(require_identity),
                         db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    service = StudentService(db, identity)
    form = await _read_form(request)
    try:
        service.update(student_id, form, ip=client_ip(request),
                       override_reason=form.get("override_reason") or None)
    except ValidationError as e:
        return render(request, "pages/student_form.html", identity=identity,
                      page_title="Editar interno", page_subtitle="Actualizar datos.",
                      page_icon="pencil", options=service.form_options(),
                      form=form, errors=e.errors, mode="edit", student_id=student_id,
                      status_code=400)
    flash(request, "Interno actualizado correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/students/{student_id}", status_code=303)


@router.post("/students/{student_id}/toggle")
def toggle_student(student_id: int, request: Request,
                   identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                   active: str = Form("1")):
    service = StudentService(db, identity)
    student = service.set_active(student_id, active == "1", ip=client_ip(request))
    state = "activado" if student.is_active else "desactivado"
    flash(request, f"Interno {state} correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/students/{student_id}", status_code=303)


@router.post("/students/{student_id}/delete")
def delete_student(student_id: int, request: Request,
                   identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                   reason: str = Form("")):
    service = StudentService(db, identity)
    try:
        service.soft_delete(student_id, reason, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/students/{student_id}", status_code=303)
    flash(request, "Interno eliminado (baja lógica).", FLASH_SUCCESS)
    return RedirectResponse(url="/students", status_code=303)


async def _read_form(request: Request) -> dict:
    """Read the submitted form body into a plain dict.

    ``csrf_protect`` already awaited ``request.form()``; Starlette caches it, so
    this returns the same parsed data without re-reading the stream.
    """
    form = await request.form()
    return {k: v for k, v in form.multi_items()}
