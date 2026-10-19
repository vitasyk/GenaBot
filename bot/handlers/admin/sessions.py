import html

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

router = Router()

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
                'cancelled': "❌",
                'expired': "⌛"
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

    try:
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    except TelegramBadRequest as e:
        # e.g. "Delete cancelled" with nothing to delete: the list is unchanged
        if "message is not modified" not in str(e):
            raise

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
                w1_name = u1.name or u1.sheet_name or f"ID: {s.worker1_id}"
            else:
                w1_name = f"ID: {s.worker1_id}"
            
        w2_name = "—"
        if s.worker2_id:
            u2 = await user_repo.get_by_id(s.worker2_id)
            if u2:
                w2_name = u2.name or u2.sheet_name or f"ID: {s.worker2_id}"
            else:
                w2_name = f"ID: {s.worker2_id}"
            
        w3_name = "—"
        if s.worker3_id:
            u3 = await user_repo.get_by_id(s.worker3_id)
            if u3:
                w3_name = u3.name or u3.sheet_name or f"ID: {s.worker3_id}"
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
                text += f"📝 <b>Замітка:</b> {html.escape(s.notes)}\n"

        builder = InlineKeyboardBuilder()
        if s.status in ['pending', 'in_progress', 'expired']:
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
