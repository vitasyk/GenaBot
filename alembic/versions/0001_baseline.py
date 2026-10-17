"""Baseline: schema as it was built by init.sql + the fix_*/add_* scripts.

Existing database: do NOT run this, mark it as applied with `alembic stamp 0001`.
New database: `alembic upgrade head`.

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

userrole = postgresql.ENUM("admin", "worker", "blocked", name="userrole")
genstatus = postgresql.ENUM("stopped", "running", "standby", name="genstatus")


def upgrade() -> None:
    userrole.create(op.get_bind(), checkfirst=True)
    genstatus.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sheet_name", sa.String(), nullable=True),
        sa.Column("role", postgresql.ENUM(name="userrole", create_type=False), server_default="worker"),
    )
    op.create_table(
        "inventory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fuel_cans", sa.Integer(), server_default="0"),
    )
    op.create_table(
        "generators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("status", postgresql.ENUM(name="genstatus", create_type=False), server_default="stopped"),
        sa.Column("current_run_start", sa.DateTime(), nullable=True),
        sa.Column("fuel_level", sa.Float(), server_default="0"),
        sa.Column("tank_capacity", sa.Float(), server_default="40"),
        sa.Column("consumption_rate", sa.Float(), server_default="2"),
        sa.Column("total_hours_run", sa.Float(), server_default="0"),
        sa.Column("last_maintenance", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("details", sa.String(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_table(
        "refuel_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("deadline", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending"),
        sa.Column("worker1_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("worker2_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("gen_name", sa.String(), nullable=True),
        sa.Column("liters", sa.Float(), nullable=True),
        sa.Column("cans", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("completed_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    )

    op.execute("INSERT INTO inventory (fuel_cans) VALUES (0)")
    op.execute("INSERT INTO generators (name, status) VALUES ('GEN-1 (003)', 'stopped'), ('GEN-2 (038)', 'stopped')")


def downgrade() -> None:
    for table in ("refuel_sessions", "logs", "generators", "inventory", "users"):
        op.drop_table(table)
    genstatus.drop(op.get_bind(), checkfirst=True)
    userrole.drop(op.get_bind(), checkfirst=True)
