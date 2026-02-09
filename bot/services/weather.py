import aiohttp
from bot.config import config

class WeatherService:
    BASE_URL = "https://api.openweathermap.org/data/2.5"

    def __init__(self):
        self.api_key = config.WEATHER_API_KEY.get_secret_value()
        self.lat = config.CITY_LAT
        self.lon = config.CITY_LON

    async def get_current_temperature(self) -> float:
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "lat": self.lat,
                    "lon": self.lon,
                    "appid": self.api_key,
                    "units": "metric"
                }
                async with session.get(f"{self.BASE_URL}/weather", params=params, timeout=5) as resp:
                    if resp.status != 200:
                        return 0.0
                    data = await resp.json()
                    return data["main"]["temp"]
        except Exception as e:
            # logging.error(f"Weather API error: {e}")
            return 0.0

    async def get_weekly_forecast(self) -> list[dict]:
        """
        Returns list of daily forecasts.
        """
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "lat": self.lat,
                    "lon": self.lon,
                    "appid": self.api_key,
                    "units": "metric"
                }
                # using /forecast endpoint (5 days/3 hour)
                async with session.get(f"{self.BASE_URL}/forecast", params=params, timeout=5) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return data.get("list", [])
        except Exception:
            return []

    async def check_cold_weather_alert(self) -> str | None:
        """
        Analyzes forecast and returns warning message if cold weather is expected.
        Criteria: < -10°C
        """
        forecasts = await self.get_weekly_forecast()
        min_temp = 100
        coldest_day = ""
        
        for f in forecasts:
            temp = f["main"]["temp_min"]
            if temp < min_temp:
                min_temp = temp
                coldest_day = f["dt_txt"]
        
        if min_temp < -10:
            return f"❄️ <b>Cold Warning!</b>\nTemp will drop to <b>{min_temp}°C</b> on {coldest_day}.\nCheck fuel and Anti-Gel!"
        
        return None

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
            # Get current and forecast
            current_temp = await self.get_current_temperature()
            
            # Simple forecast summary (next 24h)
            forecasts = await self.get_weekly_forecast()
            # Find min/max for next 24h (approx 8 items x 3h)
            next_24h = forecasts[:8]
            if not next_24h:
                 return "⚠️ Weather data unavailable."
                 
            temps = [f["main"]["temp"] for f in next_24h]
            min_temp = min(temps)
            max_temp = max(temps)
            
            # Determine status
            is_freezing = min_temp < 0
            is_critical = min_temp < -10
            
            msg = f"🌡️ <b>Прогноз погоди на сьогодні</b>\n\n"
            msg += f"Зараз: <b>{current_temp:.1f}°C</b>\n"
            msg += f"Діапазон: {min_temp:.1f}°C ... {max_temp:.1f}°C\n\n"
            
            if is_critical:
                msg += f"❄️ <b>УВАГА! Сильні морози!</b>\n"
            elif is_freezing:
                msg += f"🌨️ <b>Очікується мороз.</b>\n"
            
            msg += "⚠️ <b>РЕКОМЕНДАЦІЇ:</b>\n"
            if is_freezing:
                msg += "├ Прогріти генератори\n"
                msg += "├ Час прогріву: 5-7 хвилин\n"
            else:
                msg += "├ Штатний режим роботи\n"
            
            # Fuel impact
            factor = self.get_consumption_factor(min_temp)
            if factor > 1.0:
                 increase = int((factor - 1.0) * 100)
                 msg += f"└ ⛽ Витрата палива: +{increase}%\n"
            
            return msg
        except Exception as e:
            return f"⚠️ Error getting weather report: {e}"
