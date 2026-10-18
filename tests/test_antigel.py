from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.database.models import Generator, GenStatus
from bot.services.antigel import AntigelService, advise, format_advice
from bot.services.generator import GeneratorService

JULY, JANUARY = date(2026, 7, 1), date(2026, 1, 15)


def test_needed_only_when_cold_forecast_and_enough_untreated_fuel():
    # summer diesel (CFPP -5) + 5 °C margin: the additive must go in from a 0 °C forecast
    assert advise(90, 120, forecast_min=-1, current_temp=3, today=JULY).needed
    assert not advise(90, 120, forecast_min=4, current_temp=8, today=JANUARY).needed  # warm forecast wins
    assert not advise(10, 120, forecast_min=-15, current_temp=-3, today=JANUARY).needed  # 8% untreated


def test_dose_is_ml_per_untreated_litre_capped_by_tank_level():
    advice = advise(90.2, 120, forecast_min=-1, current_temp=3, today=JULY)
    assert advice.dose_ml == 91
    assert advise(200, 120, forecast_min=-1, current_temp=3, today=JULY).untreated_l == 120


def test_month_fallback_when_forecast_unavailable():
    assert advise(90, 120, forecast_min=None, current_temp=None, today=JANUARY).needed
    assert not advise(90, 120, forecast_min=None, current_temp=None, today=JULY).needed


def test_too_cold_now_warns_to_warm_up_first():
    advice = advise(90, 120, forecast_min=-12, current_temp=-8, today=JANUARY)
    assert advice.too_cold_now
    text = format_advice("WILSON <1>", advice, extra_hint=True)
    assert "WILSON &lt;1&gt;" in text and "≈90 мл" in text and "кожен літр" in text and "прогрійте" in text


async def test_forecast_min_of_next_three_days_is_cached(fake_redis):
    weather = MagicMock(get_weekly_forecast=AsyncMock(return_value=[
        {"temp_min": 2.0}, {"temp_min": -3.5}, {"temp_min": 1.0}, {"temp_min": -20.0},
    ]))
    service = AntigelService(weather, fake_redis)
    assert await service.get_forecast_min() == -3.5  # day 4 is ignored
    assert await service.get_forecast_min() == -3.5
    weather.get_weekly_forecast.assert_awaited_once()


async def test_running_burns_untreated_fuel_in_proportion():
    # 100 L in the tank, 40 L of it untreated; burning 50 L leaves 20 L untreated (share stays 40%)
    gen = Generator(id=1, name="WILSON", status=GenStatus.running, fuel_level=100.0, consumption_rate=10.0,
                    total_hours_run=0.0, fuel_since_antigel=40.0,
                    current_run_start=datetime.utcnow() - timedelta(hours=5))
    repo = MagicMock(add_fuel=AsyncMock(return_value=50.0), update_total_hours=AsyncMock(), set_status=AsyncMock())
    service = GeneratorService(repo, MagicMock(log_action=AsyncMock()), MagicMock(), MagicMock())
    service.weather = MagicMock(get_current_temperature=AsyncMock(return_value=5.0),
                                get_consumption_factor=MagicMock(return_value=1.0))

    await service._stop_and_calculate(gen, user_id=1)
    assert gen.fuel_since_antigel == pytest.approx(20.0)
