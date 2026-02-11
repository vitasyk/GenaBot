from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_refuel_kb(statuses: dict = None) -> InlineKeyboardMarkup:
    s1 = statuses.get("GEN-1 (036)", "🔴") if statuses else "🔴"
    s2 = statuses.get("GEN-2 (003) WILSON", "🔴") if statuses else "🔴"
    
    buttons = [
        [
            InlineKeyboardButton(text=f"{s1} GEN-1 (036)", callback_data="refuel_select_GEN-1 (036)"),
            InlineKeyboardButton(text=f"{s2} GEN-2 (003) WILSON", callback_data="refuel_select_GEN-2 (003) WILSON")
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

def get_refuel_accumulator_kb(gen_name: str, total_liters: float) -> InlineKeyboardMarkup:
    """Accumulator-style keyboard with increment buttons"""
    buttons = [
        [
            InlineKeyboardButton(text="+20л", callback_data=f"refuel_add_20"),
            InlineKeyboardButton(text="+10л", callback_data=f"refuel_add_10"),
            InlineKeyboardButton(text="+5л", callback_data=f"refuel_add_5")
        ],
        [
            InlineKeyboardButton(text="↩️ Скасувати", callback_data="refuel_acc_cancel"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"refuel_acc_done_{gen_name}")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="fuel_back")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
