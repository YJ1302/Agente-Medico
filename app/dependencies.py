"""Shared FastAPI dependencies: session identity (authentication only).

Authentication is session-cookie based (Starlette ``SessionMiddleware`` signs
the cookie with the app SECRET_KEY). These helpers read the identity from the
session and confirm the user is logged in.

Authorization (role guards and record-level scope) lives in
``app.authorization`` and must be applied on top of ``require_identity`` for any
route or action that is not open to every authenticated role.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse

from app.services.auth_service import Identity


class RedirectToLogin(Exception):
    """Raised when an unauthenticated user hits a protected page."""


def get_current_identity(request: Request) -> Identity | None:
    """Return the logged-in Identity from the session, or None."""
    data = request.session.get("identity")
    if not data:
        return None
    return Identity.from_session(data)


def require_identity(request: Request) -> Identity:
    """FastAPI dependency: ensure a user is logged in.

    Raises ``RedirectToLogin`` (handled globally) when there is no session, so
    protected routes can simply ``Depends(require_identity)``.
    """
    identity = get_current_identity(request)
    if identity is None:
        raise RedirectToLogin()
    return identity


def login_redirect() -> RedirectResponse:
    """Standard redirect response to the login page."""
    return RedirectResponse(url="/login", status_code=303)
