"""Keyboards for schedule management"""
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

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

def get_schedule_menu_kb() -> ReplyKeyboardMarkup:
    """Schedule management submenu"""
    keyboard = [
        [KeyboardButton(text="✏️ Ввести вручну"), KeyboardButton(text="🌐 Завантажити з HOE")],
        [KeyboardButton(text="📸 Розпізнати з фото"), KeyboardButton(text="📋 Переглянути графік")],
        [KeyboardButton(text="🗑️ Очистити графік"), KeyboardButton(text="🔙 Головне меню")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

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
