import logging

from aiogram import F, Router, types

from bot.services.generator import GeneratorService
from bot.services.inventory import InventoryService
from bot.services.weather import WeatherService

logger = logging.getLogger(__name__)

router = Router()

@router.message(F.text == "🌡️ Прогноз")
async def weather_forecast(message: types.Message, weather_service: WeatherService, generator_service: GeneratorService, inventory_service: InventoryService):
    """
    Показує тижневий прогноз погоди з розрахунком витрат палива
    """
    try:
        forecast = await weather_service.get_weekly_forecast()
        
        if not forecast:
            await message.answer("❌ Не вдалося отримати прогноз погоди", parse_mode="HTML")
            return
        
        # 1. Get current stock
        stock_liters = await inventory_service.check_stock()
        
        # 2. Get active generators for consumption calculation
        gens = await generator_service.get_status()
        
        # Calculate total base hourly consumption for ALL enabled generators (assuming worst case)
        # Or just running ones? Better to show "If you run all generators"
        # Let's sum up consumption of locally available gens as a baseline
        base_hourly_consumption = 0.0
        active_gen_names = []
        for g in gens:
            # Assume we want to know consumption if we run the main gens
            # If nothing is running, maybe take the standard set?
            # Let's use all generators found in DB as potential load
            base_hourly_consumption += g.consumption_rate
            active_gen_names.append(g.name)
            
        if base_hourly_consumption == 0:
            base_hourly_consumption = 2.0 # Fallback
            
        text = "🌡️ <b>Прогноз на 5 днів</b>\n"
        text += f"⛽ Активні генератори: {', '.join(active_gen_names)}\n"
        text += f"📦 Запас палива: <b>{stock_liters}л</b>\n"
        text += "➖➖➖➖➖➖➖➖➖➖\n"
        
        total_projected_consumption_24h = 0
        
        # Weekly forecast
        for day_data in forecast[:5]:
            date_str = day_data['date']
            temp_min = day_data['temp_min']
            temp_max = day_data['temp_max']
            icon_code = day_data['icon']
            
            # Icons
            weather_icon = "🌤️"
            if "01" in icon_code: weather_icon = "☀️"
            elif "02" in icon_code: weather_icon = "⛅"
            elif "03" in icon_code or "04" in icon_code: weather_icon = "☁️"
            elif "09" in icon_code: weather_icon = "🌧️"
            elif "10" in icon_code: weather_icon = "🌦️"
            elif "11" in icon_code: weather_icon = "⛈️"
            elif "13" in icon_code: weather_icon = "❄️"
            elif "50" in icon_code: weather_icon = "🌫️"
            
            # Cold warning icon
            if temp_min < -10: weather_icon = "🥶"
            
            # Consumption factor
            factor = weather_service.get_consumption_factor(temp_min)
            daily_consumption_rate = base_hourly_consumption * factor
            
            # Scenarios
            # 1. Continuous Run (24h) - Worst case
            usage_24h = daily_consumption_rate * 24
            total_projected_consumption_24h += usage_24h
            
            # Date formatting (YYYY-MM-DD -> DD.MM)
            date_fmt = date_str.split("-")[2] + "." + date_str.split("-")[1]
            
            text += f"{weather_icon} <b>{date_fmt}</b>: {temp_min:.0f}°C ... {temp_max:.0f}°C\n"
            if factor > 1.0:
                text += f"⚠️ Холод: +{int((factor-1)*100)}% до витрат\n"
            text += f"📉 Витрата (24год): ~{usage_24h:.0f}л\n\n"
        
        text += "➖➖➖➖➖➖➖➖➖➖\n"
        
        # Coverage Estimation
        days_coverage = stock_liters / (total_projected_consumption_24h / 5) # avg daily usage
        
        text += "📊 <b>Аналіз запасів:</b>\n"
        text += f"При безперервній роботі ({base_hourly_consumption}л/год + погода):\n"
        text += f"🏁 Вистачить на: ~<b>{days_coverage:.1f} днів</b>"
        
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        logger.exception("Forecast error")
        await message.answer(f"❌ Помилка отримання прогнозу: {e}", parse_mode="HTML")
