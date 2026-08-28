"""Jinja2 template environment and shared render helpers.

Centralizes the ``Jinja2Templates`` instance and injects globals that every
template needs (app metadata, navigation, current identity). Keeping this in
one module avoids repeating context assembly in each route.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import APP_DIR, settings
from app.csrf import get_csrf_token
from app.i18n import get_lang, make_translator
from app.services.auth_service import Identity
from app.services.navigation import sections_for_role
from app.web import pop_flashes

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


def _static_version(rel_path: str) -> str:
    """Cache-busting token for a static asset: its own mtime.

    Browsers/CDNs otherwise keep serving a stale cached copy of CSS/JS after
    a deploy since the URL never changes. Appending ``?v=<mtime>`` changes
    the URL whenever the file's content changes, with no manual bumping.
    """
    path = APP_DIR / "static" / rel_path
    try:
        return str(int(path.stat().st_mtime))
    except OSError:
        return "0"


# Expose selected settings to all templates.
templates.env.globals.update(
    app_name=settings.app_name,
    app_subtitle=settings.app_subtitle,
    institution_name=settings.institution_name,
    demo_mode=settings.demo_mode,
    current_year=datetime.now().year,
    static_version=_static_version,
)


def _period_context(request: Request) -> dict:
    """Top-bar period switcher data: every period plus the one in effect.

    The "active" period is the per-session choice from ``/set-period`` when set,
    otherwise the institution's current period. Read-only and defensive — a DB
    hiccup here must never break page rendering.
    """
    from types import SimpleNamespace

    try:
        from app.database import SessionLocal
        from app.repositories.repositories import AcademicPeriodRepository

        db = SessionLocal()
        try:
            repo = AcademicPeriodRepository(db)
            # Detach from the ORM immediately — the session closes before the
            # template renders, so hand the view plain objects.
            periods = [
                SimpleNamespace(id=p.id, name=p.name, code=p.code, year=p.year,
                                ordinal=p.ordinal, is_current=p.is_current)
                for p in reversed(repo.ordered())  # newest first for the menu
            ]
        finally:
            db.close()
    except Exception:  # pragma: no cover - defensive
        return {"all_periods": [], "active_period": None,
                "active_period_pinned": False, "institution_period": None}

    chosen_id = request.session.get("period_id")
    active = next((p for p in periods if p.id == chosen_id), None)
    institution_current = next((p for p in periods if p.is_current), None)
    return {
        "all_periods": periods,
        "active_period": active or institution_current or (
            periods[0] if periods else None),
        "active_period_pinned": active is not None,
        "institution_period": institution_current,
    }


def render(
    request: Request,
    template_name: str,
    identity: Identity | None = None,
    status_code: int = 200,
    **context,
):
    """Render a template with the standard shared context injected."""
    lang = get_lang(request)
    base_context = {
        "request": request,
        "identity": identity,
        "nav_sections": sections_for_role(identity.role_code) if identity else [],
        "active_path": request.url.path,
        "csrf_token": get_csrf_token(request),
        "flashes": pop_flashes(request),
        "lang": lang,
        "t": make_translator(lang),
    }
    if identity is not None:
        base_context.update(_period_context(request))
    base_context.update(context)
    return templates.TemplateResponse(
        template_name, base_context, status_code=status_code
    )
