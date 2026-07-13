"""Activity tracking models (Batch 2C).

* ``ActivityDefinition`` — a catalog entry describing an expected activity or
  procedure for a rotation, sourced from the official 'LISTA DE ACTIVIDADES'
  documents (see docs/ACTIVITY_CATALOG_SOURCE_MAP.md). Definitions with
  ``rotation_type_id is None`` are the four shared narrative categories
  (hospitalization/emergency/community/academic) common to every rotation.
* ``StudentActivity`` — a record that a specific student performed/logged an
  activity within one of their rotation assignments, moving through a
  deterministic verification workflow.
* ``ActivityReview`` — an append-only history of verify/reject/reopen actions
  on a ``StudentActivity``, so a later re-review never silently overwrites an
  earlier one (SECURITY_AND_PRIVACY_RULES.md audit requirements).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import IntPKMixin, TimestampMixin, utcnow

# -- ActivityDefinition enums (stored as plain strings for SQLite portability)
TARGET_FIXED = "fixed"
TARGET_NO_FIXED = "no_fixed_target"
TARGET_COMPLETION_ONLY = "completion_only"
TARGET_TYPES = {TARGET_FIXED, TARGET_NO_FIXED, TARGET_COMPLETION_ONLY}

EVIDENCE_NONE = "none"
EVIDENCE_ANONYMOUS_REFERENCE = "anonymous_reference"
EVIDENCE_OPTIONAL_ATTACHMENT = "optional_attachment"
EVIDENCE_POLICIES = {EVIDENCE_NONE, EVIDENCE_ANONYMOUS_REFERENCE, EVIDENCE_OPTIONAL_ATTACHMENT}

CATEGORY_HOSPITALIZATION = "hospitalization"
CATEGORY_EMERGENCY = "emergency"
CATEGORY_COMMUNITY = "community"
CATEGORY_ACADEMIC = "academic"
CATEGORY_CLINICAL_TOPIC = "clinical_topic"
CATEGORY_PROCEDURE = "procedure"
CATEGORIES = {
    CATEGORY_HOSPITALIZATION, CATEGORY_EMERGENCY, CATEGORY_COMMUNITY,
    CATEGORY_ACADEMIC, CATEGORY_CLINICAL_TOPIC, CATEGORY_PROCEDURE,
}

# -- StudentActivity status workflow
STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_VERIFIED = "verified"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"
# 'corrected' is not a resting state (see DECISIONS_LOG D-026): a rejected
# entry moves directly back to 'pending' on resubmission, with the correction
# recorded as an ActivityReview history row (action=REVIEW_CORRECTED).
ACTIVITY_STATUSES = {STATUS_DRAFT, STATUS_PENDING, STATUS_VERIFIED, STATUS_REJECTED, STATUS_CANCELLED}

REVIEW_VERIFIED = "verified"
REVIEW_REJECTED = "rejected"
REVIEW_REOPENED = "reopened"
REVIEW_CORRECTED = "corrected"


class ActivityDefinition(IntPKMixin, TimestampMixin, Base):
    """A catalog activity/procedure expected during a rotation."""

    __tablename__ = "activity_definitions"

    rotation_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("rotation_types.id"), nullable=True
    )
    rotation_type: Mapped["RotationType | None"] = relationship(  # noqa: F821
        back_populates="activity_definitions"
    )

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    target_type: Mapped[str] = mapped_column(String(20), default=TARGET_NO_FIXED, nullable=False)
    # Nullable: must be NULL for no_fixed_target/completion_only, a positive
    # integer for fixed. Never store NA as 0 (docs/ACTIVITY_CATALOG_SOURCE_MAP.md).
    target_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_label: Mapped[str | None] = mapped_column(String(40), nullable=True)

    requires_tutor_verification: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    evidence_policy: Mapped[str] = mapped_column(
        String(30), default=EVIDENCE_ANONYMOUS_REFERENCE, nullable=False
    )
    supervision_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    source_document: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_section: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_provisional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    student_activities: Mapped[list["StudentActivity"]] = relationship(
        back_populates="definition"
    )


class StudentActivity(IntPKMixin, TimestampMixin, Base):
    """A logged instance of a student performing a catalog activity."""

    __tablename__ = "student_activities"

    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), nullable=False)
    student: Mapped["Student"] = relationship(back_populates="activities")  # noqa: F821

    definition_id: Mapped[int] = mapped_column(
        ForeignKey("activity_definitions.id"), nullable=False
    )
    definition: Mapped[ActivityDefinition] = relationship(
        back_populates="student_activities"
    )

    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("rotation_assignments.id"), nullable=True
    )
    assignment: Mapped["RotationAssignment | None"] = relationship()  # noqa: F821

    performed_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    logged_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(20), default=STATUS_PENDING, nullable=False
    )
    # Anonymous evidence reference (e.g. "Historia N/A — sala 4, turno tarde");
    # never a patient identifier. Free text; validated by privacy_validator.
    evidence_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    reviews: Mapped[list["ActivityReview"]] = relationship(
        back_populates="student_activity", cascade="all, delete-orphan",
        order_by="ActivityReview.created_at",
    )


class ActivityReview(IntPKMixin, Base):
    """Append-only history of verify/reject/reopen/correct actions.

    A new row is added on every review action; existing rows are never edited,
    so the full reviewer/timestamp/comment history survives repeated
    correction-and-resubmission cycles (Batch 2C §5).
    """

    __tablename__ = "activity_reviews"

    student_activity_id: Mapped[int] = mapped_column(
        ForeignKey("student_activities.id"), nullable=False
    )
    student_activity: Mapped[StudentActivity] = relationship(back_populates="reviews")

    action: Mapped[str] = mapped_column(String(20), nullable=False)  # verified/rejected/reopened/corrected
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )
