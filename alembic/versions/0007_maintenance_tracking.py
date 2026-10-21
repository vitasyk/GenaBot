"""generators: maintenance tracking (hours at last service, admin-set interval)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21

Service is due after maint_interval_hours run hours or maint_interval_months months since
last_maintenance (existing, unused until now), whichever comes first.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("generators", sa.Column("maint_hours_at", sa.Float(), nullable=True))
    op.add_column("generators", sa.Column("maint_interval_hours", sa.Float(), nullable=False, server_default="200"))
    op.add_column("generators", sa.Column("maint_interval_months", sa.Integer(), nullable=False, server_default="12"))


def downgrade() -> None:
    op.drop_column("generators", "maint_interval_months")
    op.drop_column("generators", "maint_interval_hours")
    op.drop_column("generators", "maint_hours_at")
