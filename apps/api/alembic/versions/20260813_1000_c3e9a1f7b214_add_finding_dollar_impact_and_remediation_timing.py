"""add dollar_impact and remediation_timing to findings

Revision ID: c3e9a1f7b214
Revises: 20fcb897e807
Create Date: 2026-08-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e9a1f7b214'
down_revision: Union[str, None] = '20fcb897e807'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('findings', sa.Column('dollar_impact', sa.String(length=8), nullable=True))
    op.add_column('findings', sa.Column('remediation_timing', sa.String(length=16), nullable=True))
    # Existing findings rows predate these fields and won't get a per-rule
    # accurate value retroactively — backfill a conservative placeholder so
    # the column can be made NOT NULL; the next re-run of each scan replaces
    # these with the real rule-assigned values (run_rules_engine deletes and
    # recreates every finding for a scan on each run).
    op.execute("UPDATE findings SET dollar_impact = '$$', remediation_timing = '60-day' WHERE dollar_impact IS NULL")
    op.alter_column('findings', 'dollar_impact', nullable=False)
    op.alter_column('findings', 'remediation_timing', nullable=False)


def downgrade() -> None:
    op.drop_column('findings', 'remediation_timing')
    op.drop_column('findings', 'dollar_impact')
