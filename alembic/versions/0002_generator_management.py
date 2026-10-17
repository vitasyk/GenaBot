"""Generators managed from the admin panel: is_active + SOS instructions; WILSON is the only active one.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# SOS texts that were hardcoded in handlers/common.py
GEN_1_INSTRUCTIONS = (
    "Синій корпус\n\n"
    "1. Перевірте паливо (бак зліва)\n"
    "2. Переключіть тумблер \"CHOKE\" у положення ON\n"
    "3. Потягніть стартер 3-5 разів різко\n"
    "4. Після запуску переведіть CHOKE у OFF\n"
    "5. Прогрійте 2-3 хвилини"
)
GEN_2_INSTRUCTIONS = (
    "Червоний корпус\n\n"
    "1. Переконайтесь що вимикач НЕ на ON\n"
    "2. Натисніть кнопку PRIME 5 разів\n"
    "3. Переключіть вимикач на ON\n"
    "4. Натисніть кнопку START (тримайте 3-5 сек)\n"
    "5. Дочекайтесь стабільних обертів"
)
ACTIVE_GENERATOR = "WILSON"


def upgrade() -> None:
    op.add_column("generators", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("generators", sa.Column("instructions", sa.String(), nullable=True))

    update_sos = sa.text("UPDATE generators SET instructions = :text WHERE name = :name")
    op.execute(update_sos.bindparams(text=GEN_1_INSTRUCTIONS, name="GEN-1 (003)"))
    op.execute(update_sos.bindparams(text=GEN_2_INSTRUCTIONS, name="GEN-2 (038)"))

    op.execute(
        sa.text(
            "INSERT INTO generators (name, status, fuel_level, tank_capacity, consumption_rate, total_hours_run, is_active) "
            "VALUES (:name, 'stopped', 0, 40, 2, 0, true) ON CONFLICT (name) DO NOTHING"
        ).bindparams(name=ACTIVE_GENERATOR)
    )
    # Disabled generators must not stay running or on standby
    op.execute(
        sa.text(
            "UPDATE generators SET is_active = false, status = 'stopped', current_run_start = NULL WHERE name <> :name"
        ).bindparams(name=ACTIVE_GENERATOR)
    )


def downgrade() -> None:
    op.drop_column("generators", "instructions")
    op.drop_column("generators", "is_active")
