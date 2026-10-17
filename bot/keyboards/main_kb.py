from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

ADMIN_PANEL_TEXT = "📊 Адмін-панель"

# Every reply-keyboard button; text input steps treat these as "cancel"
MAIN_MENU_TEXTS = {
    "⛽ Заправити", "📦 Склад", "⚡ Статус", "🌡️ Прогноз", "📉 Графік",
    "🔄 Керування", "🆘 Інструкція (SOS)", ADMIN_PANEL_TEXT,
}

def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="⛽ Заправити"), KeyboardButton(text="📦 Склад")],
        [KeyboardButton(text="⚡ Статус"), KeyboardButton(text="🌡️ Прогноз"), KeyboardButton(text="📉 Графік")],
        [KeyboardButton(text="🔄 Керування"), KeyboardButton(text="🆘 Інструкція (SOS)")]
    ]

    if is_admin:
        buttons.append([KeyboardButton(text=ADMIN_PANEL_TEXT)])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
