"""User profile and notifications routes (lightweight, read-only in Part 1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import Identity, require_identity
from app.services.alert_service import AlertService
from app.templating import render

router = APIRouter(tags=["profile"])


@router.get("/profile")
def profile(request: Request, identity: Identity = Depends(require_identity)):
    return render(
        request,
        "pages/profile.html",
        identity=identity,
        page_title="Mi perfil",
        page_subtitle="Información de la cuenta.",
        page_icon="person-circle",
    )


@router.get("/set-lang")
def set_lang(request: Request, lang: str = "es", next: str = "/dashboard"):
    """Toggle the interface language preference (es/en) and return to `next`."""
    from fastapi.responses import RedirectResponse
    from app.i18n import SUPPORTED, DEFAULT_LANG
    request.session["lang"] = lang if lang in SUPPORTED else DEFAULT_LANG
    # Only allow local redirects (avoid open-redirect).
    target = next if next.startswith("/") else "/dashboard"
    return RedirectResponse(url=target, status_code=303)


@router.get("/api/notifications")
def notifications(request: Request, identity: Identity = Depends(require_identity),
                  db: Session = Depends(get_db)):
    """JSON feed for the top-bar notification dropdown (scoped to the caller —
    never another role's/sede's/student's alerts, see PERMISSIONS_MATRIX.md)."""
    alerts = AlertService(db).scoped_open_alerts(identity)
    return {
        "count": len(alerts),
        "items": [
            {"title": a.title, "message": a.message, "severity": a.severity}
            for a in alerts[:8]
        ],
    }
