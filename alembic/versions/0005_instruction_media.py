"""generators.instructions_media: photos/PDFs attached to the SOS instructions

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-18

Only Telegram file_ids are stored; the files themselves stay on Telegram's side.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("generators", sa.Column("instructions_media", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("generators", "instructions_media")
