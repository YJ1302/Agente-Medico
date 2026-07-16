"""part2e documents, incidents, attachments, templates and numbering

Revision ID: b2e4d9c17a05
Revises: ca5acdae8455
Create Date: 2026-07-15 10:00:00.000000

NOTE ON SQLITE STRATEGY (see docs/DECISIONS_LOG.md D-022):
All new columns are nullable (or created on brand-new tables), so plain
``ADD COLUMN`` is used instead of batch mode. Batch mode would recreate the
``document_records`` / ``incidents`` tables and crash on their pre-existing
unnamed foreign keys. User/assignment references are added as plain nullable
integer columns without a DB-level FK constraint (the ORM still declares the
ForeignKey for relationships), matching Batch 2B/2D.

Existing rows are preserved: the pre-2E ``document_records`` and ``incidents``
rows simply gain NULL values in the new columns.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2e4d9c17a05'
down_revision: str | None = 'ca5acdae8455'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DOCUMENT_COLUMNS = [
    ('seq_year', sa.Integer()),
    ('seq_number', sa.Integer()),
    ('priority', sa.String(length=20)),
    ('visibility', sa.String(length=20)),
    ('assignment_id', sa.Integer()),
    ('subject', sa.String(length=300)),
    ('body', sa.Text()),
    ('internal_notes', sa.Text()),
    ('created_by_user_id', sa.Integer()),
    ('submitted_by_user_id', sa.Integer()),
    ('submitted_at', sa.DateTime(timezone=True)),
    ('reviewed_by_user_id', sa.Integer()),
    ('reviewed_at', sa.DateTime(timezone=True)),
    ('approved_by_user_id', sa.Integer()),
    ('approved_at', sa.DateTime(timezone=True)),
    ('rejected_by_user_id', sa.Integer()),
    ('rejected_at', sa.DateTime(timezone=True)),
    ('rejection_reason', sa.Text()),
    ('archived_by_user_id', sa.Integer()),
    ('archived_at', sa.DateTime(timezone=True)),
    ('reopened_by_user_id', sa.Integer()),
    ('reopened_at', sa.DateTime(timezone=True)),
    ('reopen_reason', sa.Text()),
    ('due_date', sa.Date()),
]

# ``destination``/``origin`` are widened conceptually but SQLite ignores VARCHAR
# length, so no ALTER is needed for those existing columns.

_INCIDENT_COLUMNS = [
    ('seq_year', sa.Integer()),
    ('seq_number', sa.Integer()),
    ('incident_type', sa.String(length=60)),
    ('visibility', sa.String(length=20)),
    ('assignment_id', sa.Integer()),
    ('reported_by_user_id', sa.Integer()),
    ('report_date', sa.Date()),
    ('responsible_user_id', sa.Integer()),
    ('due_date', sa.Date()),
    ('internal_notes', sa.Text()),
    ('resolution', sa.Text()),
    ('resolved_by_user_id', sa.Integer()),
    ('resolved_at', sa.DateTime(timezone=True)),
    ('closed_by_user_id', sa.Integer()),
    ('closed_at', sa.DateTime(timezone=True)),
    ('dismissed_by_user_id', sa.Integer()),
    ('dismissed_at', sa.DateTime(timezone=True)),
    ('dismiss_reason', sa.Text()),
    ('reopened_by_user_id', sa.Integer()),
    ('reopened_at', sa.DateTime(timezone=True)),
    ('reopen_reason', sa.Text()),
]


def upgrade() -> None:
    for name, coltype in _DOCUMENT_COLUMNS:
        op.add_column('document_records', sa.Column(name, coltype, nullable=True))
    for name, coltype in _INCIDENT_COLUMNS:
        op.add_column('incidents', sa.Column(name, coltype, nullable=True))

    op.create_table(
        'attachments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('owner_type', sa.String(length=20), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('stored_filename', sa.String(length=255), nullable=False, unique=True),
        sa.Column('mime_type', sa.String(length=120), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_user_id', sa.Integer(), nullable=True),
        sa.Column('deleted_by_user_id', sa.Integer(), nullable=True),
    )
    op.create_index('ix_attachments_owner', 'attachments', ['owner_type', 'owner_id'])

    op.create_table(
        'status_history',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('owner_type', sa.String(length=20), nullable=False),
        sa.Column('owner_id', sa.Integer(), nullable=False),
        sa.Column('from_status', sa.String(length=30), nullable=True),
        sa.Column('to_status', sa.String(length=30), nullable=False),
        sa.Column('action', sa.String(length=60), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('actor_label', sa.String(length=160), nullable=False, server_default='system'),
        sa.Column('note', sa.Text(), nullable=True),
    )
    op.create_index('ix_status_history_owner', 'status_history', ['owner_type', 'owner_id'])

    op.create_table(
        'document_templates',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('code', sa.String(length=60), nullable=False, unique=True),
        sa.Column('name', sa.String(length=160), nullable=False),
        sa.Column('doc_type', sa.String(length=60), nullable=False),
        sa.Column('subject_template', sa.String(length=300), nullable=True),
        sa.Column('body_template', sa.Text(), nullable=False),
        sa.Column('description', sa.String(length=300), nullable=True),
    )

    op.create_table(
        'document_sequences',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('last_value', sa.Integer(), nullable=False, server_default='0'),
        sa.UniqueConstraint('kind', 'year', name='uq_sequence_kind_year'),
    )


def downgrade() -> None:
    op.drop_table('document_sequences')
    op.drop_table('document_templates')
    op.drop_index('ix_status_history_owner', table_name='status_history')
    op.drop_table('status_history')
    op.drop_index('ix_attachments_owner', table_name='attachments')
    op.drop_table('attachments')
    for name, _ in reversed(_INCIDENT_COLUMNS):
        op.drop_column('incidents', name)
    for name, _ in reversed(_DOCUMENT_COLUMNS):
        op.drop_column('document_records', name)
