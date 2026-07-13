"""part2c activity tracking catalog and workflow

Revision ID: e6118382e890
Revises: 0e5f841e0967
Create Date: 2026-07-12 22:20:39.286760

NOTE ON SQLITE STRATEGY (see docs/DECISIONS_LOG.md D-022/D-027):
SQLite cannot ALTER a column's NOT NULL constraint in place, and Alembic's
batch-mode auto-recreate crashes ("Constraint must have a name") on this
table because ``rotation_type_id`` has a pre-existing unnamed foreign key.
``activity_definitions.target_count`` must become nullable (a `no_fixed_target`
/ `completion_only` definition stores NULL, never 0 — see
ACTIVITY_CATALOG_SOURCE_MAP.md), so this migration performs a manual,
explicitly-named table rebuild instead of using batch mode. ``code``
uniqueness is enforced with a separate unique index (not a NOT NULL column
constraint) so existing rows can be safely backfilled first.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6118382e890'
down_revision: str | None = '0e5f841e0967'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- 1. New history table (no existing constraints to conflict with). ---
    op.create_table(
        'activity_reviews',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('student_activity_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('reviewer_user_id', sa.Integer(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['reviewer_user_id'], ['users.id'],
                                name='fk_activity_reviews_reviewer_user_id'),
        sa.ForeignKeyConstraint(['student_activity_id'], ['student_activities.id'],
                                name='fk_activity_reviews_student_activity_id'),
        sa.PrimaryKeyConstraint('id'),
    )

    # -- 2. Rebuild activity_definitions with a named FK (avoids the batch- ---
    #       mode crash) and target_count truly nullable.
    op.create_table(
        'activity_definitions_new',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rotation_type_id', sa.Integer(), nullable=True),
        sa.Column('code', sa.String(length=40), nullable=True),
        sa.Column('name', sa.String(length=240), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_type', sa.String(length=20), nullable=False,
                  server_default='no_fixed_target'),
        sa.Column('target_count', sa.Integer(), nullable=True),
        sa.Column('unit_label', sa.String(length=40), nullable=True),
        sa.Column('requires_tutor_verification', sa.Boolean(), nullable=False,
                  server_default=sa.true()),
        sa.Column('evidence_policy', sa.String(length=30), nullable=False,
                  server_default='anonymous_reference'),
        sa.Column('supervision_required', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('source_document', sa.String(length=200), nullable=True),
        sa.Column('source_year', sa.Integer(), nullable=True),
        sa.Column('source_section', sa.String(length=120), nullable=True),
        sa.Column('is_provisional', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['rotation_type_id'], ['rotation_types.id'],
                                name='fk_activity_definitions_rotation_type_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("""
        INSERT INTO activity_definitions_new
            (id, rotation_type_id, code, name, category, description,
             target_type, target_count, created_at, updated_at)
        SELECT
            id, rotation_type_id, 'LEGACY-' || id, name, category, description,
            'no_fixed_target', NULL, created_at, updated_at
        FROM activity_definitions
    """)
    op.drop_table('activity_definitions')
    op.rename_table('activity_definitions_new', 'activity_definitions')
    op.create_index('ix_activity_definitions_code', 'activity_definitions',
                    ['code'], unique=True)

    # -- 3. student_activities: plain nullable ADD COLUMN (no rebuild needed). --
    op.add_column('student_activities', sa.Column('evidence_reference', sa.String(length=255), nullable=True))
    op.add_column('student_activities', sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('student_activities', sa.Column('created_by_user_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('student_activities', 'created_by_user_id')
    op.drop_column('student_activities', 'submitted_at')
    op.drop_column('student_activities', 'evidence_reference')

    op.create_table(
        'activity_definitions_old',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('rotation_type_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('category', sa.String(length=80), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['rotation_type_id'], ['rotation_types.id'],
                                name='fk_activity_definitions_rotation_type_id'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute("""
        INSERT INTO activity_definitions_old
            (id, rotation_type_id, name, category, description, target_count,
             created_at, updated_at)
        SELECT id, rotation_type_id, name, category, description,
               COALESCE(target_count, 1), created_at, updated_at
        FROM activity_definitions
    """)
    op.drop_table('activity_definitions')
    op.rename_table('activity_definitions_old', 'activity_definitions')

    op.drop_table('activity_reviews')
