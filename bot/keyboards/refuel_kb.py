from collections.abc import Sequence

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.database.models import Generator
from bot.keyboards.inline_kb import get_generator_pick_kb


def get_refuel_kb(gens: Sequence[Generator]) -> InlineKeyboardMarkup:
    close = InlineKeyboardButton(text="❌ Закрити", callback_data="refuel_close")
    return get_generator_pick_kb(gens, "refuel", footer=close, with_status=True)


def get_refuel_accumulator_kb() -> InlineKeyboardMarkup:
    """Accumulator-style keyboard with increment buttons"""
    buttons = [
        [
            InlineKeyboardButton(text="+20л", callback_data="refuel_add_20"),
            InlineKeyboardButton(text="+10л", callback_data="refuel_add_10"),
            InlineKeyboardButton(text="+5л", callback_data="refuel_add_5")
        ],
        [
            InlineKeyboardButton(text="↩️ Скасувати", callback_data="refuel_acc_cancel"),
            InlineKeyboardButton(text="✅ Готово", callback_data="refuel_acc_done")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="fuel_back")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
