"""add dkim selector column to dns observations

Revision ID: 20fcb897e807
Revises: a00440335fda
Create Date: 2026-08-12 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20fcb897e807'
down_revision: Union[str, None] = 'a00440335fda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dns_observations', sa.Column('dkim_selector', sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column('dns_observations', 'dkim_selector')
