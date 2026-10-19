import html
from datetime import date
from typing import List, Tuple

from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import config
from bot.keyboards.schedule_kb import get_confirm_kb
from bot.states import ScheduleStates


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
