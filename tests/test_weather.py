import logging
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from bot.database.models import GenStatus
from bot.services.weather import WeatherService
from bot.utils.clock import utcnow
from tests.test_generators import _gen, _service, _stop_repo


def test_unknown_temperature_uses_worst_case_factor():
    weather = WeatherService()
    assert weather.get_consumption_factor(None) == max(
        weather.get_consumption_factor(t) for t in (-30.0, -5.0, 10.0))


async def test_api_failure_returns_none_and_logs_without_key(caplog):
    weather = WeatherService()
    weather.api_key = "SECRET-KEY"
    error = aiohttp.ClientError("https://x/weather?appid=SECRET-KEY")
    with patch("bot.services.weather.aiohttp.ClientSession", side_effect=error), \
            caplog.at_level(logging.WARNING):
        assert await weather.get_current_temperature() is None
        assert await weather.get_weekly_forecast() == []

    assert caplog.records
    assert "SECRET-KEY" not in caplog.text


async def test_stop_with_unknown_temperature_accounts_worst_case_fuel():
    gen = _gen(5, "WILSON", GenStatus.running, current_run_start=utcnow() - timedelta(hours=2))
    service = _service(_stop_repo(gen))
    service.weather = WeatherService()
    service.weather.get_current_temperature = AsyncMock(return_value=None)
    service.redis = MagicMock(get=AsyncMock(return_value=b"0"))

    text = await service.stop_all(user_id=1)

    consumed = service.repo.add_fuel.await_args.args[1]
    assert consumed == pytest.approx(-4.8, abs=0.05)  # 2 h * 2 L/h * 1.2
    assert "н/д" in text


async def test_daily_report_with_unknown_current_temperature():
    weather = WeatherService()
    weather.get_current_temperature = AsyncMock(return_value=None)
    weather.get_weekly_forecast = AsyncMock(return_value=[{"temp_min": 2.0, "temp_max": 8.0}])

    report = await weather.get_daily_report()

    assert "Зараз: <b>н/д</b>" in report


async def test_warming_check_with_unknown_temperature_does_not_crash():
    gen = _gen(5, "WILSON", GenStatus.stopped, last_stop_at=utcnow() - timedelta(hours=20))
    service = _service(MagicMock(get_by_name=AsyncMock(return_value=gen)))
    service.weather.get_current_temperature = AsyncMock(return_value=None)

    assert await service.get_warming_recommendation("WILSON") is None
