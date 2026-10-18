"""enable row level security on every public table

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18

Supabase exposes the public schema through its REST API. RLS with no policies gives the
API roles nothing; the bot connects as the table owner (postgres) and bypasses RLS.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "alembic_version", "generators", "inventory", "logs", "refuel_sessions",
    "schedule_entries", "shifts", "users", "worker_shifts",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")  # constant names only


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")  # constant names only
