"""enable row level security on all public tables

Revision ID: e4a1c9d27f6b
Revises: b8a2f5d13c90
Create Date: 2026-09-08 09:00:00.000000

Supabase flagged every table in the public schema as publicly readable
over its auto-generated PostgREST API because RLS was never enabled.
This app never uses that API or the anon/authenticated Supabase roles —
it talks to Postgres directly over the Session pooler as the `postgres`
role, which has BYPASSRLS — so enabling RLS with no policies closes the
PostgREST API without touching how the backend connects.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e4a1c9d27f6b'
down_revision: Union[str, None] = 'b8a2f5d13c90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = [
    'organizations',
    'users',
    'magic_link_tokens',
    'scan_requests',
    'scan_targets',
    'scan_jobs',
    'scan_events',
    'pages',
    'http_observations',
    'dns_observations',
    'technology_observations',
    'performance_observations',
    'third_party_dependencies',
    'evidence_items',
    'finding_rules',
    'findings',
    'finding_evidence',
    'reports',
]


def upgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')


def downgrade() -> None:
    for table in TABLES:
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
