import html
import logging

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.config import config
from bot.database.models import UserRole
from bot.database.repositories.logs import LogRepository
from bot.database.repositories.user import UserRepository
from bot.handlers.admin._common import _get_admin_panel_kb
from bot.scheduler import save_runtime_setting
from bot.states import AdminStates

logger = logging.getLogger(__name__)

router = Router()

@router.message(F.text == "📊 Адмін-панель")
async def admin_panel_handler(message: types.Message, user_repo: UserRepository):
    user = await user_repo.get_by_id(message.from_user.id)
    if not user or user.role != UserRole.admin:
        return

    text = "📊 <b>Адмін-панель</b>\n\n"
    text += f"🔐 <b>Режим доступу:</b> {'🔒 Обмежений (Whitelist)' if config.RESTRICT_ACCESS else '🌍 Публічний'}\n"
    text += f"📢 <b>Сповіщення:</b> {'👥 Всім працівникам' if config.NOTIFY_WORKERS else '👮 Тільки адмінам'}\n"
    text += f"👥 <b>Білий список:</b> {len(config.ALLOWED_IDS)} ID\n"
    text += f"👑 <b>Адміни:</b> {len(config.ADMIN_IDS)} ID\n"
    
    await message.answer(text, reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_force_schedule")
async def force_schedule_check(callback: types.CallbackQuery, bot: Bot):
    await callback.message.edit_text("⏳ <b>Перевірка графіку...</b>\nЦе може зайняти кілька секунд.", parse_mode="HTML")
    
    from bot.database.main import session_maker
    from bot.services.session_service import SessionService
    
    try:
        async with session_maker() as session:
            service = SessionService(session, bot=bot)
            new_session = await service.check_power_outage()
            
            if new_session:
                await callback.message.edit_text(f"✅ <b>Успішно!</b>\nСтворено нову сесію (ID: {new_session.id})\nДедлайн: {new_session.deadline.strftime('%H:%M')}", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
            else:
                await callback.message.edit_text("ℹ️ <b>Результат:</b>\nВідключень не виявлено (або сесія вже існує).", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
    except Exception as e:
        logger.exception("Manual outage check failed: user_id=%s", callback.from_user.id)
        safe_error = html.escape(str(e))
        await callback.message.edit_text(f"❌ <b>Помилка:</b>\n{safe_error}", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_set_interval")
async def set_interval_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("⚙️ <b>Налаштування інтервалу</b>\n\nВведіть інтервал перевірки графіку в хвилинах (наприклад: 15).", parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_check_interval)
    await callback.answer()

@router.message(AdminStates.waiting_for_check_interval)
async def interval_input(message: types.Message, state: FSMContext):
    try:
        minutes = int(message.text.strip())
        if minutes < 1: raise ValueError
        
        redis = state.storage.redis
        await redis.set("config:schedule_interval", minutes)
        
        from bot.scheduler import scheduler
        scheduler.reschedule_job('check_power_outage_job', trigger='interval', minutes=minutes)
        
        await message.answer(f"✅ Інтервал змінено на <b>{minutes} хв</b>.", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
        await state.clear()

    except (ValueError, AttributeError):  # not a positive integer, or no text in the message
        await message.answer("⚠️ Введіть ціле число хвилин (від 1).", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_toggle_access")
async def toggle_access_callback(callback: types.CallbackQuery, state: FSMContext):
    config.RESTRICT_ACCESS = not config.RESTRICT_ACCESS
    await save_runtime_setting(state.storage.redis, "RESTRICT_ACCESS", config.RESTRICT_ACCESS)
    await admin_panel_back(callback)
    await callback.answer(f"✅ Режим змінено на: {'Обмежений' if config.RESTRICT_ACCESS else 'Публічний'}")

@router.callback_query(F.data == "admin_toggle_notify")
async def toggle_notify_callback(callback: types.CallbackQuery, state: FSMContext):
    config.NOTIFY_WORKERS = not config.NOTIFY_WORKERS
    await save_runtime_setting(state.storage.redis, "NOTIFY_WORKERS", config.NOTIFY_WORKERS)
    await admin_panel_back(callback)
    await callback.answer(f"✅ Отримувачі: {'Всі працівники' if config.NOTIFY_WORKERS else 'Тільки адміни'}")

@router.callback_query(F.data == "admin_confirm_reset_logs")
async def confirm_reset_logs(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗑️ ТАК, СКИНУТИ", callback_data="admin_do_reset_logs"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    await callback.message.edit_text("⚠️ <b>УВАГА!</b>\n\nЦе видалить всю історію заправок.\nВи впевнені?", reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "admin_panel_back")
async def admin_panel_back(callback: types.CallbackQuery):
    text = "📊 <b>Адмін-панель</b>\n\n"
    text += f"🔐 <b>Режим доступу:</b> {'🔒 Обмежений (Whitelist)' if config.RESTRICT_ACCESS else '🌍 Публічний'}\n"
    text += f"📢 <b>Сповіщення:</b> {'👥 Всім працівникам' if config.NOTIFY_WORKERS else '👮 Тільки адмінам'}\n"
    text += f"👥 <b>Білий список:</b> {len(config.ALLOWED_IDS)} ID\n"
    text += f"👑 <b>Адміни:</b> {len(config.ADMIN_IDS)} ID\n"
    try:
        await callback.message.edit_text(text, reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer("Панель оновлена")
        else:
            raise

@router.callback_query(F.data == "admin_do_reset_logs")
async def do_reset_logs(callback: types.CallbackQuery, log_repo: LogRepository):
    await log_repo.clear_all()
    await callback.answer("✅ Історію успішно скинуто!", show_alert=True)
    await admin_panel_back(callback)

@router.callback_query(F.data == "admin_close")
async def admin_close_callback(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except (TelegramAPIError, AttributeError):  # AttributeError: InaccessibleMessage has no delete()
        logger.debug("Admin panel close: message not deleted", exc_info=True)
        
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass

@router.callback_query(F.data == "admin_view_logs")
async def admin_view_logs(callback: types.CallbackQuery, log_repo: LogRepository, user_repo: UserRepository):
    import zoneinfo

    from bot.config import config
    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    
    logs = await log_repo.get_recent_logs(limit=20)
    users = await user_repo.get_all(include_blocked=True)
    user_map = {u.id: (u.sheet_name or u.name or str(u.id)) for u in users}
    
    if not logs:
        await callback.answer("📜 Журнал порожній")
        return

    text = "📜 <b>Останні події</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    
    for log in logs:
        user_name = user_map.get(log.user_id, f"ID:{log.user_id}")
        local_time = log.timestamp.replace(tzinfo=zoneinfo.ZoneInfo("UTC")).astimezone(tz)
        time_str = local_time.strftime("%H:%M")
        
        # Clean up action text if it's too technical
        action = log.action.replace("inventory_", "").replace("refuel_", "")
        
        line = f"🕒 <code>{time_str}</code> | 👤 <b>{user_name}</b> | {action}"
        if log.details:
            line += f" (<i>{log.details}</i>)"
        
        if len(text + line + "\n") > 4000: # Stay safe within message length
            break
        text += line + "\n"
    
    text += "➖➖➖➖➖➖➖➖➖➖"
    
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()
