from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.scheduler import notify_maintenance_due


def _gen(hours: float, gen_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=gen_id, name=f"GEN-{gen_id}", total_hours_run=hours)


async def test_first_run_stores_mark_without_alert(fake_redis):
    notifier = AsyncMock()

    await notify_maintenance_due([_gen(153.0)], fake_redis, notifier)

    notifier.notify_all.assert_not_awaited()
    assert fake_redis.data["maintenance:last_mark:1"] == b"1"


async def test_alerts_once_when_100h_mark_crossed(fake_redis):
    notifier = AsyncMock()
    await notify_maintenance_due([_gen(95.0)], fake_redis, notifier)

    # hours jump past the mark in one chunk (added at stop)
    await notify_maintenance_due([_gen(104.3)], fake_redis, notifier)
    await notify_maintenance_due([_gen(110.0)], fake_redis, notifier)

    notifier.notify_all.assert_awaited_once()
    assert "GEN-1" in notifier.notify_all.await_args.args[0]


async def test_marks_are_per_generator(fake_redis):
    notifier = AsyncMock()
    await notify_maintenance_due([_gen(99.0, 1), _gen(50.0, 2)], fake_redis, notifier)

    await notify_maintenance_due([_gen(99.5, 1), _gen(201.0, 2)], fake_redis, notifier)

    notifier.notify_all.assert_awaited_once()
    assert "GEN-2" in notifier.notify_all.await_args.args[0]
