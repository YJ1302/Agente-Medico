"""Bulk-import wizard routes (Batch 2F). Thin controllers.

Upload → sheet → map → validate → preview → confirm → result. Every mutation is
POST + CSRF-protected; nothing is imported automatically. Authorization/scope
live in ``ImportService``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.authorization import ensure
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.models.base import ImportMode, ImportStatus
from app.services.audit_service import client_ip
from app.services.grade_service import GradeService
from app.services.import_profiles import all_profiles, get_profile
from app.services.import_service import ImportService
from app.services.validators import ValidationError
from app.templating import render
from app.web import FLASH_SUCCESS, flash

router = APIRouter(tags=["imports"])

_MODE_LABELS = {
    ImportMode.CREATE_ONLY.value: "Solo crear nuevos",
    ImportMode.UPDATE_EXISTING.value: "Actualizar existentes",
    ImportMode.SKIP_DUPLICATES.value: "Omitir duplicados",
    ImportMode.VALID_ONLY.value: "Importar solo filas válidas",
    ImportMode.ALL_OR_NOTHING.value: "Cancelar todo si hay errores",
}


async def _form(request: Request) -> dict:
    form = await request.form()
    return {k: v for k, v in form.multi_items()}


def _available_profiles(identity: Identity):
    return [p for p in all_profiles() if identity.role_code in p.allowed_roles]


@router.get("/imports")
def import_center(request: Request, identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    svc = ImportService(db, identity)
    profiles = _available_profiles(identity)
    ensure(bool(profiles), "No tiene acceso a la importación masiva.", "import_center_denied")
    return render(request, "pages/imports_center.html", identity=identity,
                  page_title="Centro de Importación",
                  page_subtitle="Importación masiva segura desde Excel (.xlsx/.xlsm).",
                  page_icon="upload", profiles=profiles, batches=svc.list_batches())


@router.get("/imports/history")
def import_history(request: Request, identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db), profile: str = ""):
    svc = ImportService(db, identity)
    ensure(bool(_available_profiles(identity)),
           "No tiene acceso a la importación masiva.", "import_history_denied")
    return render(request, "pages/import_history.html", identity=identity,
                  page_title="Historial de Importaciones", page_icon="clock-history",
                  batches=svc.list_batches(profile=profile or None), profile=profile)


@router.get("/imports/new")
def import_new(request: Request, identity: Identity = Depends(require_identity),
               db: Session = Depends(get_db), profile: str = "students"):
    svc = ImportService(db, identity)
    prof = get_profile(profile)
    ensure(prof is not None and svc.can_use_profile(profile),
           "No tiene permiso para este tipo de importación.", "import_profile_denied")
    schemes = GradeService(db, identity).list_schemes() if profile == "grade_components" else []
    return render(request, "pages/import_new.html", identity=identity,
                  page_title=f"Nueva importación · {prof.label}", page_icon="upload",
                  profile=prof, schemes=schemes)


@router.post("/imports")
async def import_create(request: Request, identity: Identity = Depends(require_identity),
                        db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                        profile: str = Form(...), scheme_id: str = Form("")):
    svc = ImportService(db, identity)
    form = await request.form()
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        flash(request, "Seleccione un archivo Excel.", "danger")
        return RedirectResponse(url=f"/imports/new?profile={profile}", status_code=303)
    raw = await upload.read()
    try:
        batch = svc.create_batch(profile, upload.filename, upload.content_type, raw,
                                 scheme_id=int(scheme_id) if scheme_id.strip() else None,
                                 ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/imports/new?profile={profile}", status_code=303)
    return RedirectResponse(url=f"/imports/{batch.id}/sheet", status_code=303)


@router.get("/imports/{batch_id}")
def import_detail(batch_id: int, request: Request,
                  identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    svc = ImportService(db, identity)
    batch = svc.get_for_view(batch_id)
    # Route to the correct wizard step for in-progress batches.
    if batch.status == ImportStatus.UPLOADED.value:
        return RedirectResponse(url=f"/imports/{batch.id}/sheet", status_code=303)
    if batch.status == ImportStatus.MAPPED.value:
        return RedirectResponse(url=f"/imports/{batch.id}/map", status_code=303)
    if batch.status == ImportStatus.VALIDATED.value:
        return RedirectResponse(url=f"/imports/{batch.id}/preview", status_code=303)
    return render(request, "pages/import_result.html", identity=identity,
                  page_title=f"Importación {batch.code}", page_icon="clipboard-check",
                  batch=batch, rows=svc.preview_rows(batch, limit=300), mode_labels=_MODE_LABELS)


@router.get("/imports/{batch_id}/sheet")
def import_sheet(batch_id: int, request: Request,
                 identity: Identity = Depends(require_identity),
                 db: Session = Depends(get_db)):
    svc = ImportService(db, identity)
    batch = svc.get_for_view(batch_id)
    return render(request, "pages/import_sheet.html", identity=identity,
                  page_title=f"{batch.code} · Hoja", page_icon="table",
                  batch=batch, sheets=svc.sheets(batch), step=1)


@router.post("/imports/{batch_id}/sheet")
async def import_set_sheet(batch_id: int, request: Request,
                           identity: Identity = Depends(require_identity),
                           db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                           sheet_name: str = Form(...)):
    svc = ImportService(db, identity)
    svc.set_sheet(batch_id, sheet_name, ip=client_ip(request))
    return RedirectResponse(url=f"/imports/{batch_id}/map", status_code=303)


@router.get("/imports/{batch_id}/map")
def import_map(batch_id: int, request: Request,
               identity: Identity = Depends(require_identity),
               db: Session = Depends(get_db)):
    svc = ImportService(db, identity)
    batch = svc.get_for_view(batch_id)
    return render(request, "pages/import_map.html", identity=identity,
                  page_title=f"{batch.code} · Mapeo", page_icon="diagram-3",
                  batch=batch, fields=svc.target_fields(batch),
                  headers=svc.headers_for(batch), mapping=svc.current_mapping(batch),
                  modes=_MODE_LABELS, step=2)


@router.post("/imports/{batch_id}/map")
async def import_set_map(batch_id: int, request: Request,
                         identity: Identity = Depends(require_identity),
                         db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = ImportService(db, identity)
    data = await _form(request)
    mode = data.pop("mode", ImportMode.CREATE_ONLY.value)
    mapping = {k[len("map_"):]: v for k, v in data.items()
               if k.startswith("map_") and v}
    svc.set_mapping(batch_id, mapping, mode, ip=client_ip(request))
    try:
        svc.validate_batch(batch_id, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/imports/{batch_id}/map", status_code=303)
    return RedirectResponse(url=f"/imports/{batch_id}/preview", status_code=303)


@router.get("/imports/{batch_id}/preview")
def import_preview(batch_id: int, request: Request,
                   identity: Identity = Depends(require_identity),
                   db: Session = Depends(get_db)):
    svc = ImportService(db, identity)
    batch = svc.get_for_view(batch_id)
    return render(request, "pages/import_preview.html", identity=identity,
                  page_title=f"{batch.code} · Vista previa", page_icon="eye",
                  batch=batch, rows=svc.preview_rows(batch, limit=300),
                  content_hash=batch.content_hash, mode_labels=_MODE_LABELS, step=3)


@router.post("/imports/{batch_id}/confirm")
async def import_confirm(batch_id: int, request: Request,
                         identity: Identity = Depends(require_identity),
                         db: Session = Depends(get_db), _: None = Depends(csrf_protect),
                         content_hash: str = Form("")):
    svc = ImportService(db, identity)
    try:
        svc.confirm_batch(batch_id, expected_hash=content_hash or None, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    flash(request, "Importación confirmada.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)


@router.post("/imports/{batch_id}/cancel")
async def import_cancel(batch_id: int, request: Request,
                        identity: Identity = Depends(require_identity),
                        db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = ImportService(db, identity)
    try:
        svc.cancel_batch(batch_id, ip=client_ip(request))
    except ValidationError as e:
        flash(request, list(e.errors.values())[0], "danger")
        return RedirectResponse(url=f"/imports/{batch_id}", status_code=303)
    flash(request, "Importación cancelada.", FLASH_SUCCESS)
    return RedirectResponse(url="/imports", status_code=303)


@router.get("/imports/{batch_id}/errors.xlsx")
def import_error_report(batch_id: int, request: Request,
                        identity: Identity = Depends(require_identity),
                        db: Session = Depends(get_db)):
    svc = ImportService(db, identity)
    batch = svc.get_for_view(batch_id)
    content = svc.error_report(batch, ip=client_ip(request))
    return Response(content=content,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{batch.code}_errores.xlsx"'})
