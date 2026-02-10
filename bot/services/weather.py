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
                        return []
                    data = await resp.json()
                    raw_list = data.get("list", [])
                    
                    # Aggregate by day
                    daily_data = {}
                    from datetime import datetime
                    
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
            if f["temp_min"] < min_temp:
                min_temp = f["temp_min"]
                coldest_day = f["date"]
        
        if min_temp < -10:
            return f"❄️ <b>Cold Warning!</b>\nTemp will drop to <b>{min_temp:.1f}°C</b> on {coldest_day}.\nCheck fuel and Anti-Gel!"
        
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
