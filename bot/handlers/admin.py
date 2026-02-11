from aiogram import Router, F, types, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
import html
import logging

from bot.database.models import UserRole
from bot.database.repositories.user import UserRepository
from bot.database.repositories.logs import LogRepository
from bot.config import config
from bot.states import AdminStates, SlackStates
from bot.services.slack import SlackService

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
    builder.add(InlineKeyboardButton(text="📋 Працівники", callback_data="admin_sheets_workers"))
    builder.add(InlineKeyboardButton(text="👷 Воркери", callback_data="admin_next_workers"))
    
    # Row 3: Schedule
    builder.add(InlineKeyboardButton(text="🔄 Оновити", callback_data="admin_force_schedule"))
    builder.add(InlineKeyboardButton(text="⏱️ Інтервал", callback_data="admin_set_interval"))
    
    # Rows 4-5: System & Slack
    builder.add(InlineKeyboardButton(text="⚙️ Slack", callback_data="admin_slack_menu"))
    builder.add(InlineKeyboardButton(text="📜 Журнал подій", callback_data="admin_view_logs"))
    builder.add(InlineKeyboardButton(text="🧹 Скинути історію", callback_data="admin_confirm_reset_logs"))
    builder.add(InlineKeyboardButton(text="❌ Закрити", callback_data="admin_close"))
    
    builder.adjust(2, 4, 2, 3, 1)
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
            w3 = user_map.get(s.worker3_id, "—") if s.worker3_id else "—"
            
            if w1 == "—" and w2 == "—" and w3 == "—":
                workers_str = "немає воркерів"
            else:
                workers_str = ", ".join([w for w in [w1, w2, w3] if w != "—"])
            
            # Button for each session
            builder.row(InlineKeyboardButton(
                text=f"{icon} {s.start_time.strftime('%d.%m %H:%M')} | {workers_str}",
                callback_data=f"admin_session_view:{s.id}"
            ))

    builder.row(
        InlineKeyboardButton(text="➕ Створити вручну", callback_data="admin_create_session_manual"),
        InlineKeyboardButton(text="🗑️ Видалити скасовані", callback_data="admin_delete_cancelled_sessions")
    )
    builder.row(InlineKeyboardButton(text="🗑️ Видалити ВСІ сесії", callback_data="admin_confirm_delete_all_sessions"))
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
                w1_name = u1.name or u1.sheet_name or f"@{u1.username}" or f"ID: {s.worker1_id}"
            else:
                w1_name = f"ID: {s.worker1_id}"
            
        w2_name = "—"
        if s.worker2_id:
            u2 = await user_repo.get_by_id(s.worker2_id)
            if u2:
                w2_name = u2.name or u2.sheet_name or f"@{u2.username}" or f"ID: {s.worker2_id}"
            else:
                w2_name = f"ID: {s.worker2_id}"
            
        w3_name = "—"
        if s.worker3_id:
            u3 = await user_repo.get_by_id(s.worker3_id)
            if u3:
                w3_name = u3.name or u3.sheet_name or f"@{u3.username}" or f"ID: {s.worker3_id}"
            else:
                w3_name = f"ID: {s.worker3_id}"
            
        text = f"⛽ <b>Деталі сесії # {s.id}</b>\n\n"
        text += f"📊 <b>Статус:</b> <code>{s.status}</code>\n"
        text += f"📅 <b>Початок:</b> {s.start_time.strftime('%d.%m %H:%M')}\n"
        text += f"⏰ <b>Дедлайн:</b> {s.deadline.strftime('%H:%M')}\n"
        if s.end_time:
            text += f"🏁 <b>Завершено:</b> {s.end_time.strftime('%H:%M')}\n"
        
        text += f"\n👷 <b>Воркер 1:</b> {w1_name}\n"
        text += f"👷 <b>Воркер 2:</b> {w2_name}\n"
        text += f"👷 <b>Воркер 3:</b> {w3_name}\n"
        
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
    
    try:
        await callback.message.edit_text(
            "👥 <b>Керування користувачами</b>\n\n"
            "Оберіть користувача для прив'язки до імені у графіку (Google Sheet).",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        import logging
        logging.warning(f"Failed to edit admin users list: {e}")
        await callback.answer()

@router.callback_query(F.data == "admin_sheets_workers")
async def admin_sheets_workers_list(callback: types.CallbackQuery, user_repo: UserRepository):
    from bot.services.google_sheets import GoogleSheetsService
    sheets_service = GoogleSheetsService()
    
    # 1. Get all names from Sheets (Rows 39-60)
    try:
        sheet_names = sheets_service.get_all_worker_names()
    except Exception as e:
        await callback.answer(f"❌ Помилка Google Sheets: {str(e)}", show_alert=True)
        return

    # 2. Get all registered users to check mapping
    users = await user_repo.get_all(include_blocked=True)
    registered_mapped_names = {u.sheet_name for u in users if u.sheet_name}
    
    # 3. Format list
    text = "📋 <b>Працівники з Google Таблиці</b>\n"
    text += f"<i>(Рядки 39-60, всього знайдено: {len(sheet_names)})</i>\n\n"
    
    if not sheet_names:
        text += "❌ Працівників не знайдено за вказаним діапазоном."
    else:
        for name in sheet_names:
            if name in registered_mapped_names:
                text += f"✅ <b>{name}</b>\n"
            else:
                text += f"❌ {name}\n"
        
        text += "\n✅ — зареєстрований у боті\n"
        text += "❌ — не знайдено (потрібна прив'язка у меню 'Користувачі')"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔄 Оновити", callback_data="admin_sheets_workers"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    
    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except Exception as e:
        if "message is not modified" in str(e):
            await callback.answer("Дані актуальні ✅")
        else:
            import logging
            logging.warning(f"Failed to edit workers list: {e}")
            await callback.answer()

@router.callback_query(F.data == "admin_next_workers")
async def admin_next_workers_handler(callback: types.CallbackQuery, bot: Bot):
    from bot.database.main import session_maker
    from bot.database.repositories.schedule import ScheduleRepository
    from bot.services.google_sheets import GoogleSheetsService
    from bot.database.repositories.user import UserRepository
    import zoneinfo
    from datetime import datetime, date, time, timedelta

    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    
    async with session_maker() as session:
        sched_repo = ScheduleRepository(session)
        sheets_service = GoogleSheetsService()
        user_repo = UserRepository(session)
        
        # 1. Get schedule entries for today and tomorrow
        entries = await sched_repo.get_all_for_date_range(now.date(), now.date() + timedelta(days=1))
        
        if not entries:
            await callback.message.edit_text(
                "📅 <b>Графік порожній</b>\nЗавантажте графік відключень, щоб побачити воркерів.",
                reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back")).as_markup(),
                parse_mode="HTML"
            )
            return

        # 2. Find next power-on moment
        # Power return is at (end_hour):00
        all_slots = []
        for e in entries:
            for h in range(e.start_hour, e.end_hour):
                all_slots.append(datetime.combine(e.date, time(h % 24, 0)))
        
        all_slots = sorted(list(set(all_slots)))
        
        potential_returns = []
        if all_slots:
            current_block_end = all_slots[0] + timedelta(hours=1)
            for i in range(1, len(all_slots)):
                if all_slots[i] == current_block_end:
                    current_block_end = all_slots[i] + timedelta(hours=1)
                else:
                    potential_returns.append(current_block_end)
                    current_block_end = all_slots[i] + timedelta(hours=1)
            potential_returns.append(current_block_end)

        next_rt = None
        for rt in sorted(potential_returns):
            if rt.replace(tzinfo=tz) > now:
                next_rt = rt
                break
        
        if not next_rt:
            await callback.message.edit_text(
                "👀 <b>Наступних заправок не знайдено</b>\nНа найближчий час відключень не заплановано.",
                reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back")).as_markup(),
                parse_mode="HTML"
            )
            return

        # 3. Get workers for that time from Sheets
        lookup_dt = next_rt - timedelta(minutes=1)
        worker_tuples = sheets_service.get_workers_for_outage(lookup_dt.hour, lookup_dt.date())
        
        text = f"👷 <b>Наступна заправка</b>\n"
        text += f"⏰ Час відновлення: <code>{next_rt.strftime('%H:%M')}</code> ({next_rt.strftime('%d.%m')})\n\n"
        text += "👥 <b>Чергові за графіком:</b>\n"
        
        if not worker_tuples:
            text += "❓ Працівників у Google Таблиці не знайдено."
        else:
            for w_name, _ in worker_tuples:
                user = await user_repo.get_by_sheet_name(w_name)
                status = "✅" if user else "❌"
                text += f"{status} {w_name}\n"
            
            text += "\n<i>✅ — отримає алерт</i>\n"
            text += f"<i>🕒 Дані на {lookup_dt.strftime('%H:%M')}</i>"

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔄 Оновити", callback_data="admin_next_workers"))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
        
        try:
            await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                await callback.answer("Дані актуальні ✅")
            else:
                raise

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
    except:
        pass
        
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass

@router.callback_query(F.data == "admin_view_logs")
async def admin_view_logs(callback: types.CallbackQuery, log_repo: LogRepository, user_repo: UserRepository):
    from bot.config import config
    import zoneinfo
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
@router.callback_query(F.data == "admin_confirm_delete_all_sessions")
async def admin_confirm_delete_all_sessions(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Так, видалити ВСЕ", callback_data="admin_perform_delete_all_sessions"),
        InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_sessions")
    )
    
    await callback.message.edit_text(
        "⚠️ <b>УВАГА: ВИДАЛЕННЯ ВСІХ СЕСІЙ</b>\n\n"
        "Бот видалить <b>ВСЮ</b> історію заправок з бази даних. Ця дія незворотна.\n\n"
        "Ви справді впевнені?", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )

@router.callback_query(F.data == "admin_perform_delete_all_sessions")
async def admin_perform_delete_all_sessions(callback: types.CallbackQuery, bot: Bot):
    from bot.database.main import session_maker
    from bot.database.repositories.session import SessionRepository
    
    async with session_maker() as session:
        repo = SessionRepository(session)
        count = await repo.delete_all()
    
    await callback.answer(f"🗑️ Видалено сесій: {count}", show_alert=True)
    await admin_sessions_list(callback, bot)

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
        
        # Update configuration (runtime)
        config.FUEL_THRESHOLD_CANS = new_threshold
        
        await state.clear()
        await message.answer(
            f"✅ <b>Поріг оновлено!</b>\n\n"
            f"Новий поріг: <b>{new_threshold}</b> каністр\n\n"
            f"<i>Примітка: для збереження після перезапуску додайте в .env:\n"
            f"FUEL_THRESHOLD_CANS={new_threshold}</i>",
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
