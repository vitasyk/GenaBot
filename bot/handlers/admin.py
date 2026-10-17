import html
from datetime import date, timedelta

from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton
from redis.asyncio import Redis

from bot.config import config
from bot.database.main import session_maker
from bot.database.models import SessionStatus
from bot.database.repositories.logs import LogRepository
from bot.database.repositories.session import SessionRepository
from bot.database.repositories.user import UserRepository
from bot.filters.roles import is_admin
from bot.generator_specs import MAX_GENERATOR_NAME_LENGTH
from bot.keyboards.callbacks import GenCallback
from bot.keyboards.main_kb import ADMIN_PANEL_TEXT, MAIN_MENU_TEXTS
from bot.scheduler import scheduler, CHECK_POWER_OUTAGE_JOB_ID
from bot.services.generator import GeneratorService
from bot.services.runtime_settings import (
    NOTIFY_WORKERS_KEY,
    RESTRICT_ACCESS_KEY,
    SCHEDULE_INTERVAL_KEY,
    normalize_queue,
    save_flag,
    save_queue,
)
from bot.services.schedule_parser import ScheduleParser, format_hours, parse_hours_input
from bot.services.session_service import SessionService
from bot.states import AdminStates
from bot.utils.clock import now_kyiv

router = Router()
router.message.filter(is_admin)
router.callback_query.filter(is_admin)

SESSION_STATUS_ICONS = {
    SessionStatus.pending.value: "⏳",
    SessionStatus.in_progress.value: "⚙️",
    SessionStatus.completed.value: "✅",
    SessionStatus.cancelled.value: "❌",
}
AUTO_SCHEDULE_WORDS = {"авто", "auto", "ші", "ai"}
MANUAL_SESSION_HOURS = 2
# Queues offered as buttons (HOE: 6 queues x 2 subqueues); any other one can be typed in
QUEUE_BUTTONS = [f"{queue}.{sub}" for queue in range(1, 7) for sub in (1, 2)]


def _admin_panel_text() -> str:
    text = "📊 <b>Адмін-панель</b>\n\n"
    text += f"🔐 <b>Режим доступу:</b> {'🔒 Обмежений (Whitelist)' if config.RESTRICT_ACCESS else '🌍 Публічний'}\n"
    text += f"📢 <b>Сповіщення:</b> {'👥 Всім працівникам' if config.NOTIFY_WORKERS else '👮 Тільки адмінам'}\n"
    text += f"👥 <b>Білий список:</b> {len(config.ALLOWED_IDS)} ID\n"
    text += f"👑 <b>Адміни:</b> {len(config.ADMIN_IDS)} ID\n"
    text += f"🔢 <b>Черга графіка:</b> {html.escape(config.QUEUE_NUMBER)}\n"
    return text

def _get_admin_panel_kb() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    access_text = "🌍 Відкрити доступ" if config.RESTRICT_ACCESS else "🔒 Обмежити доступ"
    builder.row(InlineKeyboardButton(text=access_text, callback_data="admin_toggle_access"))
    notify_text = "👮 Сповіщення: Тільки адмінам" if config.NOTIFY_WORKERS else "👥 Сповіщення: Всім"
    builder.row(InlineKeyboardButton(text=notify_text, callback_data="admin_toggle_notify"))
    builder.row(InlineKeyboardButton(text="⚙️ Генератори", callback_data="admin_generators"))
    builder.row(InlineKeyboardButton(text="⛽ Сесії заправки", callback_data="admin_sessions"))
    builder.row(InlineKeyboardButton(text="👥 Користувачі (Mapping)", callback_data="admin_users"))
    builder.row(InlineKeyboardButton(text=f"🔢 Черга: {config.QUEUE_NUMBER}", callback_data="admin_queue"))
    builder.row(InlineKeyboardButton(text="✍️ Графік вручну", callback_data="admin_manual_schedule"))
    builder.row(InlineKeyboardButton(text="🔄 Оновити статус (Force)", callback_data="admin_force_schedule"))
    builder.row(InlineKeyboardButton(text="⚙️ Інтервал перевірки", callback_data="admin_set_interval"))
    builder.row(InlineKeyboardButton(text="🧹 Скинути історію", callback_data="admin_confirm_reset_logs"))
    builder.row(InlineKeyboardButton(text="❌ Закрити", callback_data="admin_close"))
    return builder.as_markup()

def _back_to_panel_kb() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back")]])

