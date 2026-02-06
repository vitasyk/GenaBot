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

def get_gen_selection_kb(selected_gens: list[str] = None, statuses: dict = None) -> InlineKeyboardMarkup:
    """
    Keyboard with toggle checkboxes for generator selection
    selected_gens: list of generator names currently selected
    statuses: {gen_name: status_emoji}
    """
    if selected_gens is None:
        selected_gens = []
    
    kb = []
    # Status icons default to stopped if missing
    s1 = statuses.get("GEN-1 (003)", "🔴") if statuses else "🔴"
    s2 = statuses.get("GEN-2 (036) WILSON", "🔴") if statuses else "🔴"

    gens = [
        (f"{s1} GEN-1 (003)", "GEN-1 (003)", ""),
        (f"{s2} GEN-2 (036) WILSON", "GEN-2 (036) WILSON", "")
    ]
    
    for display_name, internal_name, label in gens:
        is_selected = internal_name in selected_gens
        # Remove checkbox icons as requested by user
        text = f"{'✅ ' if is_selected else ''}{display_name}"
        kb.append([InlineKeyboardButton(
            text=text,
            callback_data=f"toggle_gen:{internal_name}"
        )])
    
    # Add "Continue" button only if at least one is selected
    if selected_gens:
        kb.append([InlineKeyboardButton(
            text="➡️ Продовжити",
            callback_data="gen_confirm"
        )])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_gen_choice_kb(statuses: dict = None) -> InlineKeyboardMarkup:
    """Keyboard for choosing generator (DEPRECATED - use get_gen_selection_kb)"""
    s1 = statuses.get("GEN-1 (003)", "🔴") if statuses else "🔴"
    s2 = statuses.get("GEN-2 (036) WILSON", "🔴") if statuses else "🔴"
    
    kb = [
        [InlineKeyboardButton(text=f"{s1} GEN-1 (003)", callback_data="gen_choice:GEN-1 (003)")],
        [InlineKeyboardButton(text=f"{s2} GEN-2 (036) WILSON", callback_data="gen_choice:GEN-2 (036) WILSON")],
        [InlineKeyboardButton(text="Обидва", callback_data="gen_choice:both")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_skip_kb() -> InlineKeyboardMarkup:
    """Keyboard to skip current step"""
    kb = [
        [InlineKeyboardButton(text="Пропустити", callback_data="skip_step")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_antigel_kb() -> InlineKeyboardMarkup:
    """Keyboard for Anti-Gel selection"""
    kb = [
        [
            InlineKeyboardButton(text="✅ Так", callback_data="antigel:yes"),
            InlineKeyboardButton(text="❌ Ні", callback_data="antigel:no")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)
