from unittest.mock import AsyncMock, MagicMock

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
    from bot.services import session_service

    monkeypatch.setattr(sched.Redis, "from_url", MagicMock(side_effect=AssertionError("new connection")))
    session_cm = MagicMock(__aenter__=AsyncMock(return_value="session"), __aexit__=AsyncMock(return_value=None))
    monkeypatch.setattr(sched, "session_maker", MagicMock(return_value=session_cm))
    service_cls = MagicMock(return_value=MagicMock(check_power_outage=AsyncMock()))
    monkeypatch.setattr(session_service, "SessionService", service_cls)

    await sched.check_power_outage_job("bot", fake_redis)

    assert service_cls.call_args.kwargs["redis"] is fake_redis
    service_cls.return_value.check_power_outage.assert_awaited_once()
