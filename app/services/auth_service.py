"""Authentication service: credential verification and session identity.

Uses seeded demo accounts (no public registration). Passwords are verified
against bcrypt hashes. The service returns a lightweight identity object that
routes place into the signed session cookie.

An account may hold more than one role (see ``app.models.user.UserRole`` —
e.g. a Sede Coordinator who also tutors interns). Only one role is *active*
per session at a time: every authorization check in the app reads a single
``identity.role_code``, unchanged by multi-role support. When an account has
more than one granted role, ``app.routes.auth_routes`` shows a picker after
password verification and the chosen role becomes ``role_code`` here;
``available_roles`` carries the full list only so the UI can render a
switcher, and is re-validated against the database (never trusted blindly)
whenever it's used to change the active role.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.user import Role, User
from app.repositories.repositories import RepositoryBundle
from app.security import verify_password

logger = get_logger(__name__)


@dataclass
class Identity:
    """Minimal authenticated identity stored in the session cookie."""

    user_id: int
    email: str
    full_name: str
    role_code: str
    role_name: str
    # [(code, name), ...] for every role this account holds, active one
    # included — empty for Identity instances built directly (tests, agent
    # contexts) that don't care about the role switcher.
    available_roles: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_multiple_roles(self) -> bool:
        return len(self.available_roles) > 1

    def to_session(self) -> dict:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "full_name": self.full_name,
            "role_code": self.role_code,
            "role_name": self.role_name,
            "available_roles": [list(r) for r in self.available_roles],
        }

    @classmethod
    def from_session(cls, data: dict) -> "Identity | None":
        try:
            raw_roles = data.get("available_roles") or []
            return cls(
                user_id=int(data["user_id"]),
                email=data["email"],
                full_name=data["full_name"],
                role_code=data["role_code"],
                role_name=data["role_name"],
                available_roles=[(r[0], r[1]) for r in raw_roles],
            )
        except (KeyError, TypeError, ValueError, IndexError):
            return None


class AuthService:
    """Handles login authentication against seeded accounts."""

    def __init__(self, db: Session) -> None:
        self.repos = RepositoryBundle(db)

    def authenticate(self, email: str, password: str) -> User | None:
        """Return the authenticated User, or None if credentials are invalid.

        Does not build an Identity: an account may hold more than one role,
        so the caller (the login route) decides — directly, or via a
        role-choice step — which role becomes active for the session.
        """
        user = self.repos.users.get_by_email(email.strip())
        if user is None or user.is_deleted or not user.is_active:
            logger.info("Login failed for %s (no active user)", email)
            return None
        if not verify_password(password, user.hashed_password):
            logger.info("Login failed for %s (bad password)", email)
            return None
        logger.info("Login success for %s", email)
        return user

    def roles_for(self, user: User) -> list[Role]:
        """Every role this account is granted, most senior first."""
        return self.repos.user_roles.roles_for_user(user.id)

    def build_identity(self, user: User, active_role_code: str | None = None) -> Identity:
        """Build an Identity for ``user``, activating ``active_role_code``.

        ``active_role_code`` must be one of the user's granted roles — the
        caller (login or role-switch routes) is expected to have already
        validated that against ``roles_for()``; this re-checks defensively
        and falls back to the first granted role rather than trusting an
        unvalidated value silently.
        """
        roles = self.roles_for(user)
        active = None
        if active_role_code:
            active = next((r for r in roles if r.code == active_role_code), None)
        if active is None:
            active = roles[0] if roles else user.role
        return Identity(
            user_id=user.id, email=user.email, full_name=user.full_name,
            role_code=active.code, role_name=active.name,
            available_roles=[(r.code, r.name) for r in roles],
        )
