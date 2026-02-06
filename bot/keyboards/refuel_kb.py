from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_refuel_kb(statuses: dict = None) -> InlineKeyboardMarkup:
    s1 = statuses.get("GEN-1 (003)", "🔴") if statuses else "🔴"
    s2 = statuses.get("GEN-2 (036) WILSON", "🔴") if statuses else "🔴"
    
    buttons = [
        [
            InlineKeyboardButton(text=f"{s1} GEN-1 (003)", callback_data="refuel_select_GEN-1 (003)"),
            InlineKeyboardButton(text=f"{s2} GEN-2 (036) WILSON", callback_data="refuel_select_GEN-2 (036) WILSON")
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
