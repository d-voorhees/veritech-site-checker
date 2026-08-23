"""split pagespeed performance metrics into desktop/mobile

Revision ID: a00440335fda
Revises: 41e1232a517d
Create Date: 2026-08-12 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a00440335fda'
down_revision: Union[str, None] = '41e1232a517d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_COLUMNS = ["lcp_ms", "cls", "inp_ms", "fcp_ms", "ttfb_ms",
               "performance_score", "accessibility_score", "best_practices_score", "seo_score"]

NEW_METRIC_COLUMNS = ["lcp_ms", "cls", "inp_ms", "fcp_ms", "ttfb_ms"]
NEW_SCORE_COLUMNS = ["performance_score", "accessibility_score", "best_practices_score", "seo_score"]


def upgrade() -> None:
    for strategy in ("desktop", "mobile"):
        for col in NEW_METRIC_COLUMNS:
            op.add_column(
                'performance_observations',
                sa.Column(f'{strategy}_{col}', sa.Float(), nullable=True),
            )
        for col in NEW_SCORE_COLUMNS:
            op.add_column(
                'performance_observations',
                sa.Column(f'{strategy}_{col}', sa.Integer(), nullable=True),
            )

    # Existing rows only ever populated the old mobile-strategy PageSpeed call.
    for col in NEW_METRIC_COLUMNS + NEW_SCORE_COLUMNS:
        op.execute(
            f"UPDATE performance_observations SET mobile_{col} = {col}"
        )

    for col in OLD_COLUMNS:
        op.drop_column('performance_observations', col)


def downgrade() -> None:
    for col in OLD_COLUMNS:
        col_type = sa.Float() if col in NEW_METRIC_COLUMNS else sa.Integer()
        op.add_column('performance_observations', sa.Column(col, col_type, nullable=True))

    for col in OLD_COLUMNS:
        op.execute(
            f"UPDATE performance_observations SET {col} = mobile_{col}"
        )

    for strategy in ("desktop", "mobile"):
        for col in NEW_METRIC_COLUMNS + NEW_SCORE_COLUMNS:
            op.drop_column('performance_observations', f'{strategy}_{col}')
