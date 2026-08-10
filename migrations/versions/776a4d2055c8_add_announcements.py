"""add announcements table

Revision ID: 776a4d2055c8
Revises: c3f7a1b9d2e6
Create Date: 2026-08-10 00:00:00.000000

Brand-new table (no ALTER of existing tables). ``sede_id`` null means an
institution-wide announcement; a value scopes it to one sede's students,
tutors and coordinators.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '776a4d2055c8'
down_revision: str | None = 'c3f7a1b9d2e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ts_soft():
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        'announcements',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        *_ts_soft(),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('sede_id', sa.Integer(), sa.ForeignKey('sedes.id'), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=True),
    )
    op.create_index('ix_announcements_sede', 'announcements', ['sede_id'])
    op.create_index('ix_announcements_created_at', 'announcements', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_announcements_created_at', table_name='announcements')
    op.drop_index('ix_announcements_sede', table_name='announcements')
    op.drop_table('announcements')
