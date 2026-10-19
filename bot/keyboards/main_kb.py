from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

_ROWS = [
    ["⛽ Заправити", "📦 Склад"],
    ["⚡ Статус", "🌡️ Прогноз", "📉 Графік"],
    ["🆘 Інструкція (SOS)", "🔄 Керування"],
]
_ADMIN_ROW = ["📊 Адмін-панель"]

# Texts of the reply-keyboard buttons: text-input steps treat them as "cancel".
MENU_BUTTONS = frozenset(text for row in [*_ROWS, _ADMIN_ROW] for text in row)


def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [*_ROWS, _ADMIN_ROW] if is_admin else _ROWS
    buttons = [[KeyboardButton(text=text) for text in row] for row in rows]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
