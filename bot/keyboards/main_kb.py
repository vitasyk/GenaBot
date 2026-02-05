from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="⛽ Заправити"), KeyboardButton(text="📦 Склад")],
        [KeyboardButton(text="⚡ Статус"), KeyboardButton(text="🌡️ Прогноз"), KeyboardButton(text="📉 Графік")],
        [KeyboardButton(text="🆘 Інструкція (SOS)")]
    ]
    
    if is_admin:
        buttons.append([KeyboardButton(text="🔄 Керування"), KeyboardButton(text="📊 Адмін-панель")])
        
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
