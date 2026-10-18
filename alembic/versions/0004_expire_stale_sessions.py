"""quietly expire open refuel sessions whose deadline has already passed

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-18

The old code never closed sessions after their deadline (13 such sessions in production,
from February and April). The new code reminds workers once per overdue session, so without
this step the first check after deployment would send a burst of stale reminders.
Expired sessions can still be completed from their buttons.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # deadline is stored as naive Kyiv time
    op.execute(
        "UPDATE refuel_sessions SET status = 'expired' "
        "WHERE status IN ('pending', 'in_progress') "
        "AND deadline < (now() AT TIME ZONE 'Europe/Kyiv')"
    )


def downgrade() -> None:
    # Data-only change: which sessions were open before is not recorded, nothing to undo
    pass
