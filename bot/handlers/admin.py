from aiogram import Router, F, types, Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import html
import logging

from bot.database.models import UserRole
from bot.database.repositories.user import UserRepository
from bot.database.repositories.logs import LogRepository
from bot.config import config
from bot.states import AdminStates

router = Router()

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
    
    # Row 3: Schedule
    builder.add(InlineKeyboardButton(text="🔄 Оновити", callback_data="admin_force_schedule"))
    builder.add(InlineKeyboardButton(text="⏱️ Інтервал", callback_data="admin_set_interval"))
    
    # Rows 4-5: System
    builder.add(InlineKeyboardButton(text="🧹 Скинути історію", callback_data="admin_confirm_reset_logs"))
    builder.add(InlineKeyboardButton(text="❌ Закрити", callback_data="admin_close"))
    
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()

# --- Session Management Handlers ---

@router.callback_query(F.data == "admin_sessions")
async def admin_sessions_list(callback: types.CallbackQuery, bot: Bot):
    from bot.database.main import session_maker
    from bot.database.repositories.session import SessionRepository
    from bot.database.repositories.user import UserRepository
    
    async with session_maker() as session:
        repo = SessionRepository(session)
        user_repo = UserRepository(session)
        history = await repo.get_history(limit=8) # 8 latest
        all_users = await user_repo.get_all(include_blocked=True)
        # Prefer sheet_name (Google Sheets name), fallback to Telegram name
        user_map = {u.id: (u.sheet_name if u.sheet_name else (u.name if u.name else str(u.id))) for u in all_users}
        
    text = "⛽ <b>Сесії заправки (v2.3)</b>\n\nОберіть сесію для перегляду деталей або скасування:"
    builder = InlineKeyboardBuilder()
    
    if not history:
        text = "⛽ <b>Сесії заправки</b>\n\nСесій ще не було."
    else:
        for s in history:
            # Explicitly define status icon
            status_map = {
                'pending': "⏳",
                'in_progress': "⚙️",
                'completed': "✅",
                'cancelled': "❌"
            }
            icon = status_map.get(s.status, "❓")
            
            # Resolve worker names
            w1 = user_map.get(s.worker1_id, "—") if s.worker1_id else "—"
            w2 = user_map.get(s.worker2_id, "—") if s.worker2_id else "—"
            
            if w1 == "—" and w2 == "—":
                workers_str = "немає воркерів"
            else:
                workers_str = f"{w1}, {w2}"
            
            # Button for each session
            builder.row(InlineKeyboardButton(
                text=f"{icon} {s.start_time.strftime('%d.%m %H:%M')} | {workers_str}",
                callback_data=f"admin_session_view:{s.id}"
            ))

    builder.row(
        InlineKeyboardButton(text="➕ Створити вручну", callback_data="admin_create_session_manual"),
        InlineKeyboardButton(text="🗑️ Видалити скасовані", callback_data="admin_delete_cancelled_sessions")
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

async def _admin_session_view_logic(callback: types.CallbackQuery, bot: Bot, session_id: int):
    from bot.database.main import session_maker
    from bot.database.repositories.session import SessionRepository
    from bot.database.repositories.user import UserRepository
    
    async with session_maker() as session:
        repo = SessionRepository(session)
        user_repo = UserRepository(session)
        s = await repo.get_session_by_id(session_id)
        
        if not s:
            await callback.answer("Сесію не знайдено")
            return
# Get worker names within the SAME session
        w1_name = "—"
        if s.worker1_id:
            u1 = await user_repo.get_by_id(s.worker1_id)
            if u1:
                w1_name = u1.sheet_name if u1.sheet_name else u1.name
            else:
                w1_name = f"ID: {s.worker1_id}"
            
        w2_name = "—"
        if s.worker2_id:
            u2 = await user_repo.get_by_id(s.worker2_id)
            if u2:
                w2_name = u2.sheet_name if u2.sheet_name else u2.name
            else:
                w2_name = f"ID: {s.worker2_id}"
            
        text = f"⛽ <b>Деталі сесії # {s.id}</b>\n\n"
        text += f"📊 <b>Статус:</b> <code>{s.status}</code>\n"
        text += f"📅 <b>Початок:</b> {s.start_time.strftime('%d.%m %H:%M')}\n"
        text += f"⏰ <b>Дедлайн:</b> {s.deadline.strftime('%H:%M')}\n"
        if s.end_time:
            text += f"🏁 <b>Завершено:</b> {s.end_time.strftime('%H:%M')}\n"
        
        text += f"\n👷 <b>Воркер 1:</b> {w1_name}\n"
        text += f"👷 <b>Воркер 2:</b> {w2_name}\n"
        
        if s.status == 'completed':
            # Resolve completed_by
            completed_by_name = "—"
            if s.completed_by:
                uc = await user_repo.get_by_id(s.completed_by)
                if uc:
                    completed_by_name = uc.sheet_name if uc.sheet_name else uc.name
                else:
                    completed_by_name = f"ID: {s.completed_by}"

            text += f"\n✅ <b>Виконав:</b> {completed_by_name}\n"
            text += f"⚙️ <b>Генератор:</b> {s.gen_name}\n"
            text += f"⛽ <b>Залито:</b> {s.liters} л\n"
            text += f"📦 <b>Списано:</b> {s.cans} кан\n"
            if s.notes:
                text += f"📝 <b>Замітка:</b> {s.notes}\n"

        builder = InlineKeyboardBuilder()
        if s.status in ['pending', 'in_progress']:
            builder.row(InlineKeyboardButton(text="❌ Скасувати сесію", callback_data=f"admin_session_cancel:{s.id}"))
        
        builder.row(InlineKeyboardButton(text="🔙 До списку", callback_data="admin_sessions"))
        
        # answer before editing to stop loading state if triggered by button with callback
        try: await callback.answer()
        except: pass

        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_session_view:"))
async def admin_session_view(callback: types.CallbackQuery, bot: Bot):
    session_id = int(callback.data.split(":")[1])
    await _admin_session_view_logic(callback, bot, session_id)

@router.callback_query(F.data.startswith("admin_session_cancel:"))
async def admin_session_cancel(callback: types.CallbackQuery, bot: Bot):
    session_id = int(callback.data.split(":")[1])
    
    from bot.database.main import session_maker
    from bot.database.repositories.session import SessionRepository
    from bot.database.models import SessionStatus
    
    async with session_maker() as session:
        repo = SessionRepository(session)
        await repo.update_status(session_id, SessionStatus.cancelled)
        await session.commit()
        
        await callback.answer("Сесію скасовано")
        # Refresh the view
        await _admin_session_view_logic(callback, bot, session_id)

@router.callback_query(F.data == "admin_create_session_manual")
async def admin_create_session_manual(callback: types.CallbackQuery, bot: Bot):
    from bot.services.session_service import SessionService
    from bot.database.main import session_maker
    
    try:
        async with session_maker() as session:
            service = SessionService(session, bot=bot)
            new_s = await service.create_manual_session(hours=2)
            await callback.answer(f"✅ Сесію {new_s.id} створено!")
            await admin_sessions_list(callback, bot)
    except Exception as e:
        await callback.answer(f"❌ Помилка: {str(e)}")

@router.callback_query(F.data == "admin_delete_cancelled_sessions")
async def admin_delete_cancelled_sessions(callback: types.CallbackQuery, bot: Bot):
    from bot.database.main import session_maker
    from bot.database.repositories.session import SessionRepository
    
    async with session_maker() as session:
        repo = SessionRepository(session)
        count = await repo.delete_cancelled()
        
    await callback.answer(f"✅ Видалено {count} скасованих сесій!", show_alert=True)
    await admin_sessions_list(callback, bot)

# --- User Management Handlers ---

@router.callback_query(F.data == "admin_users")
async def admin_users_list(callback: types.CallbackQuery, user_repo: UserRepository):
    users = await user_repo.get_all(include_blocked=True)
    
    builder = InlineKeyboardBuilder()
    for u in users:
        # ✅ if mapped, ❓ if unmapped
        status_icon = "✅" if u.sheet_name else "❓"
        builder.row(InlineKeyboardButton(
            text=f"{status_icon} {u.name}", 
            callback_data=f"admin_user_view:{u.id}"
        ))
    
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    
    await callback.message.edit_text(
        "👥 <b>Керування користувачами</b>\n\n"
        "Оберіть користувача для прив'язки до імені у графіку (Google Sheet).",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("admin_user_view:"))
async def admin_user_details(callback: types.CallbackQuery, user_repo: UserRepository):
    user_id = int(callback.data.split(":")[1])
    user = await user_repo.get_by_id(user_id)
    
    if not user:
        await callback.answer("Користувача не знайдено")
        return

    text = f"👤 <b>Користувач:</b> {user.name}\n"
    text += f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
    text += f"🎭 <b>Роль:</b> {user.role}\n"
    text += f"📊 <b>Ім'я у графіку:</b> {user.sheet_name or '<i>Не встановлено</i>'}\n\n"
    
    if not user.sheet_name:
        text += "⚠️ Користувач не буде отримувати автоматичні сповіщення про зміну, " \
                "доки його ім'я не буде співпадати з іменем у Google Таблиці."

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ Встановити ім'я для графіку", callback_data=f"admin_user_map:{user.id}"))
    if user.sheet_name:
        builder.row(InlineKeyboardButton(text="🗑️ Очистити прив'язку", callback_data=f"admin_user_unmap:{user.id}"))
    
    builder.row(InlineKeyboardButton(text="🔙 До списку", callback_data="admin_users"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_user_map:"))
async def admin_user_map_start(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    await state.update_data(mapping_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_sheet_name)
    
    await callback.message.edit_text(
        "✏️ <b>Встановлення імені для графіку</b>\n\n"
        "Введіть ім'я ПРАЦІВНИКА точно так, як воно записане у Google Таблиці.\n"
        "Наприклад: <code>Витя С.</code> або <code>Петро О.</code>",
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_sheet_name)
async def admin_user_map_finish(message: types.Message, state: FSMContext, user_repo: UserRepository):
    data = await state.get_data()
    user_id = data.get("mapping_user_id")
    sheet_name = message.text.strip()
    
    user = await user_repo.update_sheet_name(user_id, sheet_name)

    await message.answer(
        f"✅ Користувача <b>{user.name}</b> успішно прив'язано до імені <b>{sheet_name}</b>!",
        reply_markup=_get_admin_panel_kb(),
        parse_mode="HTML"
    )
    await state.clear()

@router.callback_query(F.data.startswith("admin_user_unmap:"))
async def admin_user_unmap(callback: types.CallbackQuery, user_repo: UserRepository):
    user_id = int(callback.data.split(":")[1])
    await user_repo.update_sheet_name(user_id, None)
    await callback.answer("Прив'язку видалено")
    await admin_user_details(callback, user_repo)

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
    
    from bot.services.session_service import SessionService
    from bot.database.main import session_maker
    
    try:
        async with session_maker() as session:
            service = SessionService(session, bot=bot)
            new_session = await service.check_power_outage()
            
            if new_session:
                await callback.message.edit_text(f"✅ <b>Успішно!</b>\nСтворено нову сесію (ID: {new_session.id})\nДедлайн: {new_session.deadline.strftime('%H:%M')}", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
            else:
                await callback.message.edit_text("ℹ️ <b>Результат:</b>\nВідключень не виявлено (або сесія вже існує).", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
    except Exception as e:
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
        
        await message.answer(f"✅ Інтервал змінено на <b>{minutes} хв</b>.\n(Зміна збережена в пам'яті).", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
        await state.clear()
        
    except Exception as e:
        safe_error = html.escape(str(e))
        await message.answer(f"⚠️ <b>Помилка:</b>\n{safe_error}\nВведіть число хвилин.", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_toggle_access")
async def toggle_access_callback(callback: types.CallbackQuery, user_repo: UserRepository):
    config.RESTRICT_ACCESS = not config.RESTRICT_ACCESS
    await admin_panel_back(callback)
    await callback.answer(f"✅ Режим змінено на: {'Обмежений' if config.RESTRICT_ACCESS else 'Публічний'}")

@router.callback_query(F.data == "admin_toggle_notify")
async def toggle_notify_callback(callback: types.CallbackQuery, user_repo: UserRepository):
    config.NOTIFY_WORKERS = not config.NOTIFY_WORKERS
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
    await callback.message.edit_text(text, reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_do_reset_logs")
async def do_reset_logs(callback: types.CallbackQuery, log_repo: LogRepository):
    await log_repo.clear_all()
    await callback.answer("✅ Історію успішно скинуто!", show_alert=True)
    await admin_panel_back(callback)

@router.callback_query(F.data == "admin_close")
async def admin_close_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()
