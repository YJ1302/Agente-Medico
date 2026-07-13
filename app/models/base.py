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


class IncidentSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IncidentStatus(str, enum.Enum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    RESOLVED = "resolved"
    CLOSED = "closed"


class AgentStatus(str, enum.Enum):
    """Result status of an agent execution."""

    SUCCESS = "success"
    NO_FINDINGS = "no_findings"
    NEEDS_REVIEW = "needs_review"
    ERROR = "error"
