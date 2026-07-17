"""Evaluation models derived from the official 'FORMATO DE EVALUACION INTERNO'.

The evaluation has three areas — Conocimientos, Desempeño, Actitudinal — each
with several criteria scored 0..4:
    4 Muy satisfactorio · 3 Satisfactorio · 2 Casi satisfactorio ·
    1 Poco satisfactorio · 0 Inaceptable

Each area total is the sum of its criteria; the final rotation note is the
average of the three area scores. ``EvaluationCriterion`` stores one scored
line item so the exact instrument is reproduced faithfully and remains
auditable.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import (
    EvaluationStatus,
    IntPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
)

# The three official evaluation areas.
AREA_KNOWLEDGE = "conocimientos"
AREA_PERFORMANCE = "desempeno"
AREA_ATTITUDE = "actitudinal"

EVALUATION_SCALE = {
    4: "Muy satisfactorio",
    3: "Satisfactorio",
    2: "Casi satisfactorio",
    1: "Poco satisfactorio",
    0: "Inaceptable",
}


class Evaluation(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A rotation-end evaluation submitted by the tutor for a student."""

    __tablename__ = "evaluations"

    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("rotation_assignments.id"), unique=True, nullable=False
    )
    assignment: Mapped["RotationAssignment"] = relationship(  # noqa: F821
        back_populates="evaluation"
    )

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    student: Mapped["Student"] = relationship(back_populates="evaluations")  # noqa: F821

    tutor_id: Mapped[int | None] = mapped_column(
        ForeignKey("tutor_profiles.id"), nullable=True
    )

    status: Mapped[str] = mapped_column(
        # 30, not 20: EvaluationStatus.RETURNED_FOR_CORRECTION is 24 chars.
        # SQLite never enforces VARCHAR length so this was invisible there;
        # PostgreSQL does (see DECISIONS_LOG.md D-032).
        String(30), default=EvaluationStatus.PENDING.value, nullable=False
    )

    # Cached aggregate scores (computed from criteria when submitted).
    score_knowledge: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_performance: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_attitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    comments: Mapped[str | None] = mapped_column(Text, nullable=True)  # tutor comments

    # -- Batch 2D lifecycle & traceability fields ------------------------
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    # Coordinator's comments: mandatory when returning for correction, optional on approval.
    review_comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    criteria: Mapped[list["EvaluationCriterion"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )


class EvaluationCriterion(IntPKMixin, TimestampMixin, Base):
    """One scored criterion line within an evaluation area."""

    __tablename__ = "evaluation_criteria"

    evaluation_id: Mapped[int] = mapped_column(
        ForeignKey("evaluations.id"), nullable=False
    )
    evaluation: Mapped[Evaluation] = relationship(back_populates="criteria")

    area: Mapped[str] = mapped_column(String(30), nullable=False)  # AREA_* constants
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 0..4 per the official scale; nullable until the tutor scores it.
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
