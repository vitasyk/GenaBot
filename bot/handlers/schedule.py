"""Schedule management handlers"""
import logging
import re
from typing import List, Tuple, Optional
from datetime import datetime, date, timedelta
from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from bot.states import ScheduleStates
from bot.keyboards.schedule_kb import (
    get_schedule_menu_kb, 
    get_date_quick_kb, 
    get_confirm_kb, 
    get_hoe_selection_kb,
    get_clear_confirm_kb
)
from bot.keyboards.main_kb import get_main_keyboard
from bot.database.repositories.schedule import ScheduleRepository
from bot.database.repositories.user import UserRepository
from bot.services.schedule_parser import ScheduleParser

router = Router()
parser = ScheduleParser()

# Main Schedule Menu
@router.message(F.text == "📉 Графік")
async def schedule_menu(message: Message, user_repo: UserRepository):
    """Show schedule management submenu"""
    from bot.config import config
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
    from bot.config import config
    is_admin = message.from_user.id in config.ADMIN_IDS
    
    await message.answer(
        "🏠 Головне меню",
        reply_markup=get_main_keyboard(is_admin=is_admin)
    )

# Manual Entry Flow
@router.message(F.text == "✏️ Ввести вручну")
async def start_manual_entry(message: Message, state: FSMContext, user_repo: UserRepository):
    """Start manual schedule entry (admin only)"""
    from bot.config import config
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return
    
    await state.set_state(ScheduleStates.waiting_for_date)
    await message.answer(
        f"📅 <b>Введення графіку вручну</b>\n\n"
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
    
    from bot.config import config
    is_admin = message.from_user.id in config.ADMIN_IDS
    
    today = datetime.now().date()
    tomorrow = today + timedelta(days=1)
    
    # Get entries for today and tomorrow
    entries_today = await schedule_repo.get_entries_for_date(today, "1.1")
    entries_tomorrow = await schedule_repo.get_entries_for_date(tomorrow, "1.1")
    
    response = "📅 <b>Графік відключень (Черга 1.1)</b>\n\n"
    
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
    from bot.config import config
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return
    
    await state.clear()
    await message.answer(
        "❓ <b>Ви впевнені, що хочете очистити графік на сьогодні?</b>\n\n"
        "Це видалить всі ручні записи для черги 1.1 на поточну дату.",
        reply_markup=get_clear_confirm_kb(),
        parse_mode="HTML"
    )

@router.callback_query(F.data == "clear_confirm")
async def process_clear_confirm_callback(callback: CallbackQuery, schedule_repo: ScheduleRepository):
    """Execute schedule clearing after confirmation"""
    today = datetime.now().date()
    deleted = await schedule_repo.clear_all_for_date(today, "1.1")
    
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
    from bot.config import config
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
        "Надішліть скріншот офіційного графіку HOE (черга 1.1).\n"
        "Бот спробує автоматично визначити періоди відключень.",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )

