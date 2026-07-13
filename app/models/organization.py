"""Organizational models: institution types, sedes and staff profiles.

* ``InstitutionType`` — MINSA or EsSalud (the two provider systems).
* ``Sede`` — a teaching hospital or health center where the internship runs.
* ``SedeCoordinatorProfile`` — the docente who coordinates a sede and is the
  institutional nexus with the university.
* ``TutorProfile`` — a tutor who supervises and evaluates interns per service.

Profiles are separate from ``User`` so that role-specific attributes do not
bloat the accounts table, while still linking back to a login account.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import IntPKMixin, SoftDeleteMixin, TimestampMixin


class InstitutionType(IntPKMixin, TimestampMixin, Base):
    """A provider system: MINSA or EsSalud.

    ``code`` matches ``InstitutionCode``. ``has_community_component`` flags that
    MINSA placements may include an additional community rotation.
    """

    __tablename__ = "institution_types"

    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # MINSA may use ranking; EsSalud may use examination results.
    placement_method: Mapped[str | None] = mapped_column(String(60), nullable=True)
    has_community_component: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    sedes: Mapped[list["Sede"]] = relationship(back_populates="institution_type")
    students: Mapped[list["Student"]] = relationship(  # noqa: F821
        back_populates="institution_type"
    )


class Sede(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A teaching site — hospital or health center — hosting the internship."""

    __tablename__ = "sedes"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # 'hospital' or 'health_center'
    sede_type: Mapped[str] = mapped_column(String(40), default="hospital", nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    institution_type_id: Mapped[int] = mapped_column(
        ForeignKey("institution_types.id"), nullable=False
    )
    institution_type: Mapped[InstitutionType] = relationship(back_populates="sedes")

    coordinators: Mapped[list["SedeCoordinatorProfile"]] = relationship(
        back_populates="sede"
    )
    tutors: Mapped[list["TutorProfile"]] = relationship(back_populates="sede")
    students: Mapped[list["Student"]] = relationship(  # noqa: F821
        back_populates="sede"
    )
    rotation_assignments: Mapped[list["RotationAssignment"]] = relationship(  # noqa: F821
        back_populates="sede"
    )


class SedeCoordinatorProfile(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Docente responsible for coordinating a sede and liaising with the UPeU."""

    __tablename__ = "sede_coordinator_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    user: Mapped["User"] = relationship(back_populates="sede_coordinator_profile")  # noqa: F821

    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id"), nullable=False)
    sede: Mapped[Sede] = relationship(back_populates="coordinators")

    specialty: Mapped[str | None] = mapped_column(String(120), nullable=True)
    office_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # A sede has at most one *active* principal coordinator (Part 2A MVP).
    # Kept explicit so future secondary/support coordinators can coexist.
    is_principal: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class TutorProfile(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A rotation tutor who supervises interns in a specific service/sede."""

    __tablename__ = "tutor_profiles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=False
    )
    user: Mapped["User"] = relationship(back_populates="tutor_profile")  # noqa: F821

    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id"), nullable=False)
    sede: Mapped[Sede] = relationship(back_populates="tutors")

    # Medical specialty of the tutor (e.g. "Cirujano general").
    specialty: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The clinical service the tutor is responsible for (e.g. "Medicina Interna").
    service: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    rotation_assignments: Mapped[list["RotationAssignment"]] = relationship(  # noqa: F821
        back_populates="tutor"
    )
