import asyncio
import html
import logging
from datetime import timedelta
from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import config
from bot.database.repositories.user import UserRepository
from bot.handlers.schedule._common import (
    _ask_save_confirmation,
    _format_ranges,
    _hours_to_ranges,
)
from bot.keyboards.schedule_kb import get_date_quick_kb, get_schedule_menu_kb
from bot.services.schedule_parser import ScheduleParser
from bot.services.schedule_recognizer import (
    ScheduleRecognitionError,
    ScheduleRecognizer,
)
from bot.states import ScheduleStates
from bot.utils.clock import now_local

logger = logging.getLogger(__name__)

router = Router()
parser = ScheduleParser()
recognizer = ScheduleRecognizer()

@router.message(F.text == "📸 Розпізнати з фото")
async def start_photo_recognition(message: Message, state: FSMContext, user_repo: UserRepository):
    """Prompt for schedule screenshot (admin only)"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return
    
    await state.set_state(ScheduleStates.waiting_for_screenshot)
    
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Скасувати")]],
        resize_keyboard=True
    )
    
    await message.answer(
        "📸 <b>Розпізнавання графіку з фото</b>\n\n"
        f"Надішліть скріншот офіційного графіку HOE (черга {config.QUEUE_NUMBER}).\n"
        "Бот спробує автоматично визначити періоди відключень.",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )

async def _send_cached_schedule(callback: CallbackQuery, suffix: str, label: str, reason: str) -> None:
    """HOE is down: show the last downloaded image for this day, if any."""
    cached_img = parser.get_cached_schedule(suffix=suffix)
    if not cached_img:
        await callback.message.edit_text(f"{reason}\n\nСпробуйте пізніше або введіть графік вручну.", parse_mode="HTML")
        return
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=BufferedInputFile(cached_img, filename=f"cached_schedule_{suffix}.png"),
        caption=f"{reason}\n\nПоказую <b>останній завантажений</b> графік на {label}.\n"
                "<i>Він може бути неактуальним!</i>",
        parse_mode="HTML"
    )

@router.callback_query(F.data.in_({"hoe_today", "hoe_tomorrow"}))
async def process_hoe_download_callback(callback: CallbackQuery, state: FSMContext):
    """Download the HOE image for the chosen day, recognize it with Claude, offer admins to save it"""
    today = now_local().date()
    is_today = callback.data == "hoe_today"
    target_date = today if is_today else today + timedelta(days=1)
    label = "сьогодні" if is_today else "завтра"
    suffix = "today" if is_today else "tomorrow"

    await callback.answer()  # Answer immediately to prevent Telegram timeout
    await callback.message.edit_text(f"🔍 <b>Шукаю графік на {label}...</b>", parse_mode="HTML")

    try:
        results = await asyncio.wait_for(parser.get_schedules_data(), timeout=30.0)
    except TimeoutError:
        logger.error("HOE download timed out (30s)")
        await _send_cached_schedule(callback, suffix, label, "⚠️ <b>Сайт HOE недоступний (таймаут)</b>")
        return

    img_bytes = next((b for d, b in results if d.date() == target_date), None)
    if not img_bytes:
        if not results:
            await _send_cached_schedule(callback, suffix, label, "❌ <b>Не вдалося завантажити графік з HOE</b>")
            return
        await callback.message.edit_text(
            f"⚠️ <b>Графіку на {label} ({target_date.strftime('%d.%m')}) ще немає</b>\n\n"
            "На сайті HOE поки що не опубліковано відповідний графік.\n"
            "Спробуйте пізніше або введіть дані вручну.",
            parse_mode="HTML"
        )
        return

    caption = f"🖼️ <b>Офіційний графік на {target_date.strftime('%d.%m')}</b>\n"
    periods = None
    try:
        periods = _hours_to_ranges(await recognizer.recognize(img_bytes, config.QUEUE_NUMBER))
        caption += f"\nЧерга {html.escape(config.QUEUE_NUMBER)} (розпізнано ШІ):\n{_format_ranges(periods)}"
    except ScheduleRecognitionError as e:
        logger.warning(f"Schedule recognition failed: {e}")
        caption += f"\n⚠️ Не вдалося розпізнати: {html.escape(str(e))}\nВикористовуйте «✏️ Ввести вручну»."

    await callback.message.delete()
    await callback.message.answer_photo(
        photo=BufferedInputFile(img_bytes, filename=f"schedule_{target_date.isoformat()}.png"),
        caption=caption,
        parse_mode="HTML"
    )
    logger.info(f"User {callback.from_user.id} viewed HOE image for {target_date}")

    if periods is not None and callback.from_user.id in config.ADMIN_IDS:
        await _ask_save_confirmation(callback.message, state, target_date, periods)

@router.message(ScheduleStates.waiting_for_screenshot, F.text == "🔙 Скасувати")
async def process_schedule_screenshot_cancel(message: Message, state: FSMContext, user_repo: UserRepository):
    """Cancel waiting for screenshot"""
    await state.clear()
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer("❌ Скасовано", reply_markup=get_schedule_menu_kb(is_admin=is_admin))

@router.message(ScheduleStates.waiting_for_screenshot, F.photo | F.document)
async def process_schedule_screenshot(message: Message, state: FSMContext, user_repo: UserRepository):
    """Recognize an uploaded schedule screenshot with Claude"""
    is_admin = message.from_user.id in config.ADMIN_IDS
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id
    else:
        await message.answer("⚠️ Будь ласка, надішліть зображення (скріншот).")
        return

    await message.answer("🔍 <b>Аналізую зображення...</b>", parse_mode="HTML")

    file_io = BytesIO()
    await message.bot.download(file_id, destination=file_io)
    try:
        hours = await recognizer.recognize(file_io.getvalue(), config.QUEUE_NUMBER)
    except ScheduleRecognitionError as e:
        logger.warning(f"Photo recognition failed: {e}")
        await state.clear()
        await message.answer(
            f"❌ <b>Не вдалося розпізнати графік</b>\n{html.escape(str(e))}\n\n"
            "Спробуйте інше фото або введіть дані вручну.",
            reply_markup=get_schedule_menu_kb(is_admin=is_admin),
            parse_mode="HTML"
        )
        return

    periods = _hours_to_ranges(hours)
    await state.update_data(periods=periods)
    await state.set_state(ScheduleStates.waiting_for_date)
    await message.answer(
        f"✅ <b>Графік розпізнано!</b>\n\nВиявлено періоди:\n{_format_ranges(periods)}\n\n"
        f"📅 <b>Для якого дня встановити цей графік?</b>",
        reply_markup=get_date_quick_kb(),
        parse_mode="HTML"
    )

