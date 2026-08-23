"""magic-link auth and brevo scan summary

Revision ID: b8a2f5d13c90
Revises: c3e9a1f7b214
Create Date: 2026-08-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8a2f5d13c90'
down_revision: Union[str, None] = 'c3e9a1f7b214'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('users', 'hashed_password', existing_type=sa.String(length=255), nullable=True)
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('scans_used', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('mailerlite_synced_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('users', 'scans_used', server_default=None)

    op.create_table(
        'magic_link_tokens',
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('requested_ip', sa.String(length=64), nullable=True),
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_magic_link_tokens_token_hash'), 'magic_link_tokens', ['token_hash'], unique=True)

    op.add_column('reports', sa.Column('brevo_summary_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('reports', 'brevo_summary_json')

    op.drop_index(op.f('ix_magic_link_tokens_token_hash'), table_name='magic_link_tokens')
    op.drop_table('magic_link_tokens')

    op.drop_column('users', 'mailerlite_synced_at')
    op.drop_column('users', 'scans_used')
    op.drop_column('users', 'email_verified_at')
    op.alter_column('users', 'hashed_password', existing_type=sa.String(length=255), nullable=False)
