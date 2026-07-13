"""Student model — the intern.

Personal identifiers are intentionally minimal for the prototype and MUST be
fictional (see SECURITY_AND_PRIVACY_RULES.md). No patient clinical information
is ever attached to a student record.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import IntPKMixin, SoftDeleteMixin, TimestampMixin


class Student(IntPKMixin, TimestampMixin, SoftDeleteMixin, Base):
    """An intern student enrolled in the medical internship."""

    __tablename__ = "students"

    # Optional link to a login account (a student may exist before an account
    # is provisioned).
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), unique=True, nullable=True
    )
    user: Mapped["User | None"] = relationship(back_populates="student_profile")  # noqa: F821

    student_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    # Fictional document id for the demo only.
    document_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Internship cycle: "13" or "14".
    cycle: Mapped[str] = mapped_column(String(2), default="13", nullable=False)

    institution_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("institution_types.id"), nullable=True
    )
    institution_type: Mapped["InstitutionType | None"] = relationship(  # noqa: F821
        back_populates="students"
    )

    sede_id: Mapped[int | None] = mapped_column(ForeignKey("sedes.id"), nullable=True)
    sede: Mapped["Sede | None"] = relationship(back_populates="students")  # noqa: F821

    internship_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    internship_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    # 'complete' or 'incomplete' — drives the incomplete-profile alert rule.
    profile_status: Mapped[str] = mapped_column(
        String(20), default="complete", nullable=False
    )

    rotation_assignments: Mapped[list["RotationAssignment"]] = relationship(  # noqa: F821
        back_populates="student"
    )
    evaluations: Mapped[list["Evaluation"]] = relationship(  # noqa: F821
        back_populates="student"
    )
    activities: Mapped[list["StudentActivity"]] = relationship(  # noqa: F821
        back_populates="student"
    )
