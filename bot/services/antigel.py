"""When to add anti-gel (cold flow additive) to a generator tank.

The additive is dosed per litre of fuel and is burned in the same proportion as the fuel, so running
the generator does not dilute it. Only fuel poured in without additive does. Generator.fuel_since_antigel
holds those untreated litres still in the tank: it grows on refuel, shrinks in proportion as the
generator burns the mix, and is zeroed when someone confirms the additive was added.

The additive must go in while the fuel is still warm (it can't dissolve wax that already formed),
and the generator stands outside, so the decision uses the forecast minimum, not the current temperature.
"""
import html
import json
import math
from dataclasses import dataclass
from datetime import date

from redis.asyncio import Redis

from bot.config import config
from bot.database.models import Generator
from bot.services.weather import WeatherService
from bot.utils.clock import now_local

# Add the additive while the forecast minimum is still this far above the fuel's CFPP
SAFETY_MARGIN_C = 5.0
# Remind when this share of the tank is untreated fuel (protection drops below ~80%)
UNTREATED_SHARE = 0.2
FORECAST_DAYS = 3
# Used when the weather API is unavailable
COLD_MONTHS = {11, 12, 1, 2, 3}
FORECAST_CACHE_KEY = "weather:forecast_min"
FORECAST_CACHE_SECONDS = 3600


@dataclass(frozen=True)
class AntigelAdvice:
    needed: bool
    dose_ml: int
    untreated_l: float
    forecast_min: float | None
    too_cold_now: bool  # fuel may already be gelling: additive alone won't help, warm it up


def advise(untreated_l: float, fuel_level: float, forecast_min: float | None,
           current_temp: float | None, today: date) -> AntigelAdvice:
    cold = (forecast_min <= config.FUEL_CFPP_C + SAFETY_MARGIN_C if forecast_min is not None
            else today.month in COLD_MONTHS)
    untreated = max(0.0, min(untreated_l, fuel_level))
    share = untreated / fuel_level if fuel_level > 0 else 0.0
    return AntigelAdvice(
        needed=cold and share >= UNTREATED_SHARE,
        dose_ml=math.ceil(untreated * config.ANTIGEL_ML_PER_LITER),
        untreated_l=untreated,
        forecast_min=forecast_min,
        too_cold_now=current_temp is not None and current_temp <= config.FUEL_CFPP_C,
    )


def format_advice(gen_name: str, advice: AntigelAdvice, extra_hint: bool = False) -> str:
    """HTML reminder text. extra_hint: also tell the dose for the litres about to be poured."""
    forecast = (f" (прогноз до {advice.forecast_min:.0f}°C)" if advice.forecast_min is not None else "")
    text = (f"💉 <b>Потрібна присадка в {html.escape(gen_name)}</b>{forecast}\n"
            f"У баку ≈{advice.untreated_l:.0f} л палива без присадки: додайте ≈{advice.dose_ml} мл")
    if extra_hint:
        text += f" + {config.ANTIGEL_ML_PER_LITER:g} мл на кожен літр, що доллєте"
    text += ". Заливайте присадку до палива, поки не замерзло."
    if advice.too_cold_now:
        text += "\n⚠️ Вже холодно: паливо могло загуснути, спершу прогрійте генератор."
    return text


class AntigelService:
    def __init__(self, weather: WeatherService, redis: Redis | None = None):
        self.weather = weather
        self.redis = redis

    async def get_forecast_min(self) -> float | None:
        """Lowest temperature over the next FORECAST_DAYS days, cached in Redis for an hour."""
        if self.redis:
            cached = await self.redis.get(FORECAST_CACHE_KEY)
            if cached is not None:
                return json.loads(cached)
        days = (await self.weather.get_weekly_forecast())[:FORECAST_DAYS]
        value = min(d["temp_min"] for d in days) if days else None
        if self.redis:
            await self.redis.set(FORECAST_CACHE_KEY, json.dumps(value), ex=FORECAST_CACHE_SECONDS)
        return value

    async def advise_for(self, gen: Generator, extra_liters: float = 0.0,
                         with_current_temp: bool = True) -> AntigelAdvice:
        """extra_liters: untreated fuel just poured in but not yet recorded on the generator."""
        forecast_min = await self.get_forecast_min()
        current = await self.weather.get_current_temperature() if with_current_temp else None
        return advise((gen.fuel_since_antigel or 0.0) + extra_liters, (gen.fuel_level or 0.0) + extra_liters,
                      forecast_min, current, now_local().date())
