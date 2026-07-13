"""CSRF protection for state-changing HTML forms.

Strategy (synchronizer-token pattern):

* A random token is generated per session and stored in the signed session
  cookie (``request.session["csrf_token"]``).
* Every form embeds the token in a hidden ``csrf_token`` input.
* State-changing routes depend on ``csrf_protect``, which reads the submitted
  token from the form body and compares it to the session token in constant
  time. A missing or mismatched token raises ``CSRFError`` → a friendly 400.

All mutations use POST; GET requests are never protected because GET must not
mutate state (enforced by convention and tests).
"""

from __future__ import annotations

import secrets

from fastapi import Request

_SESSION_KEY = "csrf_token"
_FORM_FIELD = "csrf_token"


class CSRFError(Exception):
    """Raised when a state-changing request has a missing/invalid CSRF token."""

    def __init__(self, message: str = "Token de seguridad inválido o ausente. "
                                      "Recargue la página e inténtelo de nuevo.") -> None:
        self.message = message
        super().__init__(message)


def get_csrf_token(request: Request) -> str:
    """Return the session CSRF token, creating one on first use."""
    token = request.session.get(_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_SESSION_KEY] = token
    return token


def _valid(request: Request, submitted: str | None) -> bool:
    expected = request.session.get(_SESSION_KEY)
    if not expected or not submitted:
        return False
    return secrets.compare_digest(str(expected), str(submitted))


async def csrf_protect(request: Request) -> None:
    """FastAPI dependency: validate the CSRF token on a state-changing request.

    Reads the form body (Starlette caches it, so route ``Form(...)`` params still
    work afterwards). Raises ``CSRFError`` when the token is missing or invalid.
    """
    form = await request.form()
    submitted = form.get(_FORM_FIELD)
    if not _valid(request, submitted):
        raise CSRFError()
