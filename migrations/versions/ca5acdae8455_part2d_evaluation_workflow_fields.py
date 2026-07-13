"""part2d evaluation workflow fields

Revision ID: ca5acdae8455
Revises: e6118382e890
Create Date: 2026-07-12 23:16:52.319161

NOTE ON SQLITE STRATEGY (see docs/DECISIONS_LOG.md D-022):
All new columns are nullable, so plain ``ADD COLUMN`` is used instead of batch
mode. Batch mode would recreate the table and crash on ``evaluations``'
pre-existing unnamed foreign keys ("Constraint must have a name"). The two new
user references are added as plain nullable integer columns without a DB-level
FK constraint (the ORM still declares the ForeignKey for relationships), the
same approach used for ``rotation_assignments.created_by_user_id`` in Batch 2B.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ca5acdae8455'
down_revision: str | None = 'e6118382e890'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('evaluations', sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('evaluations', sa.Column('submitted_by_user_id', sa.Integer(), nullable=True))
    op.add_column('evaluations', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('evaluations', sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True))
    op.add_column('evaluations', sa.Column('review_comments', sa.Text(), nullable=True))
    op.add_column('evaluations', sa.Column('reopened_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('evaluations', sa.Column('reopened_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ('reopened_reason', 'reopened_at', 'review_comments',
                'reviewed_by_user_id', 'reviewed_at', 'submitted_by_user_id',
                'submitted_at'):
        op.drop_column('evaluations', col)
