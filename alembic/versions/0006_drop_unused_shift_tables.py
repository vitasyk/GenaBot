"""drop unused shifts and worker_shifts tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19

No code reads or writes them (duty workers come from Google Sheets); both were empty in prod.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("worker_shifts")
    op.drop_table("shifts")


def downgrade() -> None:
    # Same DDL as 0001_baseline, plus the RLS that 0002 enabled
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
    op.execute("ALTER TABLE shifts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE worker_shifts ENABLE ROW LEVEL SECURITY")
