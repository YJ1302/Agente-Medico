"""Audit and agent-execution models.

* ``AuditLog`` — an append-only record of important actions. Part 1 provides
  the schema and a helper; wiring every mutation into it is completed in later
  parts (PROJECT_RULEBOOK.md requires all important actions to eventually
  support audit logging).
* ``AgentExecution`` — a persisted record of every agent run, capturing the
  structured agent response so automated detection and recommendations remain
  transparent and reviewable.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IntPKMixin, TimestampMixin


class AuditLog(IntPKMixin, TimestampMixin, Base):
    """Append-only audit trail entry for an important action."""

    __tablename__ = "audit_logs"

    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    actor_label: Mapped[str] = mapped_column(String(160), default="system", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # JSON-serialized detail payload (stored as text for SQLite portability).
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AgentExecution(IntPKMixin, TimestampMixin, Base):
    """A persisted record of one agent run and its structured response."""

    __tablename__ = "agent_executions"

    agent_name: Mapped[str] = mapped_column(String(80), nullable=False)
    task: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-serialized lists (stored as text for SQLite portability).
    findings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_actions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_approval: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    # Milliseconds the agent took to run (for the executions dashboard).
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(80), default="system", nullable=False)
