"""Reusable ORM mixins and shared enumerations.

These mixins encode cross-cutting design rules from PROJECT_RULEBOOK.md:

* Every table has ``created_at`` / ``updated_at`` timestamps.
* Records support a soft-delete flag and an active/inactive state instead of
  physical deletion, so history and audit trails are preserved.
* Integer surrogate primary keys are used consistently for the prototype.
  (A future PostgreSQL migration may switch to UUIDs; the repository layer
  isolates callers from the key type — see DECISIONS_LOG.md.)
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp (avoids naive-datetime ambiguity)."""
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Adds auditable creation/update timestamps to a model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class SoftDeleteMixin:
    """Adds soft-delete + active state, so rows are never hard-deleted."""

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class IntPKMixin:
    """Standard integer surrogate primary key."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)


# ---------------------------------------------------------------------------
# Shared enumerations (stored as plain strings for SQLite portability)
# ---------------------------------------------------------------------------
class InstitutionCode(str, enum.Enum):
    """The two internship provider systems in scope for the internship."""

    MINSA = "MINSA"
    ESSALUD = "ESSALUD"


class StudentCycle(str, enum.Enum):
    """Medical internship cycles."""

    CYCLE_13 = "13"
    CYCLE_14 = "14"


class AssignmentStatus(str, enum.Enum):
    """Lifecycle status of a rotation assignment."""

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class EvaluationStatus(str, enum.Enum):
    """Lifecycle status of a rotation evaluation."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    RETURNED_FOR_CORRECTION = "returned_for_correction"
    APPROVED = "approved"


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class DocumentStatus(str, enum.Enum):
    """Traceable statuses for formal institutional communication."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class DocumentPriority(str, enum.Enum):
    """Priority of a formal document (display/triage only, never auto-actioned)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class VisibilityLevel(str, enum.Enum):
    """Confidentiality level applied to documents and incidents.

    * ``normal`` — visible to any authorized role within scope.
    * ``restricted`` — internal notes hidden from the student.
    * ``confidential`` — Administrator / University Coordinator only, unless the
      record is explicitly assigned to another user.
    """

    NORMAL = "normal"
    RESTRICTED = "restricted"
    CONFIDENTIAL = "confidential"


class IncidentSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    # Batch 2E — added to drive prominent dashboard alerts.
    CRITICAL = "critical"


class IncidentStatus(str, enum.Enum):
    OPEN = "open"
    # ``IN_REVIEW`` kept for backward compatibility with pre-2E rows; the 2E
    # workflow uses ``UNDER_REVIEW`` as the canonical value.
    IN_REVIEW = "in_review"
    UNDER_REVIEW = "under_review"
    ACTION_REQUIRED = "action_required"
    RESOLVED = "resolved"
    CLOSED = "closed"
    DISMISSED = "dismissed"
    REOPENED = "reopened"


class AgentStatus(str, enum.Enum):
    """Result status of an agent execution."""

    SUCCESS = "success"
    NO_FINDINGS = "no_findings"
    NEEDS_REVIEW = "needs_review"
    ERROR = "error"


class ImportStatus(str, enum.Enum):
    """Lifecycle of a bulk-import batch (Batch 2F)."""

    UPLOADED = "uploaded"        # file stored, sheet/mapping not chosen yet
    MAPPED = "mapped"            # sheet + column mapping chosen
    VALIDATED = "validated"      # dry-run validation done (preview ready)
    CONFIRMED = "confirmed"      # imported (transactionally)
    PARTIAL = "partial"          # imported valid rows only (some skipped/failed)
    CANCELLED = "cancelled"
    FAILED = "failed"            # import aborted (all-or-nothing rollback)


class ImportMode(str, enum.Enum):
    """How an import treats existing/duplicate/invalid rows."""

    CREATE_ONLY = "create_only"
    UPDATE_EXISTING = "update_existing"
    SKIP_DUPLICATES = "skip_duplicates"
    VALID_ONLY = "valid_only"          # import valid rows, skip invalid
    ALL_OR_NOTHING = "all_or_nothing"  # any error cancels the whole import


class ImportRowStatus(str, enum.Enum):
    """Per-row status during preview/validation and after import."""

    PENDING = "pending"
    VALID = "valid"
    WARNING = "warning"
    ERROR = "error"
    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"
    FAILED = "failed"


class GradeSchemeStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class GradeComponentStatus(str, enum.Enum):
    """Status of a single student grade component value."""

    DRAFT = "draft"
    IMPORTED = "imported"
    APPROVED = "approved"


# Recognised grade-component categories (Batch 2F). Weights are NOT encoded here —
# they remain configurable and may be null until the client confirms them.
GRADE_CATEGORIES: dict[str, str] = {
    "actitudinal": "Actitudinal",
    "desempeno": "Desempeño",
    "conocimiento": "Conocimiento",
    "etica": "Ética y profesionalismo",
    "participacion": "Participación/asistencia",
    "portafolio": "Portafolio",
    "simulacro_enam": "Simulacros ENAM",
    "examen_oral": "Examen oral",
    "examen_escrito": "Examen escrito/final",
    "evaluacion_docente": "Evaluación docente",
    "otro": "Otro",
}
