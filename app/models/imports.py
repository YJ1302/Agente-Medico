"""Bulk-import models (Batch 2F).

A generic, profile-driven import pipeline shared by every import type (students,
sedes, tutors, coordinators, rotations and grade components). Grade imports are
realised through this same pipeline with ``profile == "grade_components"`` (see
DECISIONS_LOG D-028) — the grade *domain* tables live in ``grades.py``.

* ``ImportBatch`` — one upload/preview/confirm session and its history.
* ``ImportRow`` — one staged source row with its raw values, normalized values,
  validation messages and final outcome. The source sheet/row is preserved so a
  downloadable error report and full traceability are possible.

No file is ever imported automatically: a batch only leaves ``validated`` for
``confirmed``/``partial`` on an explicit human confirmation.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import (
    ImportMode,
    ImportStatus,
    IntPKMixin,
    SoftDeleteMixin,
    TimestampMixin,
)


class ImportBatch(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """One bulk-import session and its auditable outcome."""

    __tablename__ = "import_batches"

    code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)  # IMP-YYYY-NNNN
    profile: Mapped[str] = mapped_column(String(40), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Temp stored file (outside static); deleted after import unless retained.
    stored_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(30), default=ImportMode.CREATE_ONLY.value, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=ImportStatus.UPLOADED.value, nullable=False
    )
    # JSON: {target_field: source_column_header}
    mapping_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Hash of (file bytes + sheet + mapping); a confirmation with a different
    # hash than the one validated is rejected as stale.
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    total_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Optional sede scope captured at creation (own-sede coordinator imports).
    sede_scope_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), nullable=True)

    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    rows: Mapped[list["ImportRow"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class ImportRow(IntPKMixin, TimestampMixin, Base):
    """One staged source row: raw values, normalized values, outcome."""

    __tablename__ = "import_rows"

    batch_id: Mapped[int] = mapped_column(ForeignKey("import_batches.id"), nullable=False)
    batch: Mapped[ImportBatch] = relationship(back_populates="rows")

    row_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based source row
    source_sheet: Mapped[str | None] = mapped_column(String(120), nullable=True)

    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)         # {header: value}
    normalized_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # cleaned values
    messages_json: Mapped[str | None] = mapped_column(Text, nullable=True)    # [{level, field, message}]

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)     # create/update/skip

    target_entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    target_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
