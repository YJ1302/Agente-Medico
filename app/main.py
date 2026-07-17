"""FastAPI application factory and entry point.

Run locally with:
    uvicorn app.main:app --reload

Wires middleware (signed sessions), static files, routes and error handlers.
On SQLite (local/dev) startup also ensures the schema exists (create_all);
on PostgreSQL, schema is owned exclusively by Alembic migrations, run before
the server starts (see the deployment start command). No seeding or resetting
ever happens automatically at startup on any backend.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import __version__
from app.authorization import Forbidden
from app.config import APP_DIR, settings
from app.csrf import CSRFError
from app.database import get_db_session, init_db
from app.dependencies import RedirectToLogin, get_current_identity
from app.logging_config import get_logger
from app.routes import (
    activity_routes,
    agent_routes,
    assistant_routes,
    auth_routes,
    coordinator_routes,
    dashboard_routes,
    document_routes,
    evaluation_routes,
    grade_routes,
    import_routes,
    incident_routes,
    pages_routes,
    profile_routes,
    report_routes,
    rotation_routes,
    sede_routes,
    student_routes,
    tutor_routes,
)
from app.services.audit_service import AUTHORIZATION_DENIED, AuditService, client_ip
from app.templating import render

logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description=settings.app_subtitle,
        version=__version__,
        docs_url="/api-docs" if settings.debug else None,
    )

    # Signed session cookie (Starlette). Cookies are http-only and same-site.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=settings.session_cookie_name,
        max_age=settings.session_max_age,
        same_site="lax",
        https_only=settings.is_production,
    )

    app.mount(
        "/static",
        StaticFiles(directory=str(APP_DIR / "static")),
        name="static",
    )

    # Routers
    app.include_router(auth_routes.router)
    app.include_router(dashboard_routes.router)
    app.include_router(student_routes.router)
    app.include_router(sede_routes.router)
    app.include_router(coordinator_routes.router)
    app.include_router(tutor_routes.router)
    app.include_router(rotation_routes.router)
    app.include_router(activity_routes.router)
    app.include_router(evaluation_routes.router)
    app.include_router(document_routes.router)
    app.include_router(incident_routes.router)
    app.include_router(report_routes.router)
    app.include_router(import_routes.router)
    app.include_router(grade_routes.router)
    app.include_router(pages_routes.router)
    app.include_router(agent_routes.router)
    app.include_router(assistant_routes.router)
    app.include_router(profile_routes.router)

    _register_error_handlers(app)

    @app.on_event("startup")
    def _startup() -> None:
        # SQLite (local/dev): create_all is a convenient, idempotent bootstrap
        # so a fresh checkout works without running Alembic first. In
        # production (PostgreSQL), schema is owned exclusively by Alembic
        # (`alembic upgrade head`, run before the server starts — see the
        # deployment start command) so create_all is skipped: letting the app
        # silently create tables that have no matching migration would cause
        # schema drift and mask a missing revision. Startup never seeds or
        # resets data either way.
        if settings.database_url.startswith("sqlite"):
            init_db()
        logger.info("%s v%s started (env=%s)", settings.app_name, __version__, settings.app_env)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        """Minimal health check for the hosting platform (Render). Returns
        only a static status — no database query, no secrets, no version
        string — so it stays fast and never leaks internal state."""
        return {"status": "ok"}

    return app


def _register_error_handlers(app: FastAPI) -> None:
    """Global exception handlers for auth redirects and error pages."""

    @app.exception_handler(RedirectToLogin)
    async def _redirect_to_login(request: Request, exc: RedirectToLogin):
        return RedirectResponse(url="/login", status_code=303)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        # Record the denied attempt (append-only) without leaking sensitive data.
        identity = get_current_identity(request)
        try:
            with get_db_session() as db:
                AuditService(db).record(
                    AUTHORIZATION_DENIED,
                    identity=identity,
                    entity_type="route",
                    detail={"path": request.url.path, "method": request.method},
                    reason=exc.reason,
                    ip_address=client_ip(request),
                )
        except Exception:  # never let auditing break the error response
            logger.exception("Failed to record authorization_denied")
        return render(request, "errors/403.html", identity=None,
                      message=exc.message, status_code=403)

    @app.exception_handler(CSRFError)
    async def _csrf_error(request: Request, exc: CSRFError):
        identity = get_current_identity(request)
        return render(request, "errors/csrf.html", identity=None,
                      message=exc.message, status_code=400)

    @app.exception_handler(404)
    async def _not_found(request: Request, exc):
        return render(request, "errors/404.html", identity=None, status_code=404)

    @app.exception_handler(500)
    async def _server_error(request: Request, exc):
        logger.exception("Unhandled server error")
        return render(request, "errors/error.html", identity=None, status_code=500)


app = create_app()
