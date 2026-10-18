"""baseline: the production schema as of 2026-10

Revision ID: 0001
Revises:
Create Date: 2026-10-18

Production already has these tables: run `alembic stamp --purge 0001` there once.
A fresh database runs `alembic upgrade head`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.execute("CREATE TYPE userrole AS ENUM ('admin', 'worker', 'blocked')")
    op.execute("CREATE TYPE genstatus AS ENUM ('stopped', 'running', 'standby')")

    op.execute("""
        CREATE TABLE users (
            id BIGINT NOT NULL,
            name VARCHAR NOT NULL,
            role userrole NOT NULL DEFAULT 'worker',
            sheet_name VARCHAR,
            CONSTRAINT users_pkey PRIMARY KEY (id)
        )
    """)
    op.execute("""
        CREATE TABLE inventory (
            id SERIAL NOT NULL,
            fuel_cans INTEGER NOT NULL DEFAULT 0,
            CONSTRAINT inventory_pkey PRIMARY KEY (id)
        )
    """)
    op.execute("""
        CREATE TABLE generators (
            id SERIAL NOT NULL,
            name VARCHAR NOT NULL,
            status genstatus NOT NULL DEFAULT 'stopped',
            current_run_start TIMESTAMP WITHOUT TIME ZONE,
            fuel_level DOUBLE PRECISION NOT NULL DEFAULT 0,
            consumption_rate DOUBLE PRECISION NOT NULL DEFAULT 2,
            tank_capacity DOUBLE PRECISION NOT NULL DEFAULT 40.0,
            total_hours_run DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            last_maintenance TIMESTAMP WITHOUT TIME ZONE,
            fuel_since_antigel DOUBLE PRECISION NOT NULL DEFAULT '0'::double precision,
            last_stop_at TIMESTAMP WITHOUT TIME ZONE,
            CONSTRAINT generators_pkey PRIMARY KEY (id),
            CONSTRAINT generators_name_key UNIQUE (name)
        )
    """)
    op.execute("""
        CREATE TABLE logs (
            id SERIAL NOT NULL,
            user_id BIGINT NOT NULL,
            action VARCHAR NOT NULL,
            details VARCHAR,
            timestamp TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT logs_pkey PRIMARY KEY (id),
            CONSTRAINT logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    op.execute("""
        CREATE TABLE refuel_sessions (
            id SERIAL NOT NULL,
            start_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            end_time TIMESTAMP WITHOUT TIME ZONE,
            deadline TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'pending',
            worker1_id BIGINT,
            worker2_id BIGINT,
            gen_name VARCHAR,
            liters DOUBLE PRECISION,
            cans DOUBLE PRECISION,
            notes VARCHAR,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_by BIGINT,
            worker3_id BIGINT,
            additional_workers JSON,
            CONSTRAINT refuel_sessions_pkey PRIMARY KEY (id),
            CONSTRAINT refuel_sessions_worker1_id_fkey FOREIGN KEY (worker1_id) REFERENCES users (id),
            CONSTRAINT refuel_sessions_worker2_id_fkey FOREIGN KEY (worker2_id) REFERENCES users (id),
            CONSTRAINT refuel_sessions_worker3_id_fkey FOREIGN KEY (worker3_id) REFERENCES users (id),
            CONSTRAINT refuel_sessions_completed_by_fkey FOREIGN KEY (completed_by) REFERENCES users (id)
        )
    """)
    op.execute("""
        CREATE TABLE schedule_entries (
            id SERIAL NOT NULL,
            date DATE NOT NULL,
            queue VARCHAR NOT NULL,
            start_hour INTEGER NOT NULL,
            end_hour INTEGER NOT NULL,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            created_by BIGINT,
            CONSTRAINT schedule_entries_pkey PRIMARY KEY (id),
            CONSTRAINT schedule_entries_created_by_fkey FOREIGN KEY (created_by) REFERENCES users (id)
        )
    """)
    op.execute("""
        CREATE TABLE shifts (
            id SERIAL NOT NULL,
            worker_id BIGINT NOT NULL,
            shift_date DATE NOT NULL,
            start_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            end_time TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            CONSTRAINT shifts_pkey PRIMARY KEY (id),
            CONSTRAINT shifts_worker_id_fkey FOREIGN KEY (worker_id) REFERENCES users (id)
        )
    """)
    op.execute("""
        CREATE TABLE worker_shifts (
            id SERIAL NOT NULL,
            date DATE NOT NULL,
            shift_number INTEGER NOT NULL,
            worker1_id BIGINT NOT NULL,
            worker2_id BIGINT NOT NULL,
            start_time VARCHAR NOT NULL,
            end_time VARCHAR NOT NULL,
            fetched_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            worker3_id BIGINT,
            CONSTRAINT worker_shifts_pkey PRIMARY KEY (id),
            CONSTRAINT worker_shifts_worker1_id_fkey FOREIGN KEY (worker1_id) REFERENCES users (id),
            CONSTRAINT worker_shifts_worker2_id_fkey FOREIGN KEY (worker2_id) REFERENCES users (id),
            CONSTRAINT worker_shifts_worker3_id_fkey FOREIGN KEY (worker3_id) REFERENCES users (id)
        )
    """)

    # Seed rows the bot expects on a fresh database
    op.execute("INSERT INTO inventory (fuel_cans) VALUES (0)")
    op.execute(sa.text("INSERT INTO generators (name) VALUES (:g1), (:g2)").bindparams(
        g1="GEN-1 (036)", g2="GEN-2 (003) WILSON",
    ))


def downgrade() -> None:
    op.execute(
        "DROP TABLE logs, refuel_sessions, schedule_entries, shifts, worker_shifts, "
        "generators, inventory, users"
    )
    op.execute("DROP TYPE genstatus")
    op.execute("DROP TYPE userrole")
