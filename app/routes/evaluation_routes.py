"""Digital evaluation workflow routes (Batch 2D). Thin controllers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.services.audit_service import client_ip
from app.services.evaluation_service import AREAS, EvaluationService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash, paginate

router = APIRouter(tags=["evaluations"])
PER_PAGE = 15


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


def _rerender_detail(request, identity, svc, evaluation_id, errors):
    data = svc.build_detail(evaluation_id)
    ev = data["ev"]
    return render(request, "pages/evaluation_detail.html", identity=identity,
                  page_title=f"Evaluación · {ev.student.full_name if ev.student else ''}",
                  page_subtitle=ev.assignment.rotation_type.name if ev.assignment and ev.assignment.rotation_type else "",
                  page_icon="check2-square", errors=errors, status_code=400, **data)


@router.get("/evaluations")
def list_evaluations(request: Request, identity: Identity = Depends(require_identity),
                     db: Session = Depends(get_db), status: str = "", page: int = 1):
    svc = EvaluationService(db, identity)
    rows = svc.list_evaluations(status=status or None)
    paged = paginate(rows, page, PER_PAGE)
    base_qs = f"status={status}&" if status else ""
    return render(request, "pages/evaluations_list.html", identity=identity,
                  page_title="Evaluaciones",
                  page_subtitle="Evaluaciones de fin de rotación (Conocimientos, Desempeño, Actitud).",
                  page_icon="check2-square", page=paged, status=status, base_qs=base_qs)


@router.get("/evaluations/{evaluation_id}")
def evaluation_detail(evaluation_id: int, request: Request,
                      identity: Identity = Depends(require_identity),
                      db: Session = Depends(get_db)):
    svc = EvaluationService(db, identity)
    data = svc.build_detail(evaluation_id)
    ev = data["ev"]
    return render(request, "pages/evaluation_detail.html", identity=identity,
                  page_title=f"Evaluación · {ev.student.full_name if ev.student else ''}",
                  page_subtitle=ev.assignment.rotation_type.name if ev.assignment and ev.assignment.rotation_type else "",
                  page_icon="check2-square", errors={}, **data)


@router.get("/evaluations/{evaluation_id}/print")
def evaluation_print(evaluation_id: int, request: Request,
                     identity: Identity = Depends(require_identity),
                     db: Session = Depends(get_db)):
    svc = EvaluationService(db, identity)
    ev = svc.get_for_view(evaluation_id)
    criteria_by_area = {area: sorted(
        [c for c in ev.criteria if c.area == area], key=lambda c: c.order_index
    ) for area in AREAS}
    return render(request, "pages/evaluation_print.html", identity=identity,
                  page_title="Evaluación", ev=ev, criteria_by_area=criteria_by_area)


@router.post("/evaluations/{evaluation_id}/start")
async def start_evaluation(evaluation_id: int, request: Request,
                           identity: Identity = Depends(require_identity),
                           db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = EvaluationService(db, identity)
    svc.start(evaluation_id, ip=client_ip(request))
    return RedirectResponse(url=f"/evaluations/{evaluation_id}", status_code=303)


@router.post("/evaluations/{evaluation_id}/save")
async def save_evaluation(evaluation_id: int, request: Request,
                          identity: Identity = Depends(require_identity),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = EvaluationService(db, identity)
    form = await _form(request)
    try:
        svc.save_draft(evaluation_id, form, ip=client_ip(request))
    except ValidationError as e:
        return _rerender_detail(request, identity, svc, evaluation_id, e.errors)
    flash(request, "Borrador guardado.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/evaluations/{evaluation_id}", status_code=303)


@router.post("/evaluations/{evaluation_id}/submit")
async def submit_evaluation(evaluation_id: int, request: Request,
                            identity: Identity = Depends(require_identity),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = EvaluationService(db, identity)
    form = await _form(request)
    try:
        svc.submit(evaluation_id, form, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return _rerender_detail(request, identity, svc, evaluation_id, e.errors)
    flash(request, "Evaluación enviada para aprobación.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/evaluations/{evaluation_id}", status_code=303)


@router.post("/evaluations/{evaluation_id}/return")
async def return_evaluation(evaluation_id: int, request: Request,
                            identity: Identity = Depends(require_identity),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                            comments: str = Form("")):
    svc = EvaluationService(db, identity)
    try:
        svc.return_for_correction(evaluation_id, comments, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/evaluations/{evaluation_id}", status_code=303)
    flash(request, "Evaluación devuelta al tutor para corrección.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/evaluations/{evaluation_id}", status_code=303)


@router.post("/evaluations/{evaluation_id}/approve")
async def approve_evaluation(evaluation_id: int, request: Request,
                             identity: Identity = Depends(require_identity),
                             db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                             comments: str = Form("")):
    svc = EvaluationService(db, identity)
    svc.approve(evaluation_id, comments, ip=client_ip(request))
    flash(request, "Evaluación aprobada.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/evaluations/{evaluation_id}", status_code=303)


@router.post("/evaluations/{evaluation_id}/reopen")
async def reopen_evaluation(evaluation_id: int, request: Request,
                            identity: Identity = Depends(require_identity),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                            reason: str = Form("")):
    svc = EvaluationService(db, identity)
    try:
        svc.reopen(evaluation_id, reason, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/evaluations/{evaluation_id}", status_code=303)
    flash(request, "Evaluación reabierta.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/evaluations/{evaluation_id}", status_code=303)
