from typing import Sequence

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.database.models import Generator
from bot.keyboards.callbacks import RefuelAmountCallback
from bot.keyboards.inline_kb import get_generator_select_kb

def get_refuel_kb(generators: Sequence[Generator]) -> InlineKeyboardMarkup:
    return get_generator_select_kb(generators, "refuel", "❌ Закрити", "refuel_close")

def get_amount_kb(gen_id: int) -> InlineKeyboardMarkup:
    def amount_button(text: str, liters: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=RefuelAmountCallback(gen_id=gen_id, liters=liters).pack())

    buttons = [
        [amount_button("Повна (20л)", 20), amount_button("Половина (10л)", 10)],
        [amount_button("5L", 5), InlineKeyboardButton(text="🔙 Назад", callback_data="fuel_back")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
