from aiogram import Router, F, types

from bot.generator_specs import LITERS_PER_CAN
from bot.services.weather import WeatherService

router = Router()

@router.message(F.text == "🌡️ Прогноз")
async def weather_forecast(message: types.Message, weather_service: WeatherService):
    """
    Показує тижневий прогноз погоди з розрахунком витрат палива
    """
    forecast = await weather_service.get_weekly_forecast()
    if not forecast:
        await message.answer("❌ Не вдалося отримати прогноз погоди", parse_mode="HTML")
        return

    text = "🌡️ <b>Прогноз на тиждень</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"

    for day_data in forecast[:7]:
        temp = day_data['main']['temp']

        if temp < -10:
            icon, consumption = "❄️❄️❄️", 3.5
        elif temp < -5:
            icon, consumption = "❄️❄️", 3.0
        elif temp < 0:
            icon, consumption = "❄️", 2.5
        else:
            icon, consumption = "🌤️", 2.0

        cans_per_day = (consumption * 24) / LITERS_PER_CAN
        text += f"{icon} <b>{temp:.0f}°C</b>\n"
        text += f"├ Витрата: ~{consumption}л/год\n"
        text += f"└ На добу: {cans_per_day:.1f} каністр\n\n"

    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += "💡 <i>Детальний аналіз палива скоро...</i>"

    await message.answer(text, parse_mode="HTML")
