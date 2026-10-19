from datetime import timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import config
from bot.database.repositories.schedule import ScheduleRepository
from bot.database.repositories.user import UserRepository
from bot.keyboards.main_kb import get_main_keyboard
from bot.keyboards.schedule_kb import (
    get_clear_confirm_kb,
    get_date_quick_kb,
    get_hoe_selection_kb,
    get_schedule_menu_kb,
)
from bot.states import ScheduleStates
from bot.utils.clock import now_local

router = Router()

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
