from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.config import config
from bot.handlers.admin.panel import toggle_access_callback, toggle_notify_callback
from bot.handlers.admin.slack import slack_threshold_input
from bot.scheduler import restore_runtime_settings


@pytest.fixture(autouse=True)
def _restore_config(monkeypatch):
    # every test may change the global config; monkeypatch puts the originals back
    monkeypatch.setattr(config, "RESTRICT_ACCESS", True)
    monkeypatch.setattr(config, "NOTIFY_WORKERS", False)
    monkeypatch.setattr(config, "FUEL_THRESHOLD_CANS", 2.0)


def _state(redis) -> MagicMock:
    state = MagicMock()
    state.storage.redis = redis
    state.clear = AsyncMock()
    return state


def _callback() -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    return cb


async def test_toggles_are_saved_and_restored(fake_redis):
    await toggle_access_callback(_callback(), state=_state(fake_redis))
    await toggle_notify_callback(_callback(), state=_state(fake_redis))
    assert (config.RESTRICT_ACCESS, config.NOTIFY_WORKERS) == (False, True)

    # simulate a restart: config back to .env defaults, then restore from Redis
    config.RESTRICT_ACCESS, config.NOTIFY_WORKERS = True, False
    await restore_runtime_settings(fake_redis)

    assert (config.RESTRICT_ACCESS, config.NOTIFY_WORKERS) == (False, True)


async def test_threshold_is_saved_and_restored(fake_redis):
    message = MagicMock()
    message.text = "3,5"
    message.answer = AsyncMock()

    await slack_threshold_input(message, _state(fake_redis))

    config.FUEL_THRESHOLD_CANS = 2.0
    await restore_runtime_settings(fake_redis)
    assert config.FUEL_THRESHOLD_CANS == 3.5
    assert ".env" not in message.answer.await_args.args[0]


async def test_restore_without_saved_values_keeps_env_defaults(fake_redis):
    await restore_runtime_settings(fake_redis)

    assert (config.RESTRICT_ACCESS, config.NOTIFY_WORKERS, config.FUEL_THRESHOLD_CANS) == (True, False, 2.0)


async def test_restore_ignores_corrupt_value(fake_redis):
    fake_redis.data["config:fuel_threshold_cans"] = b"not-a-number"

    await restore_runtime_settings(fake_redis)

    assert config.FUEL_THRESHOLD_CANS == 2.0
