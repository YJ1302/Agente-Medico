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

# Expose selected settings to all templates.
templates.env.globals.update(
    app_name=settings.app_name,
    app_subtitle=settings.app_subtitle,
    institution_name=settings.institution_name,
    demo_mode=settings.demo_mode,
    current_year=datetime.now().year,
)


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
    base_context.update(context)
    return templates.TemplateResponse(
        template_name, base_context, status_code=status_code
    )
