"""Keyboards for schedule management"""
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


class QueuePageCb(CallbackData, prefix="qst"):
    """Page of the "streets of a queue" list: the query is repeated so pages need no stored state."""
    queue: str
    place: str
    page: int


def get_queue_pages_kb(queue: str, place: str, page: int, total: int) -> InlineKeyboardMarkup | None:
    """◀️ 2/5 ▶️ under a paged list; None when everything fits on one page."""
    if total <= 1:
        return None
    buttons = []
    if page > 0:
        buttons.append(InlineKeyboardButton(text="◀️", callback_data=QueuePageCb(queue=queue, place=place, page=page - 1).pack()))
    buttons.append(InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="qst_noop"))
    if page < total - 1:
        buttons.append(InlineKeyboardButton(text="▶️", callback_data=QueuePageCb(queue=queue, place=place, page=page + 1).pack()))
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


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
