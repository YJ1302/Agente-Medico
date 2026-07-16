"""Academic grade architecture (Batch 2F foundation).

Configurable, versioned grading schemes and their per-student component scores.
This is the **foundation** reserved for the future Academic Grade Agent — the
system stores components faithfully but does **not** compute a final grade until
the official weights are confirmed.

Key invariants (GRADE_IMPORT_RULES.md):

* A component ``weight_percent`` may remain ``NULL`` until the client confirms
  it; ``GradeScheme.weights_confirmed`` gates any final-grade calculation.
* ``StudentGradeComponent.score`` is nullable: ``NULL`` means *not registered*
  and is always kept distinct from a real ``0``.
* An existing **approved** component is never overwritten silently — updates go
  through a confirmed import and are recorded in ``GradeComponentHistory``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import (
    GradeComponentStatus,
    GradeSchemeStatus,
    IntPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class GradeScheme(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A configurable, versioned grading scheme for a course/rotation + period."""

    __tablename__ = "grade_schemes"

    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    rotation_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("rotation_types.id"), nullable=True
    )
    period_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_periods.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=GradeSchemeStatus.DRAFT.value, nullable=False
    )
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Final grades are only computable once this is True AND every required
    # component has a non-null weight. Until then the UI shows the pending note.
    weights_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    components: Mapped[list["GradeComponentDefinition"]] = relationship(
        back_populates="scheme", cascade="all, delete-orphan"
    )


class GradeComponentDefinition(IntPKMixin, TimestampMixin, Base):
    """One component (column) of a grading scheme."""

    __tablename__ = "grade_component_definitions"

    scheme_id: Mapped[int] = mapped_column(ForeignKey("grade_schemes.id"), nullable=False)
    scheme: Mapped[GradeScheme] = relationship(back_populates="components")

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)  # GRADE_CATEGORIES
    # Nullable ON PURPOSE — may stay null until the client confirms the formula.
    weight_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, default=20.0, nullable=False)
    source: Mapped[str | None] = mapped_column(String(120), nullable=True)  # source sheet/label
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StudentGradeComponent(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A single student's score for one scheme component."""

    __tablename__ = "student_grade_components"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    scheme_id: Mapped[int] = mapped_column(ForeignKey("grade_schemes.id"), nullable=False)
    component_id: Mapped[int] = mapped_column(
        ForeignKey("grade_component_definitions.id"), nullable=False
    )

    # NULL = not registered (kept distinct from a real 0.0).
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=GradeComponentStatus.DRAFT.value, nullable=False
    )
    source_type: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # manual|import
    source_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_batches.id"), nullable=True
    )
    source_sheet: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_row: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_col: Mapped[str | None] = mapped_column(String(20), nullable=True)

    entered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)


class GradeComponentHistory(IntPKMixin, TimestampMixin, Base):
    """Append-only history of every change to a student grade component."""

    __tablename__ = "grade_component_history"

    student_grade_component_id: Mapped[int] = mapped_column(
        ForeignKey("student_grade_components.id"), nullable=False
    )
    old_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    old_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(160), default="system", nullable=False)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
