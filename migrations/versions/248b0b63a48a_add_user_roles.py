"""add user_roles (multi-role support)

Revision ID: 248b0b63a48a
Revises: 776a4d2055c8
Create Date: 2026-08-19 00:00:00.000000

New join table letting an account hold more than one role (e.g. a Sede
Coordinator who also tutors interns). Backfills one row per existing user
from their current ``role_id`` so every account keeps working exactly as
before until an admin explicitly grants a second role.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision: str = '248b0b63a48a'
down_revision: str | None = '776a4d2055c8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'user_roles',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('roles.id'), nullable=False),
        sa.UniqueConstraint('user_id', 'role_id', name='uq_user_roles_user_role'),
    )
    op.create_index('ix_user_roles_user_id', 'user_roles', ['user_id'])

    # Backfill: every existing account keeps its current single role.
    conn = op.get_bind()
    now = datetime.now(timezone.utc)
    users_table = sa.table('users', sa.column('id', sa.Integer()),
                            sa.column('role_id', sa.Integer()))
    user_roles_table = sa.table(
        'user_roles', sa.column('user_id', sa.Integer()),
        sa.column('role_id', sa.Integer()),
        sa.column('created_at', sa.DateTime(timezone=True)),
        sa.column('updated_at', sa.DateTime(timezone=True)),
    )
    rows = conn.execute(sa.select(users_table.c.id, users_table.c.role_id)).fetchall()
    if rows:
        conn.execute(
            user_roles_table.insert(),
            [{"user_id": r.id, "role_id": r.role_id, "created_at": now, "updated_at": now}
             for r in rows],
        )


def downgrade() -> None:
    op.drop_index('ix_user_roles_user_id', table_name='user_roles')
    op.drop_table('user_roles')
