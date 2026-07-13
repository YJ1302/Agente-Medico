"""User and Role models — authentication and role-based access control.

A ``Role`` carries a stable machine ``code`` (used by permission checks and
sidebar visibility) and a human-friendly display name. A ``User`` has exactly
one role in Part 1; the schema allows expanding to multiple roles later
without breaking existing data.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
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

    @property
    def role_code(self) -> str:
        return self.role.code if self.role else ""

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<User {self.email} ({self.role_code})>"
