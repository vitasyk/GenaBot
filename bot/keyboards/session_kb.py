from typing import Sequence

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.database.models import Generator
from bot.keyboards.callbacks import ALL_GENERATORS_ID, GenCallback

def get_start_session_kb(session_id: int) -> InlineKeyboardMarkup:
    """Keyboard for 'Start Refueling' notification"""
    kb = [
        [InlineKeyboardButton(text="🔄 Почати заправку", callback_data=f"session_start:{session_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_in_progress_kb(session_id: int) -> InlineKeyboardMarkup:
    """Keyboard for active session message"""
    kb = [
        [InlineKeyboardButton(text="✅ Завершити сесію", callback_data=f"session_complete:{session_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_gen_choice_kb(generators: Sequence[Generator]) -> InlineKeyboardMarkup:
    """Keyboard for choosing which generator was refueled"""
    kb = [
        [InlineKeyboardButton(text=g.name, callback_data=GenCallback(action="session", gen_id=g.id).pack())]
        for g in generators
    ]
    if len(generators) > 1:
        kb.append([InlineKeyboardButton(
            text="Усі",
            callback_data=GenCallback(action="session", gen_id=ALL_GENERATORS_ID).pack()
        )])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_skip_kb() -> InlineKeyboardMarkup:
    """Keyboard to skip current step"""
    kb = [
        [InlineKeyboardButton(text="Пропустити", callback_data="skip_step")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
