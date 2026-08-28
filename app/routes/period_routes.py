"""Academic period management routes (year rollover).

Thin controllers over ``PeriodService``. Also hosts ``/set-period`` — the
top-bar period switcher, which only records a per-session viewing preference
(mirrors ``/set-lang``) and never mutates data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import Forbidden, require_admin_or_university
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.services.audit_service import client_ip
from app.services.period_service import STANDARD_BIMESTERS, PeriodService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, FLASH_WARNING, flash

router = APIRouter(tags=["periods"])


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


def _safe_next(next_url: str) -> str:
    return next_url if next_url.startswith("/") else "/dashboard"


@router.get("/set-period")
def set_period(request: Request, identity: Identity = Depends(require_identity),
               period: str = "", next: str = "/dashboard"):
    """Record the top-bar period selection for this session.

    ``period=""`` (or ``all``) clears the preference and shows every period in
    the platform's list filters again.
    """
    if period in ("", "all"):
        request.session.pop("period_id", None)
    elif period.isdigit():
        request.session["period_id"] = int(period)
    return RedirectResponse(url=_safe_next(next), status_code=303)


@router.get("/periods")
def list_periods(request: Request,
                 identity: Identity = Depends(require_admin_or_university),
                 db: Session = Depends(get_db)):
    svc = PeriodService(db, identity)
    return render(request, "pages/periods_list.html", identity=identity,
                  page_title="Periodos Académicos",
                  page_subtitle="Bimestres del año de internado. Al abrir un nuevo año "
                                "no se borra nada: internos, sedes y tutores se mantienen.",
                  page_icon="calendar3", groups=svc.list_by_year(),
                  next_year=svc.next_year_suggestion(),
                  bimester_count=len(STANDARD_BIMESTERS),
                  can_manage=svc.can_manage())


@router.get("/periods/new")
def new_period(request: Request,
               identity: Identity = Depends(require_admin_or_university),
               db: Session = Depends(get_db)):
    svc = PeriodService(db, identity)
    if not svc.can_manage():
        raise Forbidden(reason="create_period_denied")
    return render(request, "pages/period_form.html", identity=identity,
                  page_title="Nuevo periodo", page_subtitle="Registrar un bimestre.",
                  page_icon="calendar-plus", form={"year": svc.next_year_suggestion()},
                  errors={}, mode="create", bimester_count=len(STANDARD_BIMESTERS))


@router.post("/periods/new")
async def create_period(request: Request,
                        identity: Identity = Depends(require_admin_or_university),
                        db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = PeriodService(db, identity)
    if not svc.can_manage():
        raise Forbidden(reason="create_period_denied")
    form = await _form(request)
    try:
        period = svc.create(form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/period_form.html", identity=identity,
                      page_title="Nuevo periodo", page_subtitle="Registrar un bimestre.",
                      page_icon="calendar-plus", form=form, errors=e.errors,
                      mode="create", bimester_count=len(STANDARD_BIMESTERS),
                      status_code=400)
    flash(request, f"Periodo «{period.name}» creado.", FLASH_SUCCESS)
    return RedirectResponse(url="/periods", status_code=303)


@router.get("/periods/{period_id}/edit")
def edit_period(period_id: int, request: Request,
                identity: Identity = Depends(require_admin_or_university),
                db: Session = Depends(get_db)):
    svc = PeriodService(db, identity)
    if not svc.can_manage():
        raise Forbidden(reason="edit_period_denied")
    p = svc.get(period_id)
    form = {"name": p.name, "code": p.code, "year": p.year, "ordinal": p.ordinal,
            "start_date": p.start_date.isoformat() if p.start_date else "",
            "end_date": p.end_date.isoformat() if p.end_date else ""}
    return render(request, "pages/period_form.html", identity=identity,
                  page_title=f"Editar · {p.name}", page_subtitle="Actualizar el periodo.",
                  page_icon="pencil", form=form, errors={}, mode="edit",
                  period_id=p.id, bimester_count=len(STANDARD_BIMESTERS))


@router.post("/periods/{period_id}/edit")
async def update_period(period_id: int, request: Request,
                        identity: Identity = Depends(require_admin_or_university),
                        db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = PeriodService(db, identity)
    if not svc.can_manage():
        raise Forbidden(reason="edit_period_denied")
    form = await _form(request)
    try:
        svc.update(period_id, form, ip=client_ip(request))
    except ValidationError as e:
        return render(request, "pages/period_form.html", identity=identity,
                      page_title="Editar periodo", page_subtitle="Actualizar el periodo.",
                      page_icon="pencil", form=form, errors=e.errors, mode="edit",
                      period_id=period_id, bimester_count=len(STANDARD_BIMESTERS),
                      status_code=400)
    flash(request, "Periodo actualizado.", FLASH_SUCCESS)
    return RedirectResponse(url="/periods", status_code=303)


@router.post("/periods/{period_id}/set-current")
async def set_current_period(period_id: int, request: Request,
                             identity: Identity = Depends(require_admin_or_university),
                             db: Session = Depends(get_db),
                             _: None = Depends(csrf_protect)):
    svc = PeriodService(db, identity)
    try:
        p = svc.set_current(period_id, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], FLASH_WARNING)
        return RedirectResponse(url="/periods", status_code=303)
    flash(request, f"«{p.name}» es ahora el periodo actual.", FLASH_SUCCESS)
    return RedirectResponse(url="/periods", status_code=303)


@router.post("/periods/{period_id}/delete")
async def delete_period(period_id: int, request: Request,
                        identity: Identity = Depends(require_admin_or_university),
                        db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = PeriodService(db, identity)
    try:
        svc.delete(period_id, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], FLASH_WARNING)
        return RedirectResponse(url="/periods", status_code=303)
    flash(request, "Periodo eliminado.", FLASH_SUCCESS)
    return RedirectResponse(url="/periods", status_code=303)


@router.post("/periods/generate-year")
async def generate_year(request: Request,
                        identity: Identity = Depends(require_admin_or_university),
                        db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                        year: str = Form(...), set_current: str = Form("")):
    svc = PeriodService(db, identity)
    try:
        result = svc.generate_year(int(year) if year.strip().isdigit() else -1,
                                   ip=client_ip(request),
                                   set_current=(set_current == "1"))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], FLASH_WARNING)
        return RedirectResponse(url="/periods", status_code=303)
    msg = f"Año {year}: {len(result['created'])} periodo(s) creado(s)."
    if result["skipped"]:
        msg += f" {len(result['skipped'])} ya existían."
    flash(request, msg, FLASH_SUCCESS)
    return RedirectResponse(url="/periods", status_code=303)
