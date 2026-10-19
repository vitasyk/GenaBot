import asyncio
import html
import logging

from aiogram import Bot, F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.config import config
from bot.database.repositories.user import UserRepository
from bot.handlers.admin._common import _get_admin_panel_kb
from bot.states import AdminStates

router = Router()

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
    
    # 1. Get all names from Sheets (gspread is blocking: keep it off the event loop)
    try:
        sheet_names = await asyncio.to_thread(sheets_service.get_all_worker_names)
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
    from datetime import datetime, time, timedelta

    tz = zoneinfo.ZoneInfo(config.TIMEZONE)
    now = datetime.now(tz)
    
    async with session_maker() as session:
        sched_repo = ScheduleRepository(session)
        sheets_service = GoogleSheetsService()
        user_repo = UserRepository(session)
        
        # 1. Get schedule entries for today and tomorrow
        entries = await sched_repo.get_all_for_date_range(now.date(), now.date() + timedelta(days=1), config.QUEUE_NUMBER)
        
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
        try:
            worker_tuples = await asyncio.to_thread(sheets_service.get_workers_for_outage, lookup_dt.hour, lookup_dt.date())
        except Exception as e:
            logging.warning("Next workers: Google Sheets unavailable", exc_info=True)
            await callback.message.edit_text(
                f"❌ <b>Google Таблиця недоступна</b>\n{html.escape(str(e))}",
                reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back")).as_markup(),
                parse_mode="HTML"
            )
            return
        
        text = "👷 <b>Наступна заправка</b>\n"
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
