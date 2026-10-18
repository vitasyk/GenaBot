"""Schedule management handlers"""
import asyncio
import html
import logging
import re
from io import BytesIO
from typing import List, Tuple
from datetime import date, timedelta
from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.states import ScheduleStates
from bot.keyboards.schedule_kb import (
    get_schedule_menu_kb, 
    get_date_quick_kb, 
    get_confirm_kb, 
    get_hoe_selection_kb,
    get_clear_confirm_kb,
    get_queue_kb
)
from bot.keyboards.main_kb import get_main_keyboard
from bot.config import config
from bot.database.repositories.schedule import ScheduleRepository
from bot.database.repositories.user import UserRepository
from bot.scheduler import save_runtime_setting
from bot.services.schedule_parser import ScheduleParser
from bot.services.schedule_recognizer import ScheduleRecognitionError, ScheduleRecognizer
from bot.utils.clock import now_local

router = Router()
parser = ScheduleParser()
recognizer = ScheduleRecognizer()

# HOE has 6 queues x 2 subqueues; any other one can be typed in
QUEUE_BUTTONS = [f"{q}.{sub}" for q in range(1, 7) for sub in (1, 2)]
QUEUE_PATTERN = re.compile(r"\d{1,2}\.\d")

# Main Schedule Menu
@router.message(F.text == "📉 Графік")
async def schedule_menu(message: Message, user_repo: UserRepository):
    """Show schedule management submenu"""
    is_admin = message.from_user.id in config.ADMIN_IDS
    
    await message.answer(
        "📅 <b>Управління графіком відключень</b>\n\n"
        "Оберіть дію:",
        reply_markup=get_schedule_menu_kb(is_admin=is_admin),
        parse_mode="HTML"
    )

@router.message(F.text == "🔙 Головне меню")
async def back_to_main(message: Message, state: FSMContext, user_repo: UserRepository):
    """Return to main menu"""
    await state.clear()
    is_admin = message.from_user.id in config.ADMIN_IDS
    
    await message.answer(
        "🏠 Головне меню",
        reply_markup=get_main_keyboard(is_admin=is_admin)
    )

