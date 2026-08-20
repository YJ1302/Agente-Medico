"""Authentication routes: login page, login submit and logout.

Uses the seeded demo accounts. On success the identity is stored in the signed
session cookie; there is no public registration.

Accounts with more than one granted role (see ``app.models.user.UserRole``)
go through an extra step: after password verification, ``_PENDING_KEY`` holds
the authenticated user's id in the session (not yet a logged-in identity —
protected routes still redirect to /login) while ``/login/choose-role`` lets
them pick which role is active. The chosen role is always re-validated
against the database, never trusted from the form alone.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.csrf import csrf_protect
from app.database import get_db
from app.dependencies import get_current_identity
from app.services.auth_service import AuthService
from app.templating import render

router = APIRouter(tags=["auth"])

_PENDING_KEY = "pending_login_user_id"

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
    user = service.authenticate(email, password)
    if user is None:
        return render(
            request,
            "login.html",
            error="Credenciales inválidas. Verifique el correo y la contraseña.",
            demo_credentials=DEMO_CREDENTIALS if settings.demo_mode else [],
            demo_password=DEMO_PASSWORD if settings.demo_mode else "",
        )
    roles = service.roles_for(user)
    if len(roles) <= 1:
        identity = service.build_identity(user)
        request.session["identity"] = identity.to_session()
        request.session.pop(_PENDING_KEY, None)
        return RedirectResponse(url="/dashboard", status_code=303)
    # Multiple roles: password is verified, but the session identity isn't
    # set yet — protected routes still redirect to /login until a role is
    # chosen below.
    request.session[_PENDING_KEY] = user.id
    return RedirectResponse(url="/login/choose-role", status_code=303)


@router.get("/login/choose-role")
def choose_role_page(request: Request, error: str | None = None,
                     db: Session = Depends(get_db)):
    if get_current_identity(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    pending_id = request.session.get(_PENDING_KEY)
    if not pending_id:
        return RedirectResponse(url="/login", status_code=303)
    service = AuthService(db)
    user = service.repos.users.get(pending_id)
    if user is None or user.is_deleted or not user.is_active:
        request.session.pop(_PENDING_KEY, None)
        return RedirectResponse(url="/login", status_code=303)
    roles = service.roles_for(user)
    if len(roles) <= 1:
        # Roles changed between password submit and this page load (e.g. an
        # admin revoked one) — just log them in with whatever remains.
        identity = service.build_identity(user)
        request.session["identity"] = identity.to_session()
        request.session.pop(_PENDING_KEY, None)
        return RedirectResponse(url="/dashboard", status_code=303)
    return render(request, "login_choose_role.html", full_name=user.full_name,
                  roles=roles, error=error)


@router.post("/login/choose-role")
def choose_role_submit(request: Request, role_code: str = Form(...),
                       db: Session = Depends(get_db)):
    pending_id = request.session.get(_PENDING_KEY)
    if not pending_id:
        return RedirectResponse(url="/login", status_code=303)
    service = AuthService(db)
    user = service.repos.users.get(pending_id)
    if user is None or user.is_deleted or not user.is_active:
        request.session.pop(_PENDING_KEY, None)
        return RedirectResponse(url="/login", status_code=303)
    roles = service.roles_for(user)
    if role_code not in {r.code for r in roles}:
        return RedirectResponse(
            url="/login/choose-role?error=" + quote("Selección inválida."), status_code=303
        )
    identity = service.build_identity(user, active_role_code=role_code)
    request.session["identity"] = identity.to_session()
    request.session.pop(_PENDING_KEY, None)
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/switch-role")
def switch_role(request: Request, role_code: str = Form(...),
                db: Session = Depends(get_db), _: None = Depends(csrf_protect)):
    """Change the session's active role without logging out.

    Only available when the account holds more than one role; always
    re-validated against the database (not just the roles cached in the
    session cookie) so a role revoked mid-session can't still be switched
    into.
    """
    identity = get_current_identity(request)
    if identity is None:
        return RedirectResponse(url="/login", status_code=303)
    service = AuthService(db)
    user = service.repos.users.get(identity.user_id)
    if user is None or user.is_deleted or not user.is_active:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)
    roles = service.roles_for(user)
    if role_code not in {r.code for r in roles}:
        return RedirectResponse(url="/dashboard", status_code=303)
    new_identity = service.build_identity(user, active_role_code=role_code)
    request.session["identity"] = new_identity.to_session()
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)
