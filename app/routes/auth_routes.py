"""Authentication routes: login page, login submit and logout.

Uses the seeded demo accounts. On success the identity is stored in the signed
session cookie; there is no public registration.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_identity
from app.services.auth_service import AuthService
from app.templating import render

router = APIRouter(tags=["auth"])

# Credentials shown on the login page only when DEMO_MODE=true.
DEMO_CREDENTIALS = [
    {"role": "Administrador", "email": "admin@internado360.demo"},
    {"role": "Coordinador Universitario", "email": "coordinator@internado360.demo"},
    {"role": "Coordinador de Sede", "email": "sede@internado360.demo"},
    {"role": "Tutor", "email": "tutor@internado360.demo"},
    {"role": "Interno", "email": "student@internado360.demo"},
]
DEMO_PASSWORD = "Demo123!"


@router.get("/")
def root(request: Request):
    """Send users to the dashboard if logged in, otherwise to login."""
    if get_current_identity(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/login")
def login_page(request: Request, error: str | None = None):
    if get_current_identity(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return render(
        request,
        "login.html",
        error=error,
        demo_credentials=DEMO_CREDENTIALS if settings.demo_mode else [],
        demo_password=DEMO_PASSWORD if settings.demo_mode else "",
    )


@router.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    service = AuthService(db)
    identity = service.authenticate(email, password)
    if identity is None:
        return render(
            request,
            "login.html",
            error="Credenciales inválidas. Verifique el correo y la contraseña.",
            demo_credentials=DEMO_CREDENTIALS if settings.demo_mode else [],
            demo_password=DEMO_PASSWORD if settings.demo_mode else "",
        )
    request.session["identity"] = identity.to_session()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
