import html
from datetime import date

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import config
from bot.keyboards.schedule_kb import get_confirm_kb
from bot.services.hoe_schedule import format_ranges as _format_ranges
from bot.states import ScheduleStates


async def _ask_save_confirmation(message: Message, state: FSMContext, target_date: date, periods: list[tuple[int, int]]):
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
