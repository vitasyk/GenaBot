from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_refuel_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="GEN-1 (003)", callback_data="refuel_select_GEN-1 (003)"),
            InlineKeyboardButton(text="GEN-2 (038)", callback_data="refuel_select_GEN-2 (038)")
        ],
        [InlineKeyboardButton(text="❌ Закрити", callback_data="refuel_close")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_amount_kb(gen_name: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="Повна (20л)", callback_data=f"refuel_confirm_{gen_name}_20"),
            InlineKeyboardButton(text="Половина (10л)", callback_data=f"refuel_confirm_{gen_name}_10")
        ],
        [
            InlineKeyboardButton(text="5L", callback_data=f"refuel_confirm_{gen_name}_5"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="fuel_back")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
