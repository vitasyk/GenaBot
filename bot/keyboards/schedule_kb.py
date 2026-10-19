"""Keyboards for schedule management"""
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def get_hoe_selection_kb() -> InlineKeyboardMarkup:
    """Inline keyboard for HOE download selection"""
    buttons = [
        [
            InlineKeyboardButton(text="Сьогодні", callback_data="hoe_today"),
            InlineKeyboardButton(text="Завтра", callback_data="hoe_tomorrow")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_clear_confirm_kb() -> InlineKeyboardMarkup:
    """Inline keyboard for clear schedule confirmation"""
    buttons = [
        [
            InlineKeyboardButton(text="🗑️ Так, очистити", callback_data="clear_confirm"),
            InlineKeyboardButton(text="❌ Скасувати", callback_data="clear_cancel")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_schedule_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Schedule management submenu"""
    keyboard = []
    
    # Admin-only buttons
    if is_admin:
        keyboard.append([KeyboardButton(text="✏️ Ввести вручну"), KeyboardButton(text="📸 Розпізнати з фото")])
        keyboard.append([KeyboardButton(text="🗑️ Очистити графік"), KeyboardButton(text="🔢 Черга")])
    
    # Public buttons (available to all)
    keyboard.append([KeyboardButton(text="📋 Переглянути графік"), KeyboardButton(text="🌐 Завантажити з HOE")])
    keyboard.append([KeyboardButton(text="🏠 Черга за адресою"), KeyboardButton(text="📋 Вулиці черги")])
    keyboard.append([KeyboardButton(text="🔙 Головне меню")])
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_queue_kb(queues: list[str], current: str) -> InlineKeyboardMarkup:
    """Queue choice, 4 per row, current one marked"""
    buttons = [
        InlineKeyboardButton(text=f"✅ {q}" if q == current else q, callback_data=f"queue_set:{q}")
        for q in queues
    ]
    rows = [buttons[i:i + 4] for i in range(0, len(buttons), 4)]
    rows.append([InlineKeyboardButton(text="✍️ Ввести іншу", callback_data="queue_custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_date_quick_kb() -> ReplyKeyboardMarkup:
    """Quick date selection"""
    keyboard = [
        [KeyboardButton(text="Сьогодні"), KeyboardButton(text="Завтра")],
        [KeyboardButton(text="🔙 Скасувати")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_confirm_kb() -> ReplyKeyboardMarkup:
    """Confirmation keyboard"""
    keyboard = [
        [KeyboardButton(text="✅ Підтвердити"), KeyboardButton(text="❌ Скасувати")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)
