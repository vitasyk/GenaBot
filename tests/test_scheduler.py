from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


# --- jobs reuse the shared Redis client ------------------------------------

def test_start_scheduler_passes_shared_redis_to_jobs(monkeypatch):
    import bot.scheduler as sched

    fake = MagicMock()
    monkeypatch.setattr(sched, "scheduler", fake)
    bot, redis = object(), object()

    sched.start_scheduler(bot, redis)

    jobs = {c.args[0].__name__: c.kwargs for c in fake.add_job.call_args_list}
    for name in ("check_maintenance_needed", "warming_check_job", "antigel_reminder_job",
                 "check_power_outage_job"):
        assert jobs[name]["args"] == [bot, redis]
    assert jobs["check_power_outage_job"]["id"] == "check_power_outage_job"
    fake.start.assert_called_once()


async def test_outage_job_uses_given_redis_without_new_connection(monkeypatch, fake_redis):
    import bot.scheduler as sched
    import bot.services.session_service as session_service

    monkeypatch.setattr(sched.Redis, "from_url", MagicMock(side_effect=AssertionError("new connection")))
    session_cm = MagicMock(__aenter__=AsyncMock(return_value="session"), __aexit__=AsyncMock(return_value=None))
    monkeypatch.setattr(sched, "session_maker", MagicMock(return_value=session_cm))
    service_cls = MagicMock(return_value=MagicMock(check_power_outage=AsyncMock()))
    monkeypatch.setattr(session_service, "SessionService", service_cls)

    await sched.check_power_outage_job("bot", fake_redis)

    assert service_cls.call_args.kwargs["redis"] is fake_redis
    service_cls.return_value.check_power_outage.assert_awaited_once()
