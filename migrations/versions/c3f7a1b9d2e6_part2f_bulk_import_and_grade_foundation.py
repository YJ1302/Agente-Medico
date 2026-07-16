"""part2f bulk import framework and academic grade foundation

Revision ID: c3f7a1b9d2e6
Revises: b2e4d9c17a05
Create Date: 2026-07-15 16:00:00.000000

All six tables are brand new, so plain ``create_table`` is used (no batch mode,
no ALTER of existing tables). Existing data is untouched. User/rotation/period
references are declared in the ORM; at the DB level they are plain nullable
integer columns (matching the SQLite strategy of earlier batches, D-022).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'c3f7a1b9d2e6'
down_revision: str | None = 'b2e4d9c17a05'
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


def _ts():
    return [
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        'import_batches',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        *_ts_soft(),
        sa.Column('code', sa.String(length=40), nullable=False, unique=True),
        sa.Column('profile', sa.String(length=40), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_filename', sa.String(length=255), nullable=True),
        sa.Column('sheet_name', sa.String(length=120), nullable=True),
        sa.Column('mode', sa.String(length=30), nullable=False, server_default='create_only'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='uploaded'),
        sa.Column('mapping_json', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=True),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('valid_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('warning_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('skipped_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sede_scope_id', sa.Integer(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('confirmed_by_user_id', sa.Integer(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
    )

    op.create_table(
        'import_rows',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        *_ts(),
        sa.Column('batch_id', sa.Integer(), sa.ForeignKey('import_batches.id'), nullable=False),
        sa.Column('row_number', sa.Integer(), nullable=False),
        sa.Column('source_sheet', sa.String(length=120), nullable=True),
        sa.Column('raw_json', sa.Text(), nullable=True),
        sa.Column('normalized_json', sa.Text(), nullable=True),
        sa.Column('messages_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('action', sa.String(length=20), nullable=True),
        sa.Column('target_entity_type', sa.String(length=60), nullable=True),
        sa.Column('target_entity_id', sa.Integer(), nullable=True),
    )
    op.create_index('ix_import_rows_batch', 'import_rows', ['batch_id'])

    op.create_table(
        'grade_schemes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        *_ts_soft(),
        sa.Column('code', sa.String(length=60), nullable=False, unique=True),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('rotation_type_id', sa.Integer(), nullable=True),
        sa.Column('period_id', sa.Integer(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('effective_from', sa.Date(), nullable=True),
        sa.Column('effective_to', sa.Date(), nullable=True),
        sa.Column('weights_confirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('notes', sa.Text(), nullable=True),
    )

    op.create_table(
        'grade_component_definitions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        *_ts(),
        sa.Column('scheme_id', sa.Integer(), sa.ForeignKey('grade_schemes.id'), nullable=False),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('category', sa.String(length=40), nullable=False),
        sa.Column('weight_percent', sa.Float(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('max_score', sa.Float(), nullable=False, server_default='20'),
        sa.Column('source', sa.String(length=120), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
    )

    op.create_table(
        'student_grade_components',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        *_ts_soft(),
        sa.Column('student_id', sa.Integer(), sa.ForeignKey('students.id'), nullable=False),
        sa.Column('scheme_id', sa.Integer(), sa.ForeignKey('grade_schemes.id'), nullable=False),
        sa.Column('component_id', sa.Integer(),
                  sa.ForeignKey('grade_component_definitions.id'), nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('source_type', sa.String(length=20), nullable=False, server_default='manual'),
        sa.Column('source_batch_id', sa.Integer(), nullable=True),
        sa.Column('source_sheet', sa.String(length=120), nullable=True),
        sa.Column('source_row', sa.Integer(), nullable=True),
        sa.Column('source_col', sa.String(length=20), nullable=True),
        sa.Column('entered_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_user_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_sgc_student_scheme', 'student_grade_components',
                    ['student_id', 'scheme_id'])

    op.create_table(
        'grade_component_history',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        *_ts(),
        sa.Column('student_grade_component_id', sa.Integer(),
                  sa.ForeignKey('student_grade_components.id'), nullable=False),
        sa.Column('old_score', sa.Float(), nullable=True),
        sa.Column('new_score', sa.Float(), nullable=True),
        sa.Column('old_status', sa.String(length=20), nullable=True),
        sa.Column('new_status', sa.String(length=20), nullable=True),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('actor_label', sa.String(length=160), nullable=False, server_default='system'),
        sa.Column('batch_id', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('grade_component_history')
    op.drop_index('ix_sgc_student_scheme', table_name='student_grade_components')
    op.drop_table('student_grade_components')
    op.drop_table('grade_component_definitions')
    op.drop_table('grade_schemes')
    op.drop_index('ix_import_rows_batch', table_name='import_rows')
    op.drop_table('import_rows')
    op.drop_table('import_batches')
