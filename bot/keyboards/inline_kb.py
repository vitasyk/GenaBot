from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_generator_control_kb(statuses: dict = None, exclude_correction: bool = False) -> InlineKeyboardMarkup:
    # Default to stopped if not provided
    s1 = statuses.get("GEN-1 (003)", "🔴") if statuses else "🔴"
    s2 = statuses.get("GEN-2 (036) WILSON", "🔴") if statuses else "🔴"
    
    buttons = [
        [
            InlineKeyboardButton(text="🟢 Старт GEN-1 (003)", callback_data="start_gen_1"),
            InlineKeyboardButton(text="🟡 Чергування GEN-1 (003)", callback_data="standby_gen_1")
        ],
        [
            InlineKeyboardButton(text="🟢 Старт GEN-2 (036) WILSON", callback_data="start_gen_2"),
            InlineKeyboardButton(text="🟡 Чергування GEN-2 (036) WILSON", callback_data="standby_gen_2")
        ]
    ]
    
    bottom_row = [InlineKeyboardButton(text="🛑 Зупинити всі", callback_data="stop_all_gens")]
    
    if not exclude_correction:
        bottom_row.append(InlineKeyboardButton(text="🔧 Корегування", callback_data="correct_fuel_menu"))
        
    buttons.append(bottom_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)
