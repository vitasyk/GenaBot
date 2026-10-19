import html
import logging
import re
from datetime import date, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import config
from bot.database.repositories.schedule import ScheduleRepository
from bot.database.repositories.user import UserRepository
from bot.handlers.schedule._common import _ask_save_confirmation
from bot.handlers.schedule.menu import back_to_main
from bot.keyboards.schedule_kb import get_date_quick_kb, get_schedule_menu_kb
from bot.states import ScheduleStates
from bot.utils.clock import now_local

router = Router()

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
    from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
    cancel_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🔙 Скасувати")]],
        resize_keyboard=True
    )
    
    await message.answer(
        f"📅 Дата: <b>{target_date.strftime('%d.%m.%Y')}</b>\n\n"
        "⏰ <b>Введіть періоди відключень</b>\n\n"
        "Формат: цілі години через тире (без хвилин), періоди через кому\n"
        "Приклад: <code>0-6, 11-15, 18-23</code>\n\n"
        "Це означає:\n"
        "• 00:00 - 06:00\n"
        "• 11:00 - 15:00\n"
        "• 18:00 - 23:00",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )

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
            # fullmatch: "18-19:30" must be rejected, not silently read as 18-19
            match = re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", part)
            if not match:
                raise ValueError(f"Невірний формат: {part}. Лише цілі години, без хвилин")
            
            start = int(match.group(1))
            end = int(match.group(2))
            
            if start < 0 or start > 23 or end < 0 or end > 24:
                raise ValueError("Години мають бути від 0 до 23 (кінець до 24)")
            
            if start >= end:
                raise ValueError(f"Початок має бути менше кінця: {start}-{end}")
            
            periods.append((start, end))
    
    except Exception as e:
        await message.answer(
            f"❌ Помилка в форматі: {html.escape(str(e))}\n\n"
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
