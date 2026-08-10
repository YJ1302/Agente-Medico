"""Announcement model — a broadcast message from staff to sede members.

``sede_id`` is null for an institution-wide announcement (admin/university
only); otherwise it scopes the message to one sede's students, tutors and
coordinators. There is no per-recipient read tracking — Liz's request was
"send to everyone", not delivery receipts, so the list is simply visible to
everyone in scope, newest first.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IntPKMixin, SoftDeleteMixin, TimestampMixin


class Announcement(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "announcements"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
