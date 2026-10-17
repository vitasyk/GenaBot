import html
import logging

import aiohttp

from bot.config import config

HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)
FALLBACK_TEMPERATURE = 0.0  # gives consumption factor 1.0 when the API is down


class WeatherService:
    BASE_URL = "https://api.openweathermap.org/data/2.5"

    def __init__(self):
        self.api_key = config.WEATHER_API_KEY.get_secret_value()
        self.lat = config.CITY_LAT
        self.lon = config.CITY_LON

    async def _get(self, endpoint: str) -> dict | None:
        params = {"lat": self.lat, "lon": self.lon, "appid": self.api_key, "units": "metric"}
        try:
            async with aiohttp.ClientSession(timeout=HTTP_TIMEOUT) as session:
                async with session.get(f"{self.BASE_URL}/{endpoint}", params=params) as resp:
                    if resp.status != 200:
                        logging.warning(f"OpenWeather /{endpoint} returned {resp.status}")
                        return None
                    return await resp.json()
        except (aiohttp.ClientError, TimeoutError):
            logging.warning(f"OpenWeather /{endpoint} is unavailable", exc_info=True)
            return None

    async def get_current_temperature(self) -> float:
        """Current temperature; FALLBACK_TEMPERATURE if the API fails, so callers never block on weather."""
        data = await self._get("weather")
        return data["main"]["temp"] if data else FALLBACK_TEMPERATURE

    async def get_weekly_forecast(self) -> list[dict]:
        """5 day / 3 hour forecast items, [] if the API fails."""
        data = await self._get("forecast")
        return data.get("list", []) if data else []

    def get_consumption_factor(self, temp: float) -> float:
        """Returns multiplier for fuel consumption based on temperature."""
        if temp < -10:
            return 1.2  # +20% in deep freeze
        elif temp < 0:
            return 1.1  # +10% below zero
        return 1.0

    async def get_daily_report(self) -> str:
        """Generates morning weather report with recommendations."""
        try:
            current_temp = await self.get_current_temperature()

            # Next 24h = 8 items x 3h
            next_24h = (await self.get_weekly_forecast())[:8]
            if not next_24h:
                return "⚠️ Weather data unavailable."

            temps = [f["main"]["temp"] for f in next_24h]
            min_temp = min(temps)
            max_temp = max(temps)

            is_freezing = min_temp < 0
            is_critical = min_temp < -10

            msg = "🌡️ <b>Прогноз погоди на сьогодні</b>\n\n"
            msg += f"Зараз: <b>{current_temp:.1f}°C</b>\n"
            msg += f"Діапазон: {min_temp:.1f}°C ... {max_temp:.1f}°C\n\n"

            if is_critical:
                msg += "❄️ <b>УВАГА! Сильні морози!</b>\n"
            elif is_freezing:
                msg += "🌨️ <b>Очікується мороз.</b>\n"

            msg += "⚠️ <b>РЕКОМЕНДАЦІЇ:</b>\n"
            if is_freezing:
                msg += "├ Прогріти генератори\n"
                msg += "├ Час прогріву: 5-7 хвилин\n"
            else:
                msg += "├ Штатний режим роботи\n"

            factor = self.get_consumption_factor(min_temp)
            if factor > 1.0:
                increase = int((factor - 1.0) * 100)
                msg += f"└ ⛽ Витрата палива: +{increase}%\n"

            return msg
        except Exception as e:
            logging.exception("Weather report failed")
            return f"⚠️ Error getting weather report: {html.escape(str(e))}"
