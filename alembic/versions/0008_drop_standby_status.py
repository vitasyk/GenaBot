"""generators: standby mode removed, move standby generators to stopped

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-26

The 'standby' value stays in the genstatus enum (dropping it needs a type rebuild); it is just unused.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE generators SET status = 'stopped', current_run_start = NULL WHERE status = 'standby'")


def downgrade() -> None:
    # Data-only: which generators were on standby is not recorded, nothing to restore
    pass
