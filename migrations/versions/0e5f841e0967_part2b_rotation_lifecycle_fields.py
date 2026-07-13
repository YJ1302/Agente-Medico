"""part2b rotation lifecycle fields

Revision ID: 0e5f841e0967
Revises: 7fb2a9a545a7
Create Date: 2026-07-12 13:37:11.235514
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0e5f841e0967'
down_revision: str | None = '7fb2a9a545a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite supports ``ALTER TABLE ADD COLUMN`` natively, so we avoid batch
    # mode (which would recreate the table and fail on the pre-existing unnamed
    # foreign keys). The two user references are added as plain nullable integer
    # columns; the ORM declares the ForeignKey for relationships and a future
    # PostgreSQL migration can add the named constraint there.
    op.add_column('rotation_assignments', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('rotation_assignments', sa.Column('cancellation_reason', sa.Text(), nullable=True))
    op.add_column('rotation_assignments', sa.Column('reopened_reason', sa.Text(), nullable=True))
    op.add_column('rotation_assignments', sa.Column('override_reason', sa.Text(), nullable=True))
    op.add_column('rotation_assignments', sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('rotation_assignments', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('rotation_assignments', sa.Column('reopened_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('rotation_assignments', sa.Column('created_by_user_id', sa.Integer(), nullable=True))
    op.add_column('rotation_assignments', sa.Column('updated_by_user_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    for col in ('updated_by_user_id', 'created_by_user_id', 'reopened_at',
                'cancelled_at', 'completed_at', 'override_reason',
                'reopened_reason', 'cancellation_reason', 'notes'):
        op.drop_column('rotation_assignments', col)
