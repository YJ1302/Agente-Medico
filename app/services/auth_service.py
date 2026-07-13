"""Authentication service: credential verification and session identity.

Uses seeded demo accounts (no public registration). Passwords are verified
against bcrypt hashes. The service returns a lightweight identity object that
routes place into the signed session cookie.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.logging_config import get_logger
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

    def to_session(self) -> dict:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "full_name": self.full_name,
            "role_code": self.role_code,
            "role_name": self.role_name,
        }

    @classmethod
    def from_session(cls, data: dict) -> "Identity | None":
        try:
            return cls(
                user_id=int(data["user_id"]),
                email=data["email"],
                full_name=data["full_name"],
                role_code=data["role_code"],
                role_name=data["role_name"],
            )
        except (KeyError, TypeError, ValueError):
            return None


class AuthService:
    """Handles login authentication against seeded accounts."""

    def __init__(self, db: Session) -> None:
        self.repos = RepositoryBundle(db)

    def authenticate(self, email: str, password: str) -> Identity | None:
        """Return an Identity if credentials are valid, else None."""
        user = self.repos.users.get_by_email(email.strip())
        if user is None or user.is_deleted or not user.is_active:
            logger.info("Login failed for %s (no active user)", email)
            return None
        if not verify_password(password, user.hashed_password):
            logger.info("Login failed for %s (bad password)", email)
            return None

        logger.info("Login success for %s (%s)", email, user.role_code)
        return Identity(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role_code=user.role.code,
            role_name=user.role.name,
        )
