from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_start_session_kb(session_id: int) -> InlineKeyboardMarkup:
    """Keyboard for 'Start Refueling' notification"""
    kb = [
        [InlineKeyboardButton(text="🔄 Почати заправку", callback_data=f"session_start:{session_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_in_progress_kb(session_id: int) -> InlineKeyboardMarkup:
    """Keyboard for active session message"""
    kb = [
        [InlineKeyboardButton(text="✅ Завершити сесію", callback_data=f"session_complete:{session_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_gen_choice_kb() -> InlineKeyboardMarkup:
    """Keyboard for choosing generator"""
    # TODO: Fetch dynamic generator names from DB if possible?
    # For now hardcode common names or use generic
    kb = [
        [InlineKeyboardButton(text="GEN-003 (Великий)", callback_data="gen_choice:GEN-003")],
        [InlineKeyboardButton(text="GEN-038 (Малий)", callback_data="gen_choice:GEN-038")],
        [InlineKeyboardButton(text="Обидва", callback_data="gen_choice:both")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_skip_kb() -> InlineKeyboardMarkup:
    """Keyboard to skip current step"""
    kb = [
        [InlineKeyboardButton(text="Пропустити", callback_data="skip_step")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
