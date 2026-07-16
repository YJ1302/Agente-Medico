"""Operational models: alerts, formal documents, incidents and attachments.

* ``Alert`` — a detected condition surfaced on dashboards. Alerts distinguish
  automated detection from any agent recommendation and record who/what
  produced them (``source``) so the "detection vs recommendation vs human
  decision" separation stays explicit.
* ``DocumentRecord`` — a formal institutional communication with traceable
  statuses following the university/sede communication route (Batch 2E adds the
  full lifecycle, numbering, priority and confidentiality fields).
* ``Incident`` — an issue affecting the normal development of the internship
  (Batch 2E adds typing, responsibility, resolution and confidentiality).
* ``Attachment`` — a polymorphic secure file attachment shared by documents and
  incidents (see FILE_UPLOAD_SECURITY.md).
* ``StatusHistory`` — an append-only workflow trail shared by documents and
  incidents so a status change is never silently overwritten.
* ``DocumentTemplate`` — a reusable body template that seeds an editable draft.
* ``DocumentSequence`` — per-year counter backing the concurrency-safe
  ``DOC-YYYY-NNNN`` numbering.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import (
    AlertSeverity,
    AlertStatus,
    DocumentPriority,
    DocumentStatus,
    IncidentSeverity,
    IncidentStatus,
    IntPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VisibilityLevel,
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
# Batch 2E additional rules (documents & incidents).
ALERT_DOC_WAITING_REVIEW = "document_waiting_review"
ALERT_DOC_REJECTED_PENDING = "document_rejected_pending_correction"
ALERT_DOC_OVERDUE = "document_overdue"
ALERT_HIGH_SEVERITY_INCIDENT = "high_severity_incident"
ALERT_CRITICAL_INCIDENT = "critical_incident"
ALERT_INCIDENT_DUE_SOON = "incident_due_soon"
ALERT_INCIDENT_OVERDUE = "incident_overdue"
ALERT_UNRESOLVED_INCIDENT_NEAR_ROTATION_END = "unresolved_incident_near_rotation_end"


# ---------------------------------------------------------------------------
# Controlled vocabularies (stored as plain strings; kept as lists so the UI can
# render Spanish labels while the DB holds a stable machine code).
# ---------------------------------------------------------------------------
# doc_type code -> Spanish label.
DOCUMENT_TYPES: dict[str, str] = {
    "resignation": "Renuncia al internado",
    "sede_change": "Cambio de sede",
    "rotation_change": "Cambio de rotación",
    "tutor_designation": "Designación de tutor",
    "coordinator_designation": "Designación de coordinador",
    "permission": "Permiso",
    "medical_leave": "Descanso médico",
    "internship_interruption": "Interrupción de internado",
    "internship_resumption": "Reanudación de internado",
    "grade_correction": "Corrección de nota",
    "incident_report": "Informe de incidente",
    "official_communication": "Comunicación oficial",
    "other": "Otro",
}

# Document types a Student may originate (USER_ROLES_AND_PERMISSIONS.md).
STUDENT_DOCUMENT_TYPES = {"resignation", "sede_change", "permission", "medical_leave"}

# incident_type code -> Spanish label.
INCIDENT_TYPES: dict[str, str] = {
    "absence": "Inasistencia",
    "repeated_tardiness": "Tardanza reiterada",
    "activity_noncompliance": "Incumplimiento de actividades",
    "conduct": "Problema de conducta",
    "health": "Problema de salud",
    "student_complaint": "Queja del estudiante",
    "tutor_complaint": "Queja del tutor",
    "sede_complaint": "Queja de la sede",
    "rotation_interruption": "Interrupción de rotación",
    "resignation": "Renuncia",
    "accident": "Accidente",
    "confidentiality": "Confidencialidad",
    "other": "Otro",
}

# Attachment owner types.
OWNER_DOCUMENT = "document"
OWNER_INCIDENT = "incident"


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
    # Numbering support: the year and per-year sequence the code was drawn from.
    seq_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seq_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default=DocumentStatus.DRAFT.value, nullable=False
    )
    priority: Mapped[str] = mapped_column(
        String(20), default=DocumentPriority.NORMAL.value, nullable=False
    )
    visibility: Mapped[str] = mapped_column(
        String(20), default=VisibilityLevel.NORMAL.value, nullable=False
    )

    # Communication route participants (free-text role/entity for the prototype).
    origin: Mapped[str | None] = mapped_column(String(160), nullable=True)
    destination: Mapped[str | None] = mapped_column(String(160), nullable=True)

    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), nullable=True
    )
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("rotation_assignments.id"), nullable=True
    )

    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A restricted internal note, hidden from students (visibility enforcement).
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reserved from Part 1 (single legacy path); real uploads use Attachment.
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # -- Lifecycle traceability -----------------------------------------
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopened_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A due date used by the overdue-document rule (optional).
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    sede: Mapped["Sede | None"] = relationship()  # noqa: F821
    student: Mapped["Student | None"] = relationship()  # noqa: F821


class Incident(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An issue affecting the normal development of the internship."""

    __tablename__ = "incidents"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    seq_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seq_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    incident_type: Mapped[str] = mapped_column(String(60), default="other", nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), default=IncidentSeverity.MEDIUM.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=IncidentStatus.OPEN.value, nullable=False
    )
    visibility: Mapped[str] = mapped_column(
        String(20), default=VisibilityLevel.NORMAL.value, nullable=False
    )

    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), nullable=True)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id"), nullable=True
    )
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("rotation_assignments.id"), nullable=True
    )

    # Legacy free-text reporter (Part 1); the FK is the authoritative reporter.
    reported_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reported_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # A restricted internal note, hidden from students.
    internal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismiss_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reopened_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    sede: Mapped["Sede | None"] = relationship()  # noqa: F821
    student: Mapped["Student | None"] = relationship()  # noqa: F821


class Attachment(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A secure, locally-stored file attached to a document or incident.

    The original filename is recorded for display only; the file is stored under
    an internally-generated ``stored_filename`` outside the public static folder
    and served only through an authorized route (see FILE_UPLOAD_SECURITY.md).
    """

    __tablename__ = "attachments"

    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)  # document|incident
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    deleted_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class StatusHistory(IntPKMixin, TimestampMixin, Base):
    """Append-only workflow trail for a document or incident status change."""

    __tablename__ = "status_history"

    owner_type: Mapped[str] = mapped_column(String(20), nullable=False)  # document|incident
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)

    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_label: Mapped[str] = mapped_column(String(160), default="system", nullable=False)
    # A short, non-confidential note or reason (mandatory for reject/dismiss/reopen).
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentTemplate(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A reusable body template that seeds an editable draft (never auto-approved)."""

    __tablename__ = "document_templates"

    code: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_template: Mapped[str | None] = mapped_column(String(300), nullable=True)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)


class DocumentSequence(Base):
    """Per-year counter backing concurrency-safe ``DOC-YYYY-NNNN`` numbering.

    A single row per (kind, year). Allocation performs an atomic
    ``UPDATE ... SET last_value = last_value + 1`` inside the caller's
    transaction; SQLite serializes writers so two concurrent allocations cannot
    return the same value. A UNIQUE constraint on the generated code is the
    final backstop.
    """

    __tablename__ = "document_sequences"
    __table_args__ = (UniqueConstraint("kind", "year", name="uq_sequence_kind_year"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # 'document' | 'incident'
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    last_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
