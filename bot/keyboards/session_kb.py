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

def get_gen_selection_kb(selected_gens: list[str] = None) -> InlineKeyboardMarkup:
    """
    Keyboard with toggle checkboxes for generator selection
    selected_gens: list of generator names currently selected
    """
    if selected_gens is None:
        selected_gens = []
    
    kb = []
    gens = [
        ("GEN-1 (003)", "Великий"),
        ("GEN-2 (036) WILSON", "Малий")
    ]
    
    for gen_name, label in gens:
        is_selected = gen_name in selected_gens
        check = "✅" if is_selected else "☐"
        text = f"{check} {gen_name} ({label})"
        kb.append([InlineKeyboardButton(
            text=text,
            callback_data=f"toggle_gen:{gen_name}"
        )])
    
    # Add "Continue" button only if at least one is selected
    if selected_gens:
        kb.append([InlineKeyboardButton(
            text="➡️ Продовжити",
            callback_data="gen_confirm"
        )])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_gen_choice_kb() -> InlineKeyboardMarkup:
    """Keyboard for choosing generator (DEPRECATED - use get_gen_selection_kb)"""
    # TODO: Fetch dynamic generator names from DB if possible?
    # For now hardcode common names or use generic
    kb = [
        [InlineKeyboardButton(text="GEN-1 (003) (Великий)", callback_data="gen_choice:GEN-1 (003)")],
        [InlineKeyboardButton(text="GEN-2 (036) WILSON (Малий)", callback_data="gen_choice:GEN-2 (036) WILSON")],
        [InlineKeyboardButton(text="Обидва", callback_data="gen_choice:both")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_skip_kb() -> InlineKeyboardMarkup:
    """Keyboard to skip current step"""
    kb = [
        [InlineKeyboardButton(text="Пропустити", callback_data="skip_step")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
