import logging

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)

class WeatherService:
    BASE_URL = "https://api.openweathermap.org/data/2.5"

    def __init__(self):
        self.api_key = config.WEATHER_API_KEY.get_secret_value()
        self.lat = config.CITY_LAT
        self.lon = config.CITY_LON

    async def get_current_temperature(self) -> float | None:
        """Current temperature, or None when the API is unavailable."""
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
                        logger.warning("Weather API /weather returned HTTP %s", resp.status)
                        return None
                    data = await resp.json()
                    return data["main"]["temp"]
        except Exception as e:
            # Only the type: aiohttp messages can contain the request URL with appid
            logger.warning("Weather API /weather failed: %s", type(e).__name__)
            return None

    async def get_weekly_forecast(self) -> list[dict]:
        """
        Returns list of daily forecasts (aggregated from 3h data).
        Each item: {
            "date": "2023-10-27",
            "temp_min": 5.0,
            "temp_max": 12.0,
            "condition": "Clouds",
            "icon": "04d"
        }
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
                        logger.warning("Weather API /forecast returned HTTP %s", resp.status)
                        return []
                    data = await resp.json()
                    raw_list = data.get("list", [])
                    
                    # Aggregate by day
                    daily_data = {}
                    
                    for item in raw_list:
                        dt_txt = item.get("dt_txt", "")
                        if not dt_txt: continue
                        
                        date_str = dt_txt.split(" ")[0]
                        temp = item["main"]["temp"]
                        weather = item["weather"][0]
                        
                        if date_str not in daily_data:
                            daily_data[date_str] = {
                                "temps": [],
                                "conditions": [],
                                "icons": []
                            }
                        
                        daily_data[date_str]["temps"].append(temp)
                        daily_data[date_str]["conditions"].append(weather["main"])
                        daily_data[date_str]["icons"].append(weather["icon"])
                    
                    # Format output
                    result = []
                    for date, info in daily_data.items():
                        temps = info["temps"]
                        # Simple most common condition
                        from collections import Counter
                        common_cond = Counter(info["conditions"]).most_common(1)[0][0]
                        common_icon = Counter(info["icons"]).most_common(1)[0][0]
                        
                        result.append({
                            "date": date,
                            "temp_min": min(temps),
                            "temp_max": max(temps),
                            "temp_avg": sum(temps) / len(temps),
                            "condition": common_cond,
                            "icon": common_icon
                        })
                        
                    return result
        except Exception as e:
            logger.warning("Weather API /forecast failed: %s", type(e).__name__)
            return []

    def get_consumption_factor(self, temp: float | None) -> float:
        """Returns multiplier for fuel consumption based on temperature.
        Unknown temperature (None) gets the worst case, so remaining fuel is never overestimated."""
        if temp is None or temp < -10:
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
            
            if not forecasts:
                 return "⚠️ Weather data unavailable."
                 
            # Use the first day's aggregated data
            today_forecast = forecasts[0]
            min_temp = today_forecast["temp_min"]
            max_temp = today_forecast["temp_max"]
            
            # Determine status
            is_freezing = min_temp < 0
            is_critical = min_temp < -10
            
            msg = "🌡️ <b>Прогноз погоди на сьогодні</b>\n\n"
            current = f"{current_temp:.1f}°C" if current_temp is not None else "н/д"
            msg += f"Зараз: <b>{current}</b>\n"
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
            
            # Fuel impact
            factor = self.get_consumption_factor(min_temp)
            if factor > 1.0:
                 increase = int((factor - 1.0) * 100)
                 msg += f"└ ⛽ Витрата палива: +{increase}%\n"
            
            return msg
        except Exception:
            logger.exception("Weather daily report failed")
            return "⚠️ Weather data unavailable."
