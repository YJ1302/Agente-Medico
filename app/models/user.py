"""User and Role models — authentication and role-based access control.

A ``Role`` carries a stable machine ``code`` (used by permission checks and
sidebar visibility) and a human-friendly display name. ``User.role_id`` is
the account's default/primary role (kept for backward compatibility and as
the role assigned when an account has exactly one). A user may additionally
hold more than one role via ``UserRole`` grants — e.g. a Sede Coordinator who
also tutors interns — in which case they choose which role is active at
login (see ``AuthService`` / ``app.routes.auth_routes``); every existing
authorization check still reads a single active ``identity.role_code``, so
this is additive and does not touch permission logic elsewhere.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import IntPKMixin, SoftDeleteMixin, TimestampMixin

# Canonical role codes used throughout the platform (single source of truth).
ROLE_ADMIN = "admin"
ROLE_UNIVERSITY_COORDINATOR = "university_coordinator"
ROLE_SEDE_COORDINATOR = "sede_coordinator"
ROLE_TUTOR = "tutor"
ROLE_STUDENT = "student"


class Role(IntPKMixin, TimestampMixin, Base):
    """A named role with an associated dashboard context and permissions."""

    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Hierarchy level: lower number = higher authority. Used for org-chart
    # rendering and future delegation logic.
    hierarchy_level: Mapped[int] = mapped_column(default=100, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="role")

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<Role {self.code}>"


class User(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An authenticated account. Passwords are stored as bcrypt hashes only."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    role: Mapped[Role] = relationship(back_populates="users")

    # Back-references to profile rows (populated only for the relevant roles).
    student_profile: Mapped["Student | None"] = relationship(  # noqa: F821
        back_populates="user", uselist=False
    )
    sede_coordinator_profile: Mapped["SedeCoordinatorProfile | None"] = (  # noqa: F821
        relationship(back_populates="user", uselist=False)
    )
    tutor_profile: Mapped["TutorProfile | None"] = relationship(  # noqa: F821
        back_populates="user", uselist=False
    )

    # Every role this account is granted (see UserRole below). Populated for
    # all users by a data migration from the former single `role_id`, so this
    # is never empty in practice — code that reads it should still tolerate
    # an empty list defensively rather than assume the backfill ran.
    role_grants: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def role_code(self) -> str:
        return self.role.code if self.role else ""

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User {self.email} ({self.role_code})>"


class UserRole(IntPKMixin, TimestampMixin, Base):
    """Grants a role to a user, on top of the account's default ``role_id``.

    Most accounts hold exactly one role and have exactly one row here
    (matching ``role_id``, backfilled by migration). An account with more
    than one row (e.g. a Sede Coordinator who also tutors) chooses which
    role is active for the session at login — see ``AuthService`` and
    ``app.routes.auth_routes``. Downstream authorization is untouched: it
    always checks a single active ``identity.role_code``.
    """

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id", name="uq_user_roles_user_role"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)

    user: Mapped["User"] = relationship(back_populates="role_grants")
    role: Mapped["Role"] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<UserRole user_id={self.user_id} role_id={self.role_id}>"
