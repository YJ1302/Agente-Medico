"""Rotation assignment routes (Batch 2B). Thin controllers over RotationService."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import Forbidden
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.services.audit_service import client_ip
from app.services.rotation_service import ConflictError, RotationService
from app.services.student_activity_service import StudentActivityService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash, paginate

router = APIRouter(tags=["rotations"])
PER_PAGE = 12


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


def _filters(q, period, rtype, sede, tutor, student, status, institution, tutorflag):
    return {
        "query": q or None,
        "period_id": int(period) if period else None,
        "rotation_type_id": int(rtype) if rtype else None,
        "sede_id": int(sede) if sede else None,
        "tutor_id": int(tutor) if tutor else None,
        "student_id": int(student) if student else None,
        "status": status or None,
        "institution_code": institution or None,
        "has_tutor": {"1": True, "0": False}.get(tutorflag, None),
    }


@router.get("/rotations")
def list_rotations(request: Request, identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db),
                   q: str = "", period: str = "", rtype: str = "", sede: str = "",
                   tutor: str = "", student: str = "", status: str = "",
                   institution: str = "", tutorflag: str = "", page: int = 1):
    svc = RotationService(db, identity)
    filters = _filters(q, period, rtype, sede, tutor, student, status, institution, tutorflag)
    rows = svc.list_assignments(**filters)
    # Attach a lightweight conflict flag per row (has any current conflict).
    conflicted = set()
    for a in rows:
        cs = svc.conflicts.check(_row_input(a))
        if any(c.blocking for c in cs):
            conflicted.add(a.id)
    paged = paginate(rows, page, PER_PAGE)
    base_qs = "".join(f"{k}={v}&" for k, v in
                      [("q", q), ("period", period), ("rtype", rtype), ("sede", sede),
                       ("tutor", tutor), ("student", student), ("status", status),
                       ("institution", institution), ("tutorflag", tutorflag)] if v)
    return render(request, "pages/rotations_list.html", identity=identity,
                  page_title="Rotaciones",
                  page_subtitle="Asignaciones de rotación por interno, sede y periodo.",
                  page_icon="arrow-repeat", page=paged, options=svc.form_options(),
                  filters={"q": q, "period": period, "rtype": rtype, "sede": sede,
                           "tutor": tutor, "student": student, "status": status,
                           "institution": institution, "tutorflag": tutorflag},
                  base_qs=base_qs, can_create=svc.can_create(), conflicted=conflicted)


@router.get("/rotations/timeline")
def timeline(request: Request, identity: Identity = Depends(require_identity),
             db: Session = Depends(get_db), group: str = "student"):
    svc = RotationService(db, identity)
    rows = svc.list_assignments()
    if group not in ("student", "sede", "period", "rotation"):
        group = "student"

    def key(a):
        if group == "student":
            return a.student.full_name if a.student else "—"
        if group == "sede":
            return a.sede.short_name or a.sede.name if a.sede else "—"
        if group == "period":
            return a.period.name if a.period else "—"
        return a.rotation_type.name if a.rotation_type else "—"

    groups: dict[str, list] = {}
    for a in sorted(rows, key=lambda x: (key(x), x.start_date or __import__("datetime").date.min)):
        groups.setdefault(key(a), []).append(a)
    return render(request, "pages/rotation_timeline.html", identity=identity,
                  page_title="Cronograma de rotaciones",
                  page_subtitle="Vista de calendario/timeline de las rotaciones.",
                  page_icon="calendar3", groups=groups, group=group)


@router.get("/rotations/new")
def new_rotation(request: Request, identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    svc = RotationService(db, identity)
    if not svc.can_create():
        raise Forbidden(reason="create_rotation_denied")
    return render(request, "pages/rotation_form.html", identity=identity,
                  page_title="Nueva rotación", page_subtitle="Programar una asignación de rotación.",
                  page_icon="calendar-plus", options=svc.form_options(), form={"status": "planned"},
                  errors={}, conflicts=[], mode="create")


@router.post("/rotations/new")
async def create_rotation(request: Request, identity: Identity = Depends(require_identity),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = RotationService(db, identity)
    if not svc.can_create():
        raise Forbidden(reason="create_rotation_denied")
    form = await _form(request)
    try:
        a = svc.create(form, ip=client_ip(request))
    except ValidationError as e:
        return _rerender_form(request, identity, svc, form, e.errors, [], "create", 400)
    except ConflictError as e:
        return _rerender_form(request, identity, svc, form, e.errors, e.conflicts,
                              "create", 400, needs_confirmation=e.needs_confirmation)
    flash(request, "Rotación creada correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/rotations/{a.id}", status_code=303)


@router.get("/rotations/{assignment_id}")
def rotation_detail(assignment_id: int, request: Request,
                    identity: Identity = Depends(require_identity),
                    db: Session = Depends(get_db)):
    svc = RotationService(db, identity)
    data = svc.build_detail(assignment_id)
    a = data["a"]
    act_svc = StudentActivityService(db, identity)
    activity_summary = act_svc.assignment_summary(assignment_id)
    activity_summary["can_log_activity"] = act_svc.can_log_activity(a)
    activity_summary["activity_options"] = act_svc.form_options(a)
    return render(request, "pages/rotation_detail.html", identity=identity,
                  page_title=f"Rotación · {a.student.full_name if a.student else ''}",
                  page_subtitle=f"{a.rotation_type.name if a.rotation_type else ''}",
                  page_icon="arrow-repeat", activity=activity_summary, **data)


@router.get("/rotations/{assignment_id}/edit")
def edit_rotation(assignment_id: int, request: Request,
                  identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    svc = RotationService(db, identity)
    a = svc.get_for_view(assignment_id)
    if not svc.can_manage(a):
        raise Forbidden(reason="edit_rotation_denied")
    if a.status in ("completed", "cancelled"):
        flash(request, "La rotación está bloqueada; use reabrir (solo administrador).", "warning")
        return RedirectResponse(url=f"/rotations/{a.id}", status_code=303)
    form = {"student_id": a.student_id, "rotation_type_id": a.rotation_type_id,
            "sede_id": a.sede_id, "period_id": a.period_id, "tutor_id": a.tutor_id,
            "start_date": a.start_date.isoformat() if a.start_date else "",
            "end_date": a.end_date.isoformat() if a.end_date else "",
            "status": a.status, "notes": a.notes}
    return render(request, "pages/rotation_form.html", identity=identity,
                  page_title="Editar rotación", page_subtitle="Actualizar la asignación.",
                  page_icon="pencil", options=svc.form_options(), form=form, errors={},
                  conflicts=[], mode="edit", assignment_id=a.id,
                  limited=(a.status == "active"))


@router.post("/rotations/{assignment_id}/edit")
async def update_rotation(assignment_id: int, request: Request,
                          identity: Identity = Depends(require_identity),
                          db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = RotationService(db, identity)
    form = await _form(request)
    try:
        svc.update(assignment_id, form, ip=client_ip(request))
    except ValidationError as e:
        return _rerender_form(request, identity, svc, form, e.errors, [], "edit", 400, assignment_id)
    except ConflictError as e:
        return _rerender_form(request, identity, svc, form, e.errors, e.conflicts, "edit",
                              400, assignment_id, needs_confirmation=e.needs_confirmation)
    flash(request, "Rotación actualizada correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/rotations/{assignment_id}", status_code=303)


@router.post("/rotations/{assignment_id}/transition")
async def transition_rotation(assignment_id: int, request: Request,
                              identity: Identity = Depends(require_identity),
                              db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                              target: str = Form(...), reason: str = Form("")):
    svc = RotationService(db, identity)
    try:
        a = svc.transition(assignment_id, target, reason=reason, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url=f"/rotations/{assignment_id}", status_code=303)
    labels = {"active": "activada", "completed": "completada", "cancelled": "cancelada",
              "planned": "reabierta"}
    flash(request, f"Rotación {labels.get(a.status, 'actualizada')} correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/rotations/{assignment_id}", status_code=303)


@router.post("/rotations/{assignment_id}/tutor")
async def set_tutor(assignment_id: int, request: Request,
                    identity: Identity = Depends(require_identity),
                    db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                    tutor_id: str = Form("")):
    svc = RotationService(db, identity)
    try:
        svc.set_tutor(assignment_id, int(tutor_id) if tutor_id else None, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "warning")
        return RedirectResponse(url=f"/rotations/{assignment_id}", status_code=303)
    flash(request, "Tutor actualizado correctamente.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/rotations/{assignment_id}", status_code=303)


# --- helpers ---------------------------------------------------------------
def _row_input(a):
    from app.services.rotation_conflict_service import RotationInput
    return RotationInput(student_id=a.student_id, rotation_type_id=a.rotation_type_id,
                         sede_id=a.sede_id, period_id=a.period_id, tutor_id=a.tutor_id,
                         start_date=a.start_date, end_date=a.end_date, assignment_id=a.id)


def _rerender_form(request, identity, svc, form, errors, conflicts, mode,
                   status_code, assignment_id=None, needs_confirmation=False):
    return render(request, "pages/rotation_form.html", identity=identity,
                  page_title="Nueva rotación" if mode == "create" else "Editar rotación",
                  page_subtitle="Programar una asignación de rotación." if mode == "create"
                  else "Actualizar la asignación.",
                  page_icon="calendar-plus" if mode == "create" else "pencil",
                  options=svc.form_options(), form=form, errors=errors,
                  conflicts=[c.to_dict() for c in conflicts], mode=mode,
                  assignment_id=assignment_id, needs_confirmation=needs_confirmation,
                  status_code=status_code)
