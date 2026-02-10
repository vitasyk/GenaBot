from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_inventory_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    if is_admin:
        builder.row(
            InlineKeyboardButton(text="➖ 1", callback_data="stock_dec_1"),
            InlineKeyboardButton(text="➕ 1", callback_data="stock_add_1"),
            InlineKeyboardButton(text="➕ 5", callback_data="stock_add_5")
        )
        builder.row(
            InlineKeyboardButton(text="📅 Корегувати дату", callback_data="stock_correct_date"),
            InlineKeyboardButton(text="📜 Історія", callback_data="stock_history")
        )
    
    builder.row(InlineKeyboardButton(text="❌ Закрити", callback_data="stock_close"))
    
    return builder.as_markup()
