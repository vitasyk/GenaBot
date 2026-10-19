"""generator management: is_active flag and start instructions

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-18

Only 'GEN-2 (003) WILSON' stays active; disabled generators keep their history.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_GENERATOR = "GEN-2 (003) WILSON"

INSTRUCTIONS = {
    "GEN-1 (036)": (
        "1. Перевірте паливо (бак зліва)\n"
        "2. Переключіть тумблер \"CHOKE\" у положення ON\n"
        "3. Потягніть стартер 3-5 разів різко\n"
        "4. Після запуску переведіть CHOKE у OFF\n"
        "5. Прогрійте 2-3 хвилини"
    ),
    "GEN-2 (003) WILSON": (
        "1. Переконайтесь що вимикач НЕ на ON\n"
        "2. Натисніть кнопку PRIME 5 разів\n"
        "3. Переключіть вимикач на ON\n"
        "4. Натисніть кнопку START (тримайте 3-5 сек)\n"
        "5. Дочекайтесь стабільних обертів"
    ),
}


def upgrade() -> None:
    op.add_column(
        "generators",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("generators", sa.Column("instructions", sa.String(), nullable=True))

    for name, text in INSTRUCTIONS.items():
        op.execute(
            sa.text("UPDATE generators SET instructions = :text WHERE name = :name")
            .bindparams(text=text, name=name)
        )
    op.execute(
        sa.text("UPDATE generators SET is_active = false WHERE name <> :name")
        .bindparams(name=ACTIVE_GENERATOR)
    )


def downgrade() -> None:
    op.drop_column("generators", "instructions")
    op.drop_column("generators", "is_active")
