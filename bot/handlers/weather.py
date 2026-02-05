from aiogram import Router, F, types
from bot.services.weather import WeatherService

router = Router()

@router.message(F.text == "🌡️ Прогноз")
async def weather_forecast(message: types.Message, weather_service: WeatherService):
    """
    Показує тижневий прогноз погоди з розрахунком витрат палива
    """
    try:
        forecast = await weather_service.get_weekly_forecast()
        
        if not forecast:
            await message.answer("❌ Не вдалося отримати прогноз погоди", parse_mode="HTML")
            return
        
        text = "🌡️ <b>Прогноз на тиждень</b>\n"
        text += "➖➖➖➖➖➖➖➖➖➖\n"
        
        # Weekly forecast - API returns list with 'main' dict containing 'temp'
        for day_data in forecast[:7]:
            # Extract temperature from API response structure
            temp = day_data['main']['temp']
            
            # Temperature icons and consumption calculation
            if temp < -10:
                icon = "❄️❄️❄️"
                consumption = 3.5
            elif temp < -5:
                icon = "❄️❄️"
                consumption = 3.0
            elif temp < 0:
                icon = "❄️"
                consumption = 2.5
            else:
                icon = "🌤️"
                consumption = 2.0
            
            cans_per_day = (consumption * 24) / 20  # 20L per can
            text += f"{icon} <b>{temp:.0f}°C</b>\n"
            text += f"├ Витрата: ~{consumption}л/год\n"
            text += f"└ На добу: {cans_per_day:.1f} каністр\n\n"
        
        text += "➖➖➖➖➖➖➖➖➖➖\n"
        text += "💡 <i>Детальний аналіз палива скоро...</i>"
        
        await message.answer(text, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Помилка отримання прогнозу: {e}", parse_mode="HTML")