async def _cancel_on_menu_button(message: types.Message, state: FSMContext) -> bool:
    if message.text in MAIN_MENU_TEXTS:
        await state.clear()
        await message.answer("❌ Скасовано. Оберіть пункт меню ще раз.")
        return True
    return False

@router.message(F.text == ADMIN_PANEL_TEXT)
async def admin_panel_handler(message: types.Message):
    await message.answer(_admin_panel_text(), reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_panel_back")
async def admin_panel_back(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(_admin_panel_text(), reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin_close")
async def admin_close_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# --- Generators ---

async def _show_generators(callback: types.CallbackQuery, generator_service: GeneratorService) -> None:
    builder = InlineKeyboardBuilder()
    for g in await generator_service.list_all():
        icon = "✅" if g.is_active else "⛔"
        builder.row(InlineKeyboardButton(text=f"{icon} {g.name}",
                                         callback_data=GenCallback(action="admin", gen_id=g.id).pack()))
    builder.row(InlineKeyboardButton(text="➕ Додати генератор", callback_data="admin_gen_add"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    await callback.message.edit_text(
        "⚙️ <b>Генератори</b>\n\n✅ — доступний для запуску й заправки, ⛔ — вимкнений (історія зберігається).",
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )

@router.callback_query(F.data == "admin_generators")
async def admin_generators(callback: types.CallbackQuery, generator_service: GeneratorService):
    await _show_generators(callback, generator_service)
    await callback.answer()

async def _show_generator(callback: types.CallbackQuery, generator_service: GeneratorService, gen_id: int) -> None:
    gen = await generator_service.get_by_id(gen_id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return

    text = f"⚙️ <b>{html.escape(gen.name)}</b>\n\n"
    text += f"Стан: {'✅ увімкнений' if gen.is_active else '⛔ вимкнений'}\n"
    text += f"Бак: {gen.tank_capacity:.1f} л, споживання: {gen.consumption_rate:.1f} л/год\n"
    text += f"Відпрацьовано: {gen.total_hours_run or 0.0:.1f} год\n"
    text += f"Інструкція SOS: {'є' if gen.instructions else 'немає'}"

    builder = InlineKeyboardBuilder()
    toggle_text = "⛔ Вимкнути" if gen.is_active else "✅ Увімкнути"
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data=f"admin_gen_toggle:{gen.id}"))
    builder.row(InlineKeyboardButton(text="📝 Інструкція SOS", callback_data=f"admin_gen_sos:{gen.id}"))
    builder.row(InlineKeyboardButton(text="🔙 До списку", callback_data="admin_generators"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(GenCallback.filter(F.action == "admin"))
async def admin_generator_view(callback: types.CallbackQuery, callback_data: GenCallback,
                               generator_service: GeneratorService):
    await _show_generator(callback, generator_service, callback_data.gen_id)
    await callback.answer()

@router.callback_query(F.data.startswith("admin_gen_toggle:"))
async def admin_generator_toggle(callback: types.CallbackQuery, generator_service: GeneratorService):
    gen_id = int(callback.data.split(":")[1])
    gen = await generator_service.get_by_id(gen_id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    await generator_service.set_active(callback.from_user.id, gen_id, not gen.is_active)
    await _show_generator(callback, generator_service, gen_id)
    await callback.answer("✅ Збережено")

@router.callback_query(F.data == "admin_gen_add")
async def admin_generator_add_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_generator_name)
    await callback.message.edit_text(
        "➕ <b>Новий генератор</b>\n\nВведіть назву (до "
        f"{MAX_GENERATOR_NAME_LENGTH} символів), наприклад <code>WILSON</code>.\n"
        "Бак і споживання потім змініть через 🔄 Керування → 🔧 Корегування.",
        reply_markup=_back_to_panel_kb(), parse_mode="HTML"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_generator_name)
async def admin_generator_add_finish(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if await _cancel_on_menu_button(message, state):
        return
    name = (message.text or "").strip()
    if not name or len(name) > MAX_GENERATOR_NAME_LENGTH:
        await message.answer(f"⚠️ Назва має бути від 1 до {MAX_GENERATOR_NAME_LENGTH} символів.")
        return

    gen = await generator_service.add_generator(message.from_user.id, name)
    if not gen:
        await message.answer("⚠️ Генератор з такою назвою вже є. Введіть іншу назву.")
        return

    await state.clear()
    await message.answer(f"✅ Генератор <b>{html.escape(gen.name)}</b> додано й увімкнено.",
                         reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_gen_sos:"))
async def admin_generator_sos_start(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(sos_gen_id=int(callback.data.split(":")[1]))
    await state.set_state(AdminStates.waiting_for_generator_instructions)
    await callback.message.edit_text("📝 Надішліть текст інструкції із запуску цього генератора одним повідомленням.",
                                     reply_markup=_back_to_panel_kb())
    await callback.answer()

@router.message(AdminStates.waiting_for_generator_instructions)
async def admin_generator_sos_finish(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if await _cancel_on_menu_button(message, state):
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("⚠️ Надішліть інструкцію текстом.")
        return

    gen = await generator_service.set_instructions(message.from_user.id, (await state.get_data())["sos_gen_id"], text)
    await state.clear()
    result = f"✅ Інструкцію для <b>{html.escape(gen.name)}</b> збережено." if gen else "⚠️ Генератор не знайдено."
    await message.answer(result, reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

# --- Refuel sessions ---

@router.callback_query(F.data == "admin_sessions")
async def admin_sessions_list(callback: types.CallbackQuery, user_repo: UserRepository):
    async with session_maker() as session:
        history = await SessionRepository(session).get_history(limit=8)
    all_users = await user_repo.get_all(include_blocked=True)
    # Prefer sheet_name (Google Sheets name), fallback to Telegram name
    user_map = {u.id: (u.sheet_name or u.name or str(u.id)) for u in all_users}

    builder = InlineKeyboardBuilder()
    if not history:
        text = "⛽ <b>Сесії заправки</b>\n\nСесій ще не було."
    else:
        text = "⛽ <b>Сесії заправки</b>\n\nОберіть сесію для перегляду деталей або скасування:"
        for s in history:
            icon = SESSION_STATUS_ICONS.get(s.status, "❓")
            w1 = user_map.get(s.worker1_id, "—") if s.worker1_id else "—"
            w2 = user_map.get(s.worker2_id, "—") if s.worker2_id else "—"
            workers_str = "немає воркерів" if w1 == w2 == "—" else f"{w1}, {w2}"
            builder.row(InlineKeyboardButton(
                text=f"{icon} {s.start_time.strftime('%d.%m %H:%M')} | {workers_str}",
                callback_data=f"admin_session_view:{s.id}"
            ))

    builder.row(InlineKeyboardButton(text="➕ Створити вручну", callback_data="admin_create_session_manual"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

async def _admin_session_view_logic(callback: types.CallbackQuery, user_repo: UserRepository, session_id: int):
    async with session_maker() as session:
        s = await SessionRepository(session).get_session_by_id(session_id)

    if not s:
        await callback.answer("Сесію не знайдено")
        return

    async def worker_name(worker_id: int | None) -> str:
        if not worker_id:
            return "—"
        user = await user_repo.get_by_id(worker_id)
        return html.escape(user.sheet_name or user.name) if user else f"ID: {worker_id}"

    text = f"⛽ <b>Деталі сесії # {s.id}</b>\n\n"
    text += f"📊 <b>Статус:</b> <code>{s.status}</code>\n"
    text += f"📅 <b>Початок:</b> {s.start_time.strftime('%d.%m %H:%M')}\n"
    text += f"⏰ <b>Дедлайн:</b> {s.deadline.strftime('%H:%M')}\n"
    if s.end_time:
        text += f"🏁 <b>Завершено:</b> {s.end_time.strftime('%H:%M')}\n"

    text += f"\n👷 <b>Воркер 1:</b> {await worker_name(s.worker1_id)}\n"
    text += f"👷 <b>Воркер 2:</b> {await worker_name(s.worker2_id)}\n"

    if s.status == SessionStatus.completed.value:
        text += f"\n⛽ <b>Генератор:</b> {html.escape(s.gen_name or '—')}\n"
        text += f"⛽ <b>Залито:</b> {s.liters} л\n"
        text += f"📦 <b>Списано:</b> {s.cans} кан\n"
        if s.notes:
            text += f"📝 <b>Замітка:</b> {html.escape(s.notes)}\n"

    builder = InlineKeyboardBuilder()
    if s.status in (SessionStatus.pending.value, SessionStatus.in_progress.value):
        builder.row(InlineKeyboardButton(text="❌ Скасувати сесію", callback_data=f"admin_session_cancel:{s.id}"))
    builder.row(InlineKeyboardButton(text="🔙 До списку", callback_data="admin_sessions"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_session_view:"))
async def admin_session_view(callback: types.CallbackQuery, user_repo: UserRepository):
    await _admin_session_view_logic(callback, user_repo, int(callback.data.split(":")[1]))
    await callback.answer()

@router.callback_query(F.data.startswith("admin_session_cancel:"))
async def admin_session_cancel(callback: types.CallbackQuery, user_repo: UserRepository):
    session_id = int(callback.data.split(":")[1])
    async with session_maker() as session:
        await SessionRepository(session).update_status(session_id, SessionStatus.cancelled)
    await _admin_session_view_logic(callback, user_repo, session_id)
    await callback.answer("Сесію скасовано")

@router.callback_query(F.data == "admin_create_session_manual")
async def admin_create_session_manual(callback: types.CallbackQuery, bot: Bot, user_repo: UserRepository,
                                      schedule_parser: ScheduleParser):
    async with session_maker() as session:
        new_s = await SessionService(session, schedule_parser, bot=bot).create_manual_session(hours=MANUAL_SESSION_HOURS)
    await admin_sessions_list(callback, user_repo)
    await callback.answer(f"✅ Сесію {new_s.id} створено!")

# --- Schedule ---

def _manual_schedule_kb() -> types.InlineKeyboardMarkup:
    today = now_kyiv().date()
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=f"Сьогодні ({today:%d.%m})", callback_data=f"admin_manual_day:{today.isoformat()}"),
        InlineKeyboardButton(text=f"Завтра ({today + timedelta(days=1):%d.%m})",
                             callback_data=f"admin_manual_day:{(today + timedelta(days=1)).isoformat()}"),
    )
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    return builder.as_markup()

@router.callback_query(F.data == "admin_manual_schedule")
async def admin_manual_schedule(callback: types.CallbackQuery, schedule_parser: ScheduleParser):
    today = now_kyiv().date()
    text = (f"✍️ <b>Графік вручну</b> (черга {html.escape(config.QUEUE_NUMBER)})\n\n"
            "Введені години мають пріоритет над розпізнаванням ШІ.\n\n")
    for day in (today, today + timedelta(days=1)):
        manual = await schedule_parser.get_manual_hours(day, config.QUEUE_NUMBER)
        text += f"• {day:%d.%m}: {format_hours(manual) if manual is not None else 'авто (ШІ)'}\n"
    await callback.message.edit_text(text, reply_markup=_manual_schedule_kb(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("admin_manual_day:"))
async def admin_manual_day(callback: types.CallbackQuery, state: FSMContext):
    day = date.fromisoformat(callback.data.split(":")[1])
    await state.update_data(manual_day=day.isoformat())
    await state.set_state(AdminStates.waiting_for_manual_hours)
    await callback.message.edit_text(
        f"✍️ <b>Години відключень на {day:%d.%m}</b> (черга {html.escape(config.QUEUE_NUMBER)})\n\n"
        "Приклади:\n"
        "<code>14-18, 22-24</code> — з 14:00 до 18:00 і з 22:00 до 24:00\n"
        "<code>0</code> — відключень немає\n"
        "<code>авто</code> — повернути розпізнавання ШІ",
        reply_markup=_back_to_panel_kb(), parse_mode="HTML"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_manual_hours)
async def admin_manual_hours_input(message: types.Message, state: FSMContext, schedule_parser: ScheduleParser):
    if await _cancel_on_menu_button(message, state):
        return
    day = date.fromisoformat((await state.get_data())["manual_day"])
    text = (message.text or "").strip()

    queue = config.QUEUE_NUMBER
    if text.lower() in AUTO_SCHEDULE_WORDS:
        await schedule_parser.clear_manual_hours(day, queue)
        result = f"✅ {day:%d.%m}, черга {html.escape(queue)}: повернуто розпізнавання ШІ."
    else:
        try:
            hours = parse_hours_input(text)
        except ValueError:
            await message.answer("⚠️ Не зрозумів. Приклад: <code>14-18, 22-24</code> або <code>0</code>.", parse_mode="HTML")
            return
        await schedule_parser.set_manual_hours(day, queue, hours)
        result = f"✅ {day:%d.%m}, черга {html.escape(queue)}: {format_hours(hours)}"

    await state.clear()
    await message.answer(result, reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_queue")
async def admin_queue_menu(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    for queue in QUEUE_BUTTONS:
        mark = "✅ " if queue == config.QUEUE_NUMBER else ""
        builder.button(text=f"{mark}{queue}", callback_data=f"admin_queue_set:{queue}")
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="✍️ Ввести іншу", callback_data="admin_queue_custom"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    await callback.message.edit_text(
        f"🔢 <b>Яку чергу розпізнавати?</b>\n\nЗараз: <b>{html.escape(config.QUEUE_NUMBER)}</b>.\n"
        "Від черги залежать сесії заправки, «📉 Графік» і ручні години.",
        reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("admin_queue_set:"))
async def admin_queue_set(callback: types.CallbackQuery, state: FSMContext, redis: Redis):
    queue = normalize_queue(callback.data.split(":", 1)[1])
    if not queue:
        await callback.answer("Невідома черга", show_alert=True)
        return
    await save_queue(redis, queue)
    await admin_panel_back(callback, state)
    await callback.answer(f"✅ Черга {queue}")

@router.callback_query(F.data == "admin_queue_custom")
async def admin_queue_custom(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_queue_number)
    await callback.message.edit_text("✍️ Введіть номер черги, наприклад <code>1.1</code> або <code>4.2</code>.",
                                     reply_markup=_back_to_panel_kb(), parse_mode="HTML")
    await callback.answer()

@router.message(AdminStates.waiting_for_queue_number)
async def admin_queue_input(message: types.Message, state: FSMContext, redis: Redis):
    if await _cancel_on_menu_button(message, state):
        return
    queue = normalize_queue(message.text or "")
    if not queue:
        await message.answer("⚠️ Формат: число, крапка, число — наприклад <code>1.1</code>.", parse_mode="HTML")
        return
    await save_queue(redis, queue)
    await state.clear()
    await message.answer(f"✅ Черга графіка: <b>{queue}</b>", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_force_schedule")
async def force_schedule_check(callback: types.CallbackQuery, bot: Bot, schedule_parser: ScheduleParser):
    await callback.answer()
    await callback.message.edit_text("⏳ <b>Перевірка графіку...</b>\nЦе може зайняти кілька секунд.", parse_mode="HTML")

    async with session_maker() as session:
        new_session = await SessionService(session, schedule_parser, bot=bot).check_power_outage()

    if new_session:
        text = (f"✅ <b>Успішно!</b>\nСтворено нову сесію (ID: {new_session.id})\n"
                f"Дедлайн: {new_session.deadline.strftime('%H:%M')}")
    else:
        text = "ℹ️ <b>Результат:</b>\nВідключень не виявлено (або сесія вже існує)."
    await callback.message.edit_text(text, reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_set_interval")
async def set_interval_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("⚙️ <b>Налаштування інтервалу</b>\n\nВведіть інтервал перевірки графіку в хвилинах (наприклад: 15).",
                                     reply_markup=_back_to_panel_kb(), parse_mode="HTML")
    await state.set_state(AdminStates.waiting_for_check_interval)
    await callback.answer()

@router.message(AdminStates.waiting_for_check_interval)
async def interval_input(message: types.Message, state: FSMContext, redis: Redis):
    if await _cancel_on_menu_button(message, state):
        return
    try:
        minutes = int((message.text or "").strip())
    except ValueError:
        minutes = 0
    if minutes < 1:
        await message.answer("⚠️ Введіть ціле число хвилин, більше нуля.")
        return

    await redis.set(SCHEDULE_INTERVAL_KEY, minutes)
    scheduler.reschedule_job(CHECK_POWER_OUTAGE_JOB_ID, trigger='interval', minutes=minutes)
    await state.clear()
    await message.answer(f"✅ Інтервал змінено на <b>{minutes} хв</b>.", reply_markup=_get_admin_panel_kb(), parse_mode="HTML")

# --- Toggles & users ---

@router.callback_query(F.data == "admin_toggle_access")
async def toggle_access_callback(callback: types.CallbackQuery, state: FSMContext, redis: Redis):
    config.RESTRICT_ACCESS = not config.RESTRICT_ACCESS
    await save_flag(redis, RESTRICT_ACCESS_KEY, config.RESTRICT_ACCESS)
    await admin_panel_back(callback, state)
    await callback.answer(f"✅ Режим змінено на: {'Обмежений' if config.RESTRICT_ACCESS else 'Публічний'}")

@router.callback_query(F.data == "admin_toggle_notify")
async def toggle_notify_callback(callback: types.CallbackQuery, state: FSMContext, redis: Redis):
    config.NOTIFY_WORKERS = not config.NOTIFY_WORKERS
    await save_flag(redis, NOTIFY_WORKERS_KEY, config.NOTIFY_WORKERS)
    await admin_panel_back(callback, state)
    await callback.answer(f"✅ Отримувачі: {'Всі працівники' if config.NOTIFY_WORKERS else 'Тільки адміни'}")

@router.callback_query(F.data == "admin_confirm_reset_logs")
async def confirm_reset_logs(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗑️ ТАК, СКИНУТИ", callback_data="admin_do_reset_logs"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    await callback.message.edit_text("⚠️ <b>УВАГА!</b>\n\nЦе видалить всю історію заправок.\nВи впевнені?",
                                     reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "admin_do_reset_logs")
async def do_reset_logs(callback: types.CallbackQuery, state: FSMContext, log_repo: LogRepository):
    await log_repo.clear_all()
    await callback.answer("✅ Історію успішно скинуто!", show_alert=True)
    await admin_panel_back(callback, state)

@router.callback_query(F.data == "admin_users")
async def admin_users_list(callback: types.CallbackQuery, user_repo: UserRepository):
    builder = InlineKeyboardBuilder()
    for u in await user_repo.get_all(include_blocked=True):
        status_icon = "✅" if u.sheet_name else "❓"
        builder.row(InlineKeyboardButton(text=f"{status_icon} {u.name}", callback_data=f"admin_user_view:{u.id}"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))

    await callback.message.edit_text(
        "👥 <b>Керування користувачами</b>\n\n"
        "Оберіть користувача для прив'язки до імені у графіку (Google Sheet).",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

async def _show_user(callback: types.CallbackQuery, user_repo: UserRepository, user_id: int) -> None:
    user = await user_repo.get_by_id(user_id)
    if not user:
        await callback.answer("Користувача не знайдено")
        return

    text = f"👤 <b>Користувач:</b> {html.escape(user.name)}\n"
    text += f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
    text += f"🎭 <b>Роль:</b> {user.role.value}\n"
    text += f"📊 <b>Ім'я у графіку:</b> {html.escape(user.sheet_name) if user.sheet_name else '<i>Не встановлено</i>'}\n\n"
    if not user.sheet_name:
        text += "⚠️ Користувач не буде отримувати автоматичні сповіщення про зміну, " \
                "доки його ім'я не буде співпадати з іменем у Google Таблиці."

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ Встановити ім'я для графіку", callback_data=f"admin_user_map:{user.id}"))
    if user.sheet_name:
        builder.row(InlineKeyboardButton(text="🗑️ Очистити прив'язку", callback_data=f"admin_user_unmap:{user.id}"))
    builder.row(InlineKeyboardButton(text="🔙 До списку", callback_data="admin_users"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_user_view:"))
async def admin_user_details(callback: types.CallbackQuery, user_repo: UserRepository):
    await _show_user(callback, user_repo, int(callback.data.split(":")[1]))
    await callback.answer()

@router.callback_query(F.data.startswith("admin_user_map:"))
async def admin_user_map_start(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(mapping_user_id=int(callback.data.split(":")[1]))
    await state.set_state(AdminStates.waiting_for_sheet_name)
    await callback.message.edit_text(
        "✏️ <b>Встановлення імені для графіку</b>\n\n"
        "Введіть ім'я ПРАЦІВНИКА точно так, як воно записане у Google Таблиці.\n"
        "Наприклад: <code>Витя С.</code> або <code>Петро О.</code>",
        reply_markup=_back_to_panel_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_sheet_name)
async def admin_user_map_finish(message: types.Message, state: FSMContext, user_repo: UserRepository):
    if await _cancel_on_menu_button(message, state):
        return
    sheet_name = (message.text or "").strip()
    if not sheet_name:
        await message.answer("⚠️ Введіть ім'я текстом.")
        return

    user = await user_repo.update_sheet_name((await state.get_data()).get("mapping_user_id"), sheet_name)
    await state.clear()
    if not user:
        await message.answer("⚠️ Користувача не знайдено.", reply_markup=_get_admin_panel_kb())
        return
    await message.answer(
        f"✅ Користувача <b>{html.escape(user.name)}</b> успішно прив'язано до імені <b>{html.escape(sheet_name)}</b>!",
        reply_markup=_get_admin_panel_kb(),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("admin_user_unmap:"))
async def admin_user_unmap(callback: types.CallbackQuery, user_repo: UserRepository):
    user_id = int(callback.data.split(":")[1])
    await user_repo.update_sheet_name(user_id, None)
    await _show_user(callback, user_repo, user_id)
    await callback.answer("Прив'язку видалено")
