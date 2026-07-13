"""Server-side authorization: role guards and record-level scope.

Part 1 only checked *authentication* (logged-in). Part 2 adds real
*authorization*: role-level route guards and record-level scope helpers that
enforce the access model in docs/USER_ROLES_AND_PERMISSIONS.md.

Two layers:

* **Route guards** — ``require_roles(...)`` dependency factory rejects a request
  whose identity does not hold an allowed role (raises ``Forbidden`` → 403).
* **Record scope** — pure predicate helpers (``can_view_student`` etc.) that
  services call before returning or mutating a specific row, so a user cannot
  reach another sede's / student's data by editing a URL.

Hiding sidebar links is *never* the security boundary; these checks are.
"""

from __future__ import annotations

from fastapi import Depends, Request

from app.dependencies import require_identity
from app.models.user import (
    ROLE_ADMIN,
    ROLE_SEDE_COORDINATOR,
    ROLE_STUDENT,
    ROLE_TUTOR,
    ROLE_UNIVERSITY_COORDINATOR,
)
from app.services.auth_service import Identity


class Forbidden(Exception):
    """Raised when an authenticated user lacks permission for an action.

    Carries an optional machine ``reason`` used for the audit log
    (``authorization_denied``) and a human message for the 403 page.
    """

    def __init__(self, message: str = "No tiene permisos para acceder a este recurso.",
                 reason: str = "role_not_allowed") -> None:
        self.message = message
        self.reason = reason
        super().__init__(message)


# ---------------------------------------------------------------------------
# Route-level role guards
# ---------------------------------------------------------------------------
def require_roles(*allowed: str):
    """Return a FastAPI dependency that allows only the given role codes.

    Usage:
        admin_only = require_roles(ROLE_ADMIN)

        @router.get("/users")
        def users(identity: Identity = Depends(admin_only)): ...
    """
    allowed_set = set(allowed)

    def _guard(request: Request,
               identity: Identity = Depends(require_identity)) -> Identity:
        if identity.role_code not in allowed_set:
            raise Forbidden(
                reason=f"role_{identity.role_code}_denied",
            )
        return identity

    return _guard


# Convenience pre-built guards matching USER_ROLES_AND_PERMISSIONS.md.
require_admin = require_roles(ROLE_ADMIN)
require_admin_or_university = require_roles(ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR)
require_staff = require_roles(  # any non-student staff member
    ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR, ROLE_TUTOR
)
require_management = require_roles(  # can manage sede-scoped resources
    ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR, ROLE_SEDE_COORDINATOR
)


# ---------------------------------------------------------------------------
# Role predicates
# ---------------------------------------------------------------------------
def is_admin(identity: Identity) -> bool:
    return identity.role_code == ROLE_ADMIN


def is_university(identity: Identity) -> bool:
    return identity.role_code == ROLE_UNIVERSITY_COORDINATOR


def is_global_viewer(identity: Identity) -> bool:
    """Admin and University Coordinator see all internship records."""
    return identity.role_code in {ROLE_ADMIN, ROLE_UNIVERSITY_COORDINATOR}


# ---------------------------------------------------------------------------
# Record-level scope helpers
#
# These take already-loaded ORM objects and the current identity plus a
# ``RepositoryBundle`` (imported lazily to avoid a cycle) and answer a simple
# yes/no. Services must call them before returning or mutating a specific row.
# ---------------------------------------------------------------------------
def _sede_ids_for_coordinator(identity: Identity, repos) -> set[int]:
    """Sede ids the given sede-coordinator identity coordinates."""
    ids: set[int] = set()
    for c in repos.sede_coordinators.active():
        if c.user_id == identity.user_id and c.sede_id is not None:
            ids.add(c.sede_id)
    return ids


def _tutor_profile_ids(identity: Identity, repos) -> set[int]:
    """Tutor-profile ids belonging to the given tutor identity."""
    return {t.id for t in repos.tutors.active() if t.user_id == identity.user_id}


def can_view_student(identity: Identity, student, repos) -> bool:
    """Whether the identity may view the given student record."""
    if is_global_viewer(identity):
        return True
    if identity.role_code == ROLE_SEDE_COORDINATOR:
        return student.sede_id in _sede_ids_for_coordinator(identity, repos)
    if identity.role_code == ROLE_TUTOR:
        tutor_ids = _tutor_profile_ids(identity, repos)
        return any(
            a.tutor_id in tutor_ids for a in getattr(student, "rotation_assignments", [])
        )
    if identity.role_code == ROLE_STUDENT:
        return student.user_id == identity.user_id
    return False


def can_edit_student(identity: Identity, student, repos) -> bool:
    """Whether the identity may edit the given student record."""
    if is_global_viewer(identity):
        return True
    if identity.role_code == ROLE_SEDE_COORDINATOR:
        return student.sede_id in _sede_ids_for_coordinator(identity, repos)
    return False


def can_view_sede(identity: Identity, sede, repos) -> bool:
    if is_global_viewer(identity):
        return True
    if identity.role_code == ROLE_SEDE_COORDINATOR:
        return sede.id in _sede_ids_for_coordinator(identity, repos)
    # Tutors/students may read a sede tied to their assignment; permissive read.
    return True


def can_view_assignment(identity: Identity, assignment, repos) -> bool:
    if is_global_viewer(identity):
        return True
    if identity.role_code == ROLE_SEDE_COORDINATOR:
        return assignment.sede_id in _sede_ids_for_coordinator(identity, repos)
    if identity.role_code == ROLE_TUTOR:
        return assignment.tutor_id in _tutor_profile_ids(identity, repos)
    if identity.role_code == ROLE_STUDENT:
        return assignment.student and assignment.student.user_id == identity.user_id
    return False


def ensure(condition: bool, message: str = "Acceso denegado.",
           reason: str = "scope_denied") -> None:
    """Raise ``Forbidden`` unless ``condition`` holds (guard-clause helper)."""
    if not condition:
        raise Forbidden(message=message, reason=reason)
