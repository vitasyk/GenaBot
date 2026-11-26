from collections.abc import Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.database.models import Generator
from bot.keyboards.inline_kb import GenCb, get_start_generator_kb, status_icon


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

def get_gen_selection_kb(gens: Sequence[Generator], selected_gens: list[str]) -> InlineKeyboardMarkup:
    """
    Toggle keyboard for choosing refuelled generators.
    gens: active generators; selected_gens: names already chosen (kept in FSM by name).
    """
    kb = [
        [InlineKeyboardButton(
            text=f"{'✅ ' if g.name in selected_gens else ''}{status_icon(g.status)} {g.name}",
            callback_data=GenCb(action="toggle", id=g.id).pack()
        )]
        for g in gens
    ]
    
    # Add "Continue" button only if at least one is selected
    if selected_gens:
        kb.append([InlineKeyboardButton(
            text="➡️ Продовжити",
            callback_data="gen_confirm"
        )])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_skip_kb() -> InlineKeyboardMarkup:
    """Keyboard to skip current step"""
    kb = [
        [InlineKeyboardButton(text="Пропустити", callback_data="skip_step")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_antigel_kb() -> InlineKeyboardMarkup:
    """Keyboard for Anti-Gel selection"""
    kb = [
        [
            InlineKeyboardButton(text="✅ Так", callback_data="antigel:yes"),
            InlineKeyboardButton(text="❌ Ні", callback_data="antigel:no")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


class OutageAnswerCb(CallbackData, prefix="outage"):
    """Answer to the outage warning. block: block start as YYYYMMDDHH (naive Kyiv time)."""
    power: bool  # True = power is on, the outage did not happen
    block: int


def get_outage_warning_kb(gens: Sequence[Generator], block: int) -> InlineKeyboardMarkup:
    """Outage warning: 'generator started' buttons plus 'is the power off?' yes/no row (kept last)."""
    rows = get_start_generator_kb(gens).inline_keyboard
    rows.append([
        InlineKeyboardButton(text="✅ Так, світла немає", callback_data=OutageAnswerCb(power=False, block=block).pack()),
        InlineKeyboardButton(text="❌ Ні, світло є", callback_data=OutageAnswerCb(power=True, block=block).pack()),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
