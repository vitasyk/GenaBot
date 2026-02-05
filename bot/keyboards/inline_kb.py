from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_generator_control_kb(exclude_correction: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🟢 Старт GEN-1", callback_data="start_gen_1"),
            InlineKeyboardButton(text="🟡 Чергування GEN-1", callback_data="standby_gen_1")
        ],
        [
            InlineKeyboardButton(text="🟢 Старт GEN-2", callback_data="start_gen_2"),
            InlineKeyboardButton(text="🟡 Чергування GEN-2", callback_data="standby_gen_2")
        ]
    ]
    
    bottom_row = [InlineKeyboardButton(text="🛑 Зупинити всі", callback_data="stop_all_gens")]
    
    if not exclude_correction:
        bottom_row.append(InlineKeyboardButton(text="🔧 Корегування", callback_data="correct_fuel_menu"))
        
    buttons.append(bottom_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)
