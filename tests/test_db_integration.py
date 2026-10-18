"""Repository checks against a real Postgres migrated with `alembic upgrade head`.

Run (local compose stack up, see DEPLOY.md "Локальний тест"):
    INTEGRATION_DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/genabot pytest tests/test_db_integration.py
"""
import os
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from bot.database.models import SessionStatus
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.inventory import InventoryRepository
from bot.database.repositories.schedule import ScheduleRepository
from bot.database.repositories.session import OPEN_STATUSES, SessionRepository

DB_URL = os.environ.get("INTEGRATION_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="INTEGRATION_DATABASE_URL not set")


@pytest.fixture
async def db():
    engine = create_async_engine(DB_URL, connect_args={"statement_cache_size": 0})
    async with engine.connect() as conn:
        trans = await conn.begin()
        # Repositories commit; savepoints keep everything inside the outer transaction we roll back
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        yield session
        await session.close()
        await trans.rollback()
    await engine.dispose()


async def test_session_completes_once_and_old_start_button_does_not_reopen_it(db):
    repo = SessionRepository(db)
    now = datetime(2026, 10, 18, 16, 0)
    s = await repo.create_session(start_time=now, deadline=now + timedelta(hours=2))

    first = await repo.complete_session(s.id, completed_by=None, gen_name="GEN-2 (003) WILSON: 20л",
                                        liters=20.0, cans=1.0)
    second = await repo.complete_session(s.id, completed_by=None, gen_name="x", liters=20.0, cans=1.0)
    reopened = await repo.update_status(s.id, SessionStatus.in_progress, only_from=OPEN_STATUSES)

    assert first is not None and first.status == SessionStatus.completed.value
    assert second is None
    assert reopened is None


async def test_expired_session_can_still_be_completed(db):
    repo = SessionRepository(db)
    now = datetime(2026, 10, 18, 16, 0)
    s = await repo.create_session(start_time=now, deadline=now)
    await repo.update_status(s.id, SessionStatus.expired)
    assert s.id not in [o.id for o in await repo.get_overdue_sessions(now + timedelta(hours=1))]
    assert await repo.complete_session(s.id, completed_by=None, gen_name="x", liters=5.0, cans=0.25) is not None


async def test_every_overdue_session_is_found_not_only_the_latest(db):
    # Regression: only the newest open session was checked, an older overdue one stayed pending forever
    repo = SessionRepository(db)
    base = datetime(2026, 10, 18, 16, 0)
    older = await repo.create_session(start_time=base, deadline=base + timedelta(hours=2))
    await repo.create_session(start_time=base + timedelta(hours=1), deadline=base + timedelta(hours=3))

    overdue = await repo.get_overdue_sessions(base + timedelta(hours=2, minutes=1))
    assert [s.id for s in overdue] == [older.id]


async def test_stock_accepts_fractional_liters_from_session_completion(db):
    # finish_session passes the sum of typed liters (floats like 20.5) to take_fuel
    repo = InventoryRepository(db)
    start = await repo.get_stock()
    await repo.update_stock(100)
    left = await repo.update_stock(-20.5)
    await db.flush()
    assert left == pytest.approx(start + 79.5, abs=0.5)


async def test_only_active_generators_are_listed(db):
    gens = await GeneratorRepository(db).get_all(active_only=True)
    assert [g.name for g in gens] == ["GEN-2 (003) WILSON"]


async def test_schedule_entries_are_per_queue(db):
    repo = ScheduleRepository(db)
    day = date(2026, 10, 18)
    await repo.create_entry(day, "1.1", 14, 18)
    await repo.create_entry(day, "2.1", 8, 10)
    assert [(e.start_hour, e.end_hour) for e in await repo.get_entries_for_date(day, "1.1")] == [(14, 18)]
