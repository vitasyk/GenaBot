import html
import logging

from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import BufferedInputFile

from bot.config import config
from bot.database.models import UserRole
from bot.database.repositories.user import UserRepository
from bot.keyboards.callbacks import GenCallback
from bot.keyboards.inline_kb import get_generator_select_kb
from bot.keyboards.main_kb import get_main_keyboard
from bot.services.generator import GeneratorService
from bot.services.schedule_parser import ScheduleParser, format_hours

router = Router()

SOS_MENU_TEXT = "🆘 <b>Оберіть генератор для інструкції:</b>"
NO_INSTRUCTIONS_TEXT = "Інструкцію ще не додано. Адміністратор може додати її в адмін-панелі → ⚙️ Генератори."

@router.message(CommandStart())
@router.message(Command("menu"))
@router.message(Command("help"))
async def cmd_start(message: types.Message, user_repo: UserRepository):
    user = await user_repo.create_or_update(
        user_id=message.from_user.id,
        name=message.from_user.full_name
    )

    if user.role == UserRole.blocked:
        await message.answer("⛔ <b>Доступ заборонено</b>\nЗверніться до адміністратора для надання доступу.", parse_mode="HTML")
        return

    await message.answer(
        f"👋 Вітаю, {html.escape(user.name)}!\n"
        f"Роль: {user.role.value}\n"
        f"Використовуйте кнопки нижче для керування генераторами.",
        reply_markup=get_main_keyboard(user.role == UserRole.admin),
        parse_mode="HTML"
    )

@router.message(F.text == "🆘 Інструкція (SOS)")
async def sos_handler(message: types.Message, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await message.answer(SOS_MENU_TEXT, reply_markup=get_generator_select_kb(gens, "sos", "❌ Закрити", "stock_close"),
                         parse_mode="HTML")

@router.callback_query(F.data == "sos_menu")
async def sos_menu_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await callback.message.edit_text(SOS_MENU_TEXT, reply_markup=get_generator_select_kb(gens, "sos", "❌ Закрити", "stock_close"),
                                     parse_mode="HTML")
    await callback.answer()

@router.callback_query(GenCallback.filter(F.action == "sos"))
async def sos_generator(callback: types.CallbackQuery, callback_data: GenCallback, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.gen_id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return

    text = f"🔧 <b>{html.escape(gen.name)}</b>\n\n{html.escape(gen.instructions or NO_INSTRUCTIONS_TEXT)}"
    back = types.InlineKeyboardMarkup(inline_keyboard=[[types.InlineKeyboardButton(text="🔙 Назад", callback_data="sos_menu")]])
    await callback.message.edit_text(text, reply_markup=back, parse_mode="HTML")
    await callback.answer()

@router.message(F.text == "📉 Графік")
async def show_schedule_common(message: types.Message, schedule_parser: ScheduleParser):
    wait_msg = await message.answer("⏳ <b>Завантаження графіку...</b>", parse_mode="HTML")

    try:
        img_bytes = await schedule_parser.fetch_latest_schedule_image()
        hours_by_date = await schedule_parser.get_hours_by_date(config.QUEUE_NUMBER)
    except Exception as e:
        logging.exception("Schedule view failed")
        await wait_msg.edit_text(f"❌ <b>Помилка:</b>\n{html.escape(str(e))}", parse_mode="HTML")
        return

    caption = f"📈 <b>Актуальний графік відключень</b>\nЧерга {html.escape(config.QUEUE_NUMBER)}:\n"
    caption += "\n".join(f"• {day.strftime('%d.%m')}: {format_hours(hours)}" for day, hours in sorted(hours_by_date.items()))

    if img_bytes:
        await message.answer_photo(BufferedInputFile(img_bytes, filename="schedule.png"), caption=caption, parse_mode="HTML")
        await wait_msg.delete()
    elif hours_by_date:
        await wait_msg.edit_text(caption, parse_mode="HTML")
    else:
        await wait_msg.edit_text("❌ Не вдалося отримати картинку з сайту.")