@router.callback_query(F.data.in_({"hoe_today", "hoe_tomorrow"}))
async def process_hoe_download_callback(callback: CallbackQuery):
    """Handle HOE download selection"""
    target = callback.data
    today = datetime.now().date()
    target_date = today if target == "hoe_today" else today + timedelta(days=1)
    
    label = "сьогодні" if target == "hoe_today" else "завтра"
    
    await callback.answer() # Answer immediately to prevent Telegram timeout
    await callback.message.edit_text(f"🔍 <b>Шукаю графік на {label}...</b>", parse_mode="HTML")
    
    try:
        # Fetch data: returns List[(date, List[hours], bytes)]
        import asyncio
        results = await asyncio.wait_for(parser.get_schedules_data(queue="1.1"), timeout=30.0)
        
        # Filter for target date
        found = None
        for d_obj, hours, img_bytes in results:
            if d_obj.date() == target_date: # Using .date() since d_obj might be datetime
                found = (d_obj, img_bytes)
                break
        
        if found:
            d_obj, img_bytes = found
            photo = BufferedInputFile(img_bytes, filename=f"schedule_{d_obj.strftime('%Y-%m-%d')}.png")
            
            # Delete selection message
            await callback.message.delete()
            
            await callback.message.answer_photo(
                photo=photo,
                caption=f"🖼️ <b>Офіційний графік на {d_obj.strftime('%d.%m')}</b>\n"
                        f"Використовуйте 'Ввести вручну' для оновлення бота.",
                parse_mode="HTML"
            )
            logging.info(f"User {callback.from_user.id} viewed HOE image for {d_obj.date()}")
        else:
            await callback.message.edit_text(
                f"⚠️ <b>Графіку на {label} ({target_date.strftime('%d.%m')}) ще немає</b>\n\n"
                "На сайті HOE поки що не опубліковано відповідний графік.\n"
                "Спробуйте пізніше або введіть дані вручну.",
                parse_mode="HTML"
            )
            
    except asyncio.TimeoutError:
        logging.error("HOE download timed out (30s)")
        
        # Fallback to cache
        suffix = "today" if target == "hoe_today" else "tomorrow"
        cached_img = parser.get_cached_schedule(suffix=suffix)
        if cached_img:
            photo = BufferedInputFile(cached_img, filename=f"cached_schedule_{suffix}.png")
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=photo,
                caption=f"⚠️ <b>Сайт HOE недоступний (таймаут)</b>\n\n"
                        f"Показую <b>останній завантажений</b> графік на {label}.\n"
                        "<i>Він може бути неактуальним!</i>",
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(
                "⏳ <b>Сервер HOE занадто довго не відповідає</b>\n\n"
                "Спробуйте пізніше або завантажте графік вручну.",
                parse_mode="HTML"
            )
    except Exception as e:
        logging.error(f"HOE image fetch failed: {e}")
        
        # Fallback to cache
        suffix = "today" if target == "hoe_today" else "tomorrow"
        cached_img = parser.get_cached_schedule(suffix=suffix)
        if cached_img:
            photo = BufferedInputFile(cached_img, filename=f"cached_schedule_{suffix}.png")
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=photo,
                caption=f"❌ <b>Помилка завантаження</b>: {str(e)}\n\n"
                        f"Показую <b>останній завантажений</b> графік на {label}.",
                parse_mode="HTML"
            )
        else:
            await callback.message.edit_text(f"❌ <b>Помилка завантаження</b>: {str(e)}", parse_mode="HTML")

@router.message(ScheduleStates.waiting_for_screenshot, F.photo | F.document)
async def process_schedule_screenshot(message: Message, state: FSMContext, user_repo: UserRepository):
    """Process uploaded screenshot using ScheduleParser"""
    from bot.config import config
    is_admin = message.from_user.id in config.ADMIN_IDS
    # Get photo bytes
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type.startswith("image/"):
        file_id = message.document.file_id
    else:
        await message.answer("⚠️ Будь ласка, надішліть зображення (скріншот).")
        return

    await message.answer("🔍 <b>Аналізую зображення...</b>", parse_mode="HTML")
    
    try:
        file = await message.bot.get_file(file_id)
        from io import BytesIO
        file_io = BytesIO()
        await message.bot.download_file(file.file_path, file_io)
        img_bytes = file_io.getvalue()
        
        hours = parser.parse_image(img_bytes, queue="1.1")
        
        if not hours:
            await message.answer(
                "❌ <b>Не вдалося розпізнати графік</b>\n\n"
                "Переконайтеся, що на фото чітко видно таблицю HOE.\n"
                "Спробуйте надіслати інше фото або введіть дані вручну.",
                reply_markup=get_schedule_menu_kb(is_admin=is_admin),
                parse_mode="HTML"
            )
            await state.clear()
            return

        # Convert hours to ranges
        ranges = _hours_to_ranges(hours)
        await state.update_data(periods=ranges)
        
        # Now ask for date
        await state.set_state(ScheduleStates.waiting_for_date)
        await message.answer(
            f"✅ <b>Графік розпізнано!</b>\n\n"
            f"Виявлено періоди:\n" + "\n".join([f"• {s:02d}:00 - {e:02d}:00" for s, e in ranges]) + "\n\n"
            f"📅 <b>Для якого дня встановити цей графік?</b>",
            reply_markup=get_date_quick_kb(),
            parse_mode="HTML"
        )
        
    except Exception as e:
        logging.error(f"Manual photo parsing failed: {e}")
        await message.answer(f"❌ <b>Помилка аналізу</b>: {str(e)}", parse_mode="HTML")
        await state.clear()

