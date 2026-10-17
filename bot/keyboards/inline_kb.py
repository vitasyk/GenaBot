from typing import Sequence

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.database.models import Generator
from bot.keyboards.callbacks import GenCallback

def get_generator_control_kb(generators: Sequence[Generator], exclude_correction: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=f"🟢 Старт {g.name}", callback_data=GenCallback(action="start", gen_id=g.id).pack()),
            InlineKeyboardButton(text=f"🟡 Чергування {g.name}", callback_data=GenCallback(action="standby", gen_id=g.id).pack())
        ]
        for g in generators
    ]

    bottom_row = [InlineKeyboardButton(text="🛑 Зупинити всі", callback_data="stop_all_gens")]

    if not exclude_correction:
        bottom_row.append(InlineKeyboardButton(text="🔧 Корегування", callback_data="correct_fuel_menu"))

    buttons.append(bottom_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_generator_select_kb(generators: Sequence[Generator], action: str,
                            back_text: str, back_callback: str) -> InlineKeyboardMarkup:
    """One button per generator (GenCallback with the given action) plus a back row."""
    rows = [
        [InlineKeyboardButton(text=g.name, callback_data=GenCallback(action=action, gen_id=g.id).pack())]
        for g in generators
    ]
    rows.append([InlineKeyboardButton(text=back_text, callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
