"""Academic grade routes (Batch 2F foundation). Thin controllers.

Displays grade schemes and the per-student component matrix. A final grade is
never computed while weights are unconfirmed — the UI shows
"Fórmula pendiente de confirmación". Students never see the raw matrix.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.authorization import ensure, require_admin_or_university
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import Identity, require_identity
from app.models.base import GRADE_CATEGORIES
from app.services.audit_service import client_ip
from app.services.grade_service import GradeService
from app.templating import render
from app.web import FLASH_SUCCESS, flash

router = APIRouter(tags=["grades"])


@router.get("/grades")
def grades_list(request: Request,
                identity: Identity = Depends(require_admin_or_university),
                db: Session = Depends(get_db)):
    svc = GradeService(db, identity)
    return render(request, "pages/grades_list.html", identity=identity,
                  page_title="Notas académicas",
                  page_subtitle="Esquemas de nota configurables. Las fórmulas finales "
                                "requieren la confirmación de los pesos oficiales.",
                  page_icon="123", schemes=svc.list_schemes())


@router.get("/grades/cross-sheet-check")
def cross_sheet_check(request: Request,
                      identity: Identity = Depends(require_admin_or_university),
                      db: Session = Depends(get_db), batch_ids: str = ""):
    """Compare student sets across several grade-import batches (read-only).

    Registered BEFORE ``/grades/{scheme_id}`` — FastAPI matches routes in
    registration order, and an int-typed path param would otherwise swallow
    this static path (returning a spurious 422 for "cross-sheet-check").
    """
    svc = GradeService(db, identity)
    ids = [int(x) for x in batch_ids.split(",") if x.strip().isdigit()]
    report = svc.cross_sheet_report(ids) if ids else None
    from app.services.import_service import ImportService
    grade_batches = ImportService(db, identity).list_batches(profile="grade_components")
    return render(request, "pages/grade_cross_sheet.html", identity=identity,
                  page_title="Verificación entre hojas",
                  page_subtitle="Compara los internos importados entre distintas hojas de notas.",
                  page_icon="diagram-2", report=report, batch_ids=batch_ids,
                  grade_batches=grade_batches)


@router.get("/grades/{scheme_id}")
def grade_scheme_detail(scheme_id: int, request: Request,
                        identity: Identity = Depends(require_admin_or_university),
                        db: Session = Depends(get_db)):
    svc = GradeService(db, identity)
    data = svc.build_matrix(scheme_id)
    return render(request, "pages/grade_scheme_detail.html", identity=identity,
                  page_title=f"Esquema · {data['scheme'].name}", page_icon="123",
                  categories=GRADE_CATEGORIES, **data)


@router.post("/grades/component/{sgc_id}/approve")
async def approve_component(sgc_id: int, request: Request,
                            identity: Identity = Depends(require_identity),
                            db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    svc = GradeService(db, identity)
    sgc = svc.approve_component(sgc_id, ip=client_ip(request))
    flash(request, "Componente de nota aprobado.", FLASH_SUCCESS)
    return RedirectResponse(url=f"/grades/{sgc.scheme_id}", status_code=303)