# Manual Entry State Handlers (Must be AFTER specific button handlers)
@router.message(ScheduleStates.waiting_for_date)
async def process_date_input(message: Message, state: FSMContext, user_repo: UserRepository):
    """Process date input"""
    if not message.text:
        return
        
    logging.info(f"Schedule: process_date_input text='{message.text}' state={await state.get_state()}")
    
    if message.text == "🔙 Скасувати":
        await state.clear()
        from bot.config import config
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
        target_date = datetime.now().date()
    elif text_lower in ["завтра", "tomorrow"]:
        target_date = datetime.now().date() + timedelta(days=1)
    else:
        # Try parsing DD.MM or DD.MM.YY format
        match = re.match(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$", text_lower)
        if match:
            day, month = int(match.group(1)), int(match.group(2))
            year = datetime.now().year
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
    
    hours.sort()
    ranges = []
    if not hours: return ranges
    
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
        from bot.config import config
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
                raise ValueError(f"Години мають бути від 0 до 23 (кінець до 24)")
            
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
    
    # Save and confirm
    await state.update_data(periods=periods)
    data = await state.get_data()
    
    # Convert ISO string back to date object
    target_date = date.fromisoformat(data['target_date'])
    
    # Format confirmation message
    periods_text = "\n".join([f"• {s:02d}:00 - {e:02d}:00" for s, e in periods])
    
    await state.set_state(ScheduleStates.confirming)
    await message.answer(
        f"📋 <b>Підтвердження</b>\n\n"
        f"📅 Дата: <b>{target_date.strftime('%d.%m.%Y')}</b>\n"
        f"📋 Черга: <b>1.1</b>\n\n"
        f"⏰ Періоди відключень:\n{periods_text}\n\n"
        f"Всього блоків: {len(periods)}",
        reply_markup=get_confirm_kb(),
        parse_mode="HTML"
    )

@router.message(ScheduleStates.confirming, F.text == "✅ Підтвердити")
async def confirm_schedule(message: Message, state: FSMContext, schedule_repo: ScheduleRepository, user_repo: UserRepository):
    """Confirm and save schedule"""
    data = await state.get_data()
    
    # Convert ISO string back to date object
    target_date = date.fromisoformat(data['target_date'])
    periods = data['periods']
    
    # Clear existing entries for this date
    deleted = await schedule_repo.clear_all_for_date(target_date, queue="1.1")
    
    # Create new entries
    for start, end in periods:
        await schedule_repo.create_entry(
            entry_date=target_date,
            queue="1.1",
            start_hour=start,
            end_hour=end,
            user_id=message.from_user.id
        )
    
    await state.clear()
    from bot.config import config
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
    from bot.config import config
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer("❌ Скасовано", reply_markup=get_schedule_menu_kb(is_admin=is_admin))

@router.message(ScheduleStates.waiting_for_download_confirm, F.text == "❌ Скасувати")
async def cancel_download_confirm(message: Message, state: FSMContext, user_repo: UserRepository):
    """Cancel HOE download at confirmation step"""
    await state.clear()
    from bot.config import config
    is_admin = message.from_user.id in config.ADMIN_IDS
    await message.answer("❌ Скасовано", reply_markup=get_schedule_menu_kb(is_admin=is_admin))
