import html

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.config import config
from bot.scheduler import save_runtime_setting
from bot.services.slack import SlackService
from bot.states import SlackStates

router = Router()

# --- Slack Management Handlers ---

def _get_slack_kb():
    """Keyboard for Slack configuration menu"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📊 Поріг палива", callback_data="slack_set_threshold"))
    builder.row(InlineKeyboardButton(text="✉️ Надіслати повідомлення", callback_data="slack_send_custom"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    return builder.as_markup()

@router.callback_query(F.data == "admin_slack_menu")
async def admin_slack_menu(callback: types.CallbackQuery):
    """Show Slack configuration options"""
    current_threshold = config.FUEL_THRESHOLD_CANS
    webhook_status = "✅ Налаштовано" if config.SLACK_WEBHOOK_URL else "❌ Не налаштовано"
    
    text = (
        "⚙️ <b>Slack Налаштування</b>\n\n"
        f"🔗 Webhook: {webhook_status}\n"
        f"📊 Поріг палива: <b>{current_threshold}</b> каністр\n\n"
        "Оберіть дію:"
    )
    
    await callback.message.edit_text(text, reply_markup=_get_slack_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "slack_set_threshold")
async def slack_set_threshold(callback: types.CallbackQuery, state: FSMContext):
    """Prompt for new threshold value"""
    await state.set_state(SlackStates.waiting_for_threshold)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_slack_menu"))
    
    await callback.message.edit_text(
        "📊 <b>Налаштування порогу палива</b>\n\n"
        f"Поточний поріг: <b>{config.FUEL_THRESHOLD_CANS}</b> каністр\n\n"
        "Введіть нове значення (наприклад: 3.5):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(SlackStates.waiting_for_threshold)
async def slack_threshold_input(message: types.Message, state: FSMContext):
    """Process threshold input"""
    try:
        new_threshold = float(message.text.strip().replace(",", "."))
        
        if new_threshold < 0 or new_threshold > 100:
            await message.answer("⚠️ Введіть значення від 0 до 100 каністр.")
            return
        
        config.FUEL_THRESHOLD_CANS = new_threshold
        await save_runtime_setting(state.storage.redis, "FUEL_THRESHOLD_CANS", new_threshold)

        await state.clear()
        await message.answer(
            f"✅ <b>Поріг оновлено!</b>\n\n"
            f"Новий поріг: <b>{new_threshold}</b> каністр",
            reply_markup=_get_slack_kb(),
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("⚠️ Введіть коректне число (наприклад: 2.5)")

@router.callback_query(F.data == "slack_send_custom")
async def slack_send_custom(callback: types.CallbackQuery, state: FSMContext):
    """Prompt for custom message"""
    if not config.SLACK_WEBHOOK_URL:
        await callback.answer("❌ Slack Webhook не налаштовано у .env", show_alert=True)
        return
    
    await state.set_state(SlackStates.waiting_for_message)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_slack_menu"))
    
    await callback.message.edit_text(
        "✉️ <b>Надіслати повідомлення в Slack</b>\n\n"
        "Введіть текст повідомлення:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(SlackStates.waiting_for_message)
async def slack_message_input(message: types.Message, state: FSMContext):
    """Send custom message to Slack"""
    text = message.text.strip()
    
    if not text:
        await message.answer("⚠️ Повідомлення не може бути порожнім.")
        return
    
    slack_service = SlackService(config.SLACK_WEBHOOK_URL)
    await slack_service.send_message(text)
    
    await state.clear()
    await message.answer(
        f"✅ <b>Повідомлення надіслано!</b>\n\n"
        f"Текст: <i>{html.escape(text)}</i>",
        reply_markup=_get_slack_kb(),
        parse_mode="HTML"
    )
