"""Academic scheduling models: periods, rotation types and assignments.

The internship year is divided into bimonthly ``AcademicPeriod`` blocks
(Ene-Feb, Mar-Abr, ...), matching the university's programming spreadsheet.
A ``RotationAssignment`` places one student in one rotation, at one sede, with
one tutor, during one period — the operational heart of the platform.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import (
    AssignmentStatus,
    IntPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class AcademicPeriod(IntPKMixin, TimestampMixin, Base):
    """A bimonthly block of the internship calendar (e.g. 'Ene-Feb 2026')."""

    __tablename__ = "academic_periods"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)  # 1..6 within the year
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    rotation_assignments: Mapped[list["RotationAssignment"]] = relationship(
        back_populates="period"
    )


class RotationType(IntPKMixin, TimestampMixin, Base):
    """A kind of rotation (Medicina Interna, Cirugía, Pediatría, Gineco-Obst.)."""

    __tablename__ = "rotation_types"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether this is a core rotation or an additional component (e.g. community).
    is_core: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    typical_weeks: Mapped[int] = mapped_column(default=8, nullable=False)

    rotation_assignments: Mapped[list["RotationAssignment"]] = relationship(
        back_populates="rotation_type"
    )
    activity_definitions: Mapped[list["ActivityDefinition"]] = relationship(  # noqa: F821
        back_populates="rotation_type"
    )


class RotationAssignment(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A student's placement in a rotation, at a sede, with a tutor, in a period.

    ``tutor_id`` is nullable on purpose: an assignment can be planned before a
    tutor is designated, which the monitoring agent flags as a missing-tutor
    alert.
    """

    __tablename__ = "rotation_assignments"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    student: Mapped["Student"] = relationship(back_populates="rotation_assignments")  # noqa: F821

    rotation_type_id: Mapped[int] = mapped_column(
        ForeignKey("rotation_types.id"), nullable=False
    )
    rotation_type: Mapped[RotationType] = relationship(
        back_populates="rotation_assignments"
    )

    sede_id: Mapped[int] = mapped_column(ForeignKey("sedes.id"), nullable=False)
    sede: Mapped["Sede"] = relationship(back_populates="rotation_assignments")  # noqa: F821

    period_id: Mapped[int] = mapped_column(
        ForeignKey("academic_periods.id"), nullable=False
    )
    period: Mapped[AcademicPeriod] = relationship(back_populates="rotation_assignments")

    tutor_id: Mapped[int | None] = mapped_column(
        ForeignKey("tutor_profiles.id"), nullable=True
    )
    tutor: Mapped["TutorProfile | None"] = relationship(  # noqa: F821
        back_populates="rotation_assignments"
    )

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=AssignmentStatus.PLANNED.value, nullable=False
    )

    # -- Batch 2B lifecycle & traceability fields ------------------------
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Reasons captured for high-impact transitions (also mirrored to the audit
    # log); kept on the record so the detail page can display recent history.
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reopened_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Justification recorded when an authorized user overrides a blocking
    # conflict (institution/community/period-date).
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    evaluation: Mapped["Evaluation | None"] = relationship(  # noqa: F821
        back_populates="assignment", uselist=False
    )
