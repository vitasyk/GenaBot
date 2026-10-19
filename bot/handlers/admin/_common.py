from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.config import config


def _get_admin_panel_kb():
    builder = InlineKeyboardBuilder()
    
    # Row 1: Toggles
    access_text = "🔐 Доступ: ON" if config.RESTRICT_ACCESS else "🔓 Доступ: OFF"
    notify_text = "📢 Сповіщ: ADMIN" if not config.NOTIFY_WORKERS else "📢 Сповіщ: ALL"
    
    builder.add(InlineKeyboardButton(text=access_text, callback_data="admin_toggle_access"))
    builder.add(InlineKeyboardButton(text=notify_text, callback_data="admin_toggle_notify"))
    
    # Row 2: Management
    builder.add(InlineKeyboardButton(text="⛽ Сесії", callback_data="admin_sessions"))
    builder.add(InlineKeyboardButton(text="👥 Юзери", callback_data="admin_users"))
    builder.add(InlineKeyboardButton(text="📋 Працівники", callback_data="admin_sheets_workers"))
    builder.add(InlineKeyboardButton(text="👷 Воркери", callback_data="admin_next_workers"))
    
    # Row 3: Schedule
    builder.add(InlineKeyboardButton(text="🔄 Оновити", callback_data="admin_force_schedule"))
    builder.add(InlineKeyboardButton(text="⏱️ Інтервал", callback_data="admin_set_interval"))
    
    # Rows 4-5: System & Slack
    builder.add(InlineKeyboardButton(text="⚙️ Slack", callback_data="admin_slack_menu"))
    builder.add(InlineKeyboardButton(text="⚙️ Генератори", callback_data="admin_generators"))
    builder.add(InlineKeyboardButton(text="📜 Журнал подій", callback_data="admin_view_logs"))
    builder.add(InlineKeyboardButton(text="🧹 Скинути історію", callback_data="admin_confirm_reset_logs"))
    builder.add(InlineKeyboardButton(text="❌ Закрити", callback_data="admin_close"))
    
    builder.adjust(2, 4, 2, 2, 2, 1)
    return builder.as_markup()