# Manual Entry Flow
@router.message(F.text == "✏️ Ввести вручну")
async def start_manual_entry(message: Message, state: FSMContext, user_repo: UserRepository):
    """Start manual schedule entry (admin only)"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return

    await state.clear()  # drop periods left over from an unfinished photo recognition
    await state.set_state(ScheduleStates.waiting_for_date)
    await message.answer(
        "📅 <b>Введення графіку вручну</b>\n\n"
        "Введіть дату для якої хочете встановити графік:\n"
        "• Сьогодні\n"
        "• Завтра\n"
        "• Формат: ДД.ММ (наприклад: 05.02)",
        reply_markup=get_date_quick_kb(),
        parse_mode="HTML"
    )

# View Schedule
@router.message(F.text == "📋 Переглянути графік")
async def view_schedule(message: Message, schedule_repo: ScheduleRepository, state: FSMContext, user_repo: UserRepository):
    """View current schedule"""
    await state.clear()
    
    is_admin = message.from_user.id in config.ADMIN_IDS
    
    today = now_local().date()
    tomorrow = today + timedelta(days=1)
    
    # Get entries for today and tomorrow
    entries_today = await schedule_repo.get_entries_for_date(today, config.QUEUE_NUMBER)
    entries_tomorrow = await schedule_repo.get_entries_for_date(tomorrow, config.QUEUE_NUMBER)
    
    response = f"📅 <b>Графік відключень (Черга {config.QUEUE_NUMBER})</b>\n\n"
    
    # Today
    if entries_today:
        response += f"<b>Сьогодні ({today.strftime('%d.%m.%Y')}):</b>\n"
        for e in entries_today:
            response += f"• {e.start_hour:02d}:00 - {e.end_hour:02d}:00\n"
    else:
        response += f"<b>Сьогодні ({today.strftime('%d.%m.%Y')}):</b> графік не встановлено\n"
    
    response += "\n"
    
    # Tomorrow
    if entries_tomorrow:
        response += f"<b>Завтра ({tomorrow.strftime('%d.%m.%Y')}):</b>\n"
        for e in entries_tomorrow:
            response += f"• {e.start_hour:02d}:00 - {e.end_hour:02d}:00\n"
    else:
        response += f"<b>Завтра ({tomorrow.strftime('%d.%m.%Y')}):</b> графік не встановлено\n"
    
    await message.answer(response, parse_mode="HTML", reply_markup=get_schedule_menu_kb(is_admin=is_admin))

# Clear Schedule
@router.message(F.text == "🗑️ Очистити графік")
async def clear_schedule_prompt(message: Message, state: FSMContext, user_repo: UserRepository):
    """Show confirmation for clearing schedule (admin only)"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return
    
    await state.clear()
    await message.answer(
        "❓ <b>Ви впевнені, що хочете очистити графік на сьогодні?</b>\n\n"
        f"Це видалить всі ручні записи для черги {config.QUEUE_NUMBER} на поточну дату.",
        reply_markup=get_clear_confirm_kb(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "clear_confirm")
async def process_clear_confirm_callback(callback: CallbackQuery, schedule_repo: ScheduleRepository):
    """Execute schedule clearing after confirmation"""
    today = now_local().date()
    deleted = await schedule_repo.clear_all_for_date(today, config.QUEUE_NUMBER)
    
    await callback.message.edit_text(
        f"✅ <b>Графік на {today.strftime('%d.%m.%Y')} очищено</b>\n"
        f"Видалено записів: {deleted}",
        parse_mode="HTML"
    )
    await callback.answer("Графік очищено!")

@router.callback_query(F.data == "clear_cancel")
async def process_clear_cancel_callback(callback: CallbackQuery):
    """Cancel schedule clearing"""
    await callback.message.edit_text("❌ <b>Очищення скасовано</b>", parse_mode="HTML")
    await callback.answer("Скасовано")

# HOE Download - Visual only (no DB updates)
@router.message(F.text == "🌐 Завантажити з HOE")
async def download_from_hoe_visual(message: Message, state: FSMContext):
    """Show options for HOE download"""
    await state.clear()
    await message.answer(
        "📅 <b>Завантаження графіку</b>\n\n"
        "Оберіть день, за який хочете отримати графік:",
        reply_markup=get_hoe_selection_kb(),
        parse_mode="HTML"
    )

@router.message(F.text == "📸 Розпізнати з фото")
async def start_photo_recognition(message: Message, state: FSMContext, user_repo: UserRepository):
    """Prompt for schedule screenshot (admin only)"""
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return
    
    await state.set_state(ScheduleStates.waiting_for_screenshot)
    
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
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

def _format_ranges(ranges: List[Tuple[int, int]]) -> str:
    if not ranges:
        return "• відключень немає"
    return "\n".join(f"• {s:02d}:00 - {e:02d}:00" for s, e in ranges)

async def _ask_save_confirmation(message: Message, state: FSMContext, target_date: date, periods: List[Tuple[int, int]]):
    """Shows the periods to save and waits for ✅/❌ (handled by confirm_schedule)."""
    await state.update_data(target_date=target_date.isoformat(), periods=periods)
    await state.set_state(ScheduleStates.confirming)
    await message.answer(
        f"📋 <b>Підтвердження</b>\n\n"
        f"📅 Дата: <b>{target_date.strftime('%d.%m.%Y')}</b>\n"
        f"📋 Черга: <b>{html.escape(config.QUEUE_NUMBER)}</b>\n\n"
        f"⏰ Періоди відключень:\n{_format_ranges(periods)}\n\n"
        f"Всього блоків: {len(periods)}",
        reply_markup=get_confirm_kb(),
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
    except asyncio.TimeoutError:
        logging.error("HOE download timed out (30s)")
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
        logging.warning(f"Schedule recognition failed: {e}")
        caption += f"\n⚠️ Не вдалося розпізнати: {html.escape(str(e))}\nВикористовуйте «✏️ Ввести вручну»."

    await callback.message.delete()
    await callback.message.answer_photo(
        photo=BufferedInputFile(img_bytes, filename=f"schedule_{target_date.isoformat()}.png"),
        caption=caption,
        parse_mode="HTML"
    )
    logging.info(f"User {callback.from_user.id} viewed HOE image for {target_date}")

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
        logging.warning(f"Photo recognition failed: {e}")
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

# Queue selection (admin only)
async def _save_queue(state: FSMContext, queue: str) -> None:
    config.QUEUE_NUMBER = queue
    await save_runtime_setting(state.storage.redis, "QUEUE_NUMBER", queue)
    logging.info(f"Queue changed to {queue}")

@router.message(F.text == "🔢 Черга")
async def queue_menu(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return
    await message.answer(
        f"🔢 <b>Яку чергу відстежувати?</b>\n\nЗараз: <b>{html.escape(config.QUEUE_NUMBER)}</b>.\n"
        "Від черги залежать графік, розпізнавання ШІ та сесії заправки.",
        reply_markup=get_queue_kb(QUEUE_BUTTONS, config.QUEUE_NUMBER),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("queue_set:"))
async def queue_set(callback: CallbackQuery, state: FSMContext):
    queue = callback.data.split(":", 1)[1]
    if callback.from_user.id not in config.ADMIN_IDS or not QUEUE_PATTERN.fullmatch(queue):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await _save_queue(state, queue)
    await callback.message.edit_text(f"✅ Черга: <b>{queue}</b>", parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "queue_custom")
async def queue_custom(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await state.set_state(ScheduleStates.waiting_for_queue)
    await callback.message.edit_text("✍️ Введіть номер черги, наприклад <code>4.2</code>.", parse_mode="HTML")
    await callback.answer()

@router.message(ScheduleStates.waiting_for_queue)
async def queue_input(message: Message, state: FSMContext):
    queue = (message.text or "").strip().replace(",", ".")
    if not QUEUE_PATTERN.fullmatch(queue):
        await message.answer("⚠️ Формат: число, крапка, число — наприклад <code>1.1</code>.", parse_mode="HTML")
        return
    await _save_queue(state, queue)
    await state.clear()
    await message.answer(f"✅ Черга: <b>{queue}</b>", parse_mode="HTML",
                         reply_markup=get_schedule_menu_kb(is_admin=True))

# Manual Entry State Handlers (Must be AFTER specific button handlers)
@router.message(ScheduleStates.waiting_for_date)
async def process_date_input(message: Message, state: FSMContext, user_repo: UserRepository):
    """Process date input"""
    if not message.text:
        return
        
    logging.info(f"Schedule: process_date_input text='{message.text}' state={await state.get_state()}")
    
    if message.text == "🔙 Скасувати":
        await state.clear()
        is_admin = message.from_user.id in config.ADMIN_IDS
        await message.answer("❌ Скасовано", reply_markup=get_schedule_menu_kb(is_admin=is_admin))
        return
        
    # Skip if user accidentally pressed another main menu button or command
    if message.text.startswith("/") or message.text in ["✏️ Ввести вручну", "📉 Графік", "🌐 Завантажити з HOE", "📋 Переглянути графік", "🗑️ Очистити графік", "🔙 Головне меню"]:
        logging.info("Schedule: clearing state due to command/menu button in date input")
        await state.clear()
        if message.text == "🔙 Головне меню":
             await back_to_main(message, state, user_repo)
        return
    
    # Parse date
    target_date = None
    text_lower = message.text.lower().strip()
    
    if text_lower in ["сьогодні", "today"]:
        target_date = now_local().date()
    elif text_lower in ["завтра", "tomorrow"]:
        target_date = now_local().date() + timedelta(days=1)
    else:
        # Try parsing DD.MM or DD.MM.YY format
        match = re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$", text_lower)
        if match:
            day, month = int(match.group(1)), int(match.group(2))
            year = now_local().year
            if match.group(3):
                year_val = int(match.group(3))
                year = 2000 + year_val if year_val < 100 else year_val
            
            try:
                target_date = date(year, month, day)
            except ValueError:
                pass
    
    if not target_date:
        await message.answer(
            "❌ Невірний формат дати. Спробуйте ще раз.\n"
            "Приклади: Сьогодні, Завтра, 05.02",
            reply_markup=get_date_quick_kb()
        )
        return
    
    
    # Periods already recognized from a photo: go straight to confirmation
    recognized = (await state.get_data()).get("periods")
    if recognized is not None:
        await _ask_save_confirmation(message, state, target_date, [tuple(p) for p in recognized])
        return

    # Save date as ISO string (for JSON serialization in Redis)
    await state.update_data(target_date=target_date.isoformat())
    await state.set_state(ScheduleStates.waiting_for_periods)
    
    # Send cancel only keyboard for periods input
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Скасувати")]],
        resize_keyboard=True
    )
    
    await message.answer(
        f"📅 Дата: <b>{target_date.strftime('%d.%m.%Y')}</b>\n\n"
        "⏰ <b>Введіть періоди відключень</b>\n\n"
        "Формат: години через тире, періоди через кому\n"
        "Приклад: <code>0-6, 11-15, 18-23</code>\n\n"
        "Це означає:\n"
        "• 00:00 - 06:00\n"
        "• 11:00 - 15:00\n"
        "• 18:00 - 23:00",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )

def _hours_to_ranges(hours: List[int]) -> List[tuple[int, int]]:
    """Convert list of hours to list of (start, end) ranges"""
    if not hours:
        return []

    hours = sorted(hours)
    ranges = []
    start = hours[0]
    for i in range(1, len(hours)):
        if hours[i] != hours[i-1] + 1:
            ranges.append((start, hours[i-1] + 1))
            start = hours[i]
    ranges.append((start, hours[-1] + 1))
    return ranges

@router.message(ScheduleStates.waiting_for_periods)
async def process_periods_input(message: Message, state: FSMContext, schedule_repo: ScheduleRepository, user_repo: UserRepository):
    """Process time periods input"""
    if message.text == "🔙 Скасувати":
        await state.clear()
        is_admin = message.from_user.id in config.ADMIN_IDS
        await message.answer("❌ Скасовано", reply_markup=get_schedule_menu_kb(is_admin=is_admin))
        return
        
    # Skip if user accidentally pressed another main menu button or command
    if message.text.startswith("/") or message.text in [
        "✏️ Ввести вручну", "📉 Графік", "🌐 Завантажити з HOE", "📋 Переглянути графік", 
        "🗑️ Очистити графік", "🔙 Головне меню", "Сьогодні", "Завтра"
    ]:
        logging.info("Schedule: clearing state due to command/menu button in periods input")
        await state.clear()
        if message.text == "🔙 Головне меню":
             await back_to_main(message, state, user_repo)
        return

    # Parse format: "0-6, 11-15, 18-23"
    periods = []
    
    try:
        # Split by comma
        parts = message.text.split(',')
        for part in parts:
            part = part.strip()
            match = re.match(r"(\d{1,2})\s*-\s*(\d{1,2})", part)
            if not match:
                raise ValueError(f"Невірний формат: {part}")
            
            start = int(match.group(1))
            end = int(match.group(2))
            
            if start < 0 or start > 23 or end < 0 or end > 24:
                raise ValueError("Години мають бути від 0 до 23 (кінець до 24)")
            
            if start >= end:
                raise ValueError(f"Початок має бути менше кінця: {start}-{end}")
            
            periods.append((start, end))
    
    except Exception as e:
        await message.answer(
            f"❌ Помилка в форматі: {e}\n\n"
            "Приклад: <code>0-6, 11-15, 18-23</code>",
            parse_mode="HTML"
        )
        return
    
    target_date = date.fromisoformat((await state.get_data())['target_date'])
    await _ask_save_confirmation(message, state, target_date, periods)

@router.message(ScheduleStates.confirming, F.text == "✅ Підтвердити")
async def confirm_schedule(message: Message, state: FSMContext, schedule_repo: ScheduleRepository, user_repo: UserRepository):
    """Confirm and save schedule"""
    data = await state.get_data()
    
    # Convert ISO string back to date object
    target_date = date.fromisoformat(data['target_date'])
    periods = data['periods']
    
    # Clear existing entries for this date
    deleted = await schedule_repo.clear_all_for_date(target_date, queue=config.QUEUE_NUMBER)
    
    # Create new entries
    for start, end in periods:
        await schedule_repo.create_entry(
            entry_date=target_date,
            queue=config.QUEUE_NUMBER,
            start_hour=start,
            end_hour=end,
            user_id=message.from_user.id
        )
    
    await state.clear()
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer(
        f"✅ <b>Графік збережено!</b>\n\n"
        f"📅 Дата: {target_date.strftime('%d.%m.%Y')}\n"
        f"📝 Додано блоків: {len(periods)}\n"
        f"🗑️ Видалено старих: {deleted}",
        reply_markup=get_schedule_menu_kb(is_admin=is_admin),
        parse_mode="HTML"
    )
    
    logging.info(f"User {message.from_user.id} saved schedule for {target_date}: {periods}")

@router.message(ScheduleStates.confirming, F.text == "❌ Скасувати")
async def cancel_schedule_confirm(message: Message, state: FSMContext, user_repo: UserRepository):
    """Cancel schedule entry at confirmation step"""
    await state.clear()
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer("❌ Скасовано", reply_markup=get_schedule_menu_kb(is_admin=is_admin))

@router.message(ScheduleStates.waiting_for_download_confirm, F.text == "❌ Скасувати")
async def cancel_download_confirm(message: Message, state: FSMContext, user_repo: UserRepository):
    """Cancel HOE download at confirmation step"""
    await state.clear()
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer("❌ Скасовано", reply_markup=get_schedule_menu_kb(is_admin=is_admin))
