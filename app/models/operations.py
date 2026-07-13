"""Operational models: alerts, formal documents and incidents.

* ``Alert`` — a detected condition surfaced on dashboards. Alerts distinguish
  automated detection from any agent recommendation and record who/what
  produced them (``source``) so the "detection vs recommendation vs human
  decision" separation stays explicit.
* ``DocumentRecord`` — a formal institutional communication with traceable
  statuses following the university/sede communication route.
* ``Incident`` — an issue affecting the normal development of the internship.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import (
    AlertSeverity,
    AlertStatus,
    DocumentStatus,
    IncidentSeverity,
    IncidentStatus,
    IntPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
)

# Alert categories map 1:1 to the deterministic rules in the rule engine.
ALERT_ROTATION_ENDING = "rotation_ending_soon"
ALERT_MISSING_TUTOR = "missing_tutor"
ALERT_PENDING_EVALUATION = "pending_evaluation"
ALERT_INCOMPLETE_PROFILE = "incomplete_profile"
# Batch 2B additional rules.
ALERT_OVERDUE_EVALUATION = "overdue_evaluation_after_rotation_end"
ALERT_STUDENT_OVERLAP = "student_rotation_overlap"
ALERT_TUTOR_SEDE_MISMATCH = "tutor_sede_mismatch"
ALERT_INSTITUTION_MISMATCH = "institution_mismatch"
# Batch 2C additional rules (activity tracking).
ALERT_ACTIVITY_TARGET_AT_RISK = "activity_target_at_risk"
ALERT_OLD_PENDING_ACTIVITY = "old_pending_activity"
ALERT_REJECTED_ACTIVITY_CORRECTION = "rejected_activity_requires_correction"
ALERT_ROTATION_COMPLETED_UNVERIFIED = "rotation_completed_with_unverified_activities"
ALERT_TUTOR_VERIFICATION_BACKLOG = "tutor_verification_backlog"
# Batch 2D additional rules (evaluation workflow).
ALERT_RETURNED_EVALUATION = "returned_evaluation_pending_correction"
ALERT_SUBMITTED_EVALUATION = "submitted_evaluation_waiting_approval"


class Alert(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A detected condition requiring attention, shown on dashboards."""

    __tablename__ = "alerts"

    category: Mapped[str] = mapped_column(String(60), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), default=AlertSeverity.WARNING.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=AlertStatus.OPEN.value, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # 'rule_engine' | 'agent' | 'manual' — makes the origin auditable.
    source: Mapped[str] = mapped_column(String(40), default="rule_engine", nullable=False)

    # Optional link back to the entity that triggered the alert.
    related_entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    related_entity_id: Mapped[int | None] = mapped_column(nullable=True)

    # True when a human must approve/act — never auto-actioned by an agent.
    requires_human_action: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )


class DocumentRecord(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A formal institutional communication with a traceable lifecycle."""

    __tablename__ = "document_records"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=DocumentStatus.DRAFT.value, nullable=False
    )

    # Communication route participants (free-text role/entity for the prototype).
    origin: Mapped[str | None] = mapped_column(String(120), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(120), nullable=True)

    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # File uploads are not implemented in Part 1; the path is reserved for the
    # future safe file-upload pipeline (see SECURITY_AND_PRIVACY_RULES.md).
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Incident(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An issue affecting the normal development of the internship."""

    __tablename__ = "incidents"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), default=IncidentSeverity.MEDIUM.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=IncidentStatus.OPEN.value, nullable=False
    )

    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), nullable=True
    )
    reported_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
