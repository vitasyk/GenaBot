import html
from datetime import datetime, time

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.config import config
from bot.keyboards.main_kb import MENU_BUTTONS
from bot.services.generator import GeneratorService
from bot.services.maintenance import format_status, maintenance_status
from bot.states import AdminStates
from bot.utils.clock import local_to_utc, now_local

router = Router()

# --- Generator Management Handlers ---

GEN_NAME_MAX_LEN = 32
SOS_TEXT_MAX_LEN = 3500  # leaves room for the title within Telegram's 4096 limit
SOS_MEDIA_MAX = 10  # Telegram sends at most 10 files in one album
HOURS_DELTA_MAX = 1000
MAINT_HOURS_MAX = 2000
MAINT_MONTHS_MAX = 36
_admin_only = F.from_user.id.in_(config.ADMIN_IDS)
_GEN_INPUT_STATES = {
    AdminStates.waiting_for_gen_name.state,
    AdminStates.waiting_for_gen_instructions.state,
    AdminStates.waiting_for_gen_media.state,
    AdminStates.waiting_for_gen_hours.state,
    AdminStates.waiting_for_maint_date.state,
    AdminStates.waiting_for_maint_hours.state,
    AdminStates.waiting_for_maint_interval.state,
}


class AdminGenCb(CallbackData, prefix="adm_gen"):
    action: str  # view, toggle, sos, media, media_clear, hours, maint, maint_today, maint_cur, maint_int
    id: int


def _generators_list_kb(gens) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for g in gens:
        icon = "✅" if g.is_active else "⛔"
        builder.row(InlineKeyboardButton(text=f"{icon} {g.name}", callback_data=AdminGenCb(action="view", id=g.id).pack()))
    builder.row(InlineKeyboardButton(text="➕ Додати генератор", callback_data="admin_gen_add"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel_back"))
    return builder.as_markup()


async def _generators_list_text_kb(generator_service: GeneratorService) -> tuple[str, types.InlineKeyboardMarkup]:
    gens = await generator_service.get_all()
    text = "⚙️ <b>Генератори</b>\n\n✅ — активний (є в меню), ⛔ — вимкнений.\nОберіть генератор:"
    return text, _generators_list_kb(gens)


def _generator_details(gen) -> tuple[str, types.InlineKeyboardMarkup]:
    text = f"⚙️ <b>{html.escape(gen.name)}</b>\n\n"
    text += f"📍 <b>Стан:</b> {'✅ Активний' if gen.is_active else '⛔ Вимкнений'}\n"
    text += f"⚡ <b>Статус:</b> {gen.status.value}\n"
    text += f"⛽ <b>Залишок:</b> {gen.fuel_level:.1f} л (бак {gen.tank_capacity:.1f} л)\n"
    text += f"📉 <b>Споживання:</b> {gen.consumption_rate:.1f} л/год\n"
    text += f"⏱ <b>Напрацювання:</b> {gen.total_hours_run or 0.0:.1f} год\n"
    text += f"{format_status(maintenance_status(gen, now_local().date()))}\n"
    text += f"🗓 <b>Інтервал ТО:</b> {gen.maint_interval_hours:g} год або {gen.maint_interval_months} міс\n"
    media_count = len(gen.instructions_media or [])
    text += f"🆘 <b>Інструкція SOS:</b> {'додано' if gen.instructions else 'не додано'}"
    text += f", вкладень: {media_count}"

    builder = InlineKeyboardBuilder()
    toggle_text = "⛔ Вимкнути" if gen.is_active else "✅ Увімкнути"
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data=AdminGenCb(action="toggle", id=gen.id).pack()))
    builder.row(InlineKeyboardButton(text="⏱ Мотогодини", callback_data=AdminGenCb(action="hours", id=gen.id).pack()))
    builder.row(InlineKeyboardButton(text="🔧 ТО виконано", callback_data=AdminGenCb(action="maint", id=gen.id).pack()),
                InlineKeyboardButton(text="🗓 Інтервал ТО", callback_data=AdminGenCb(action="maint_int", id=gen.id).pack()))
    builder.row(InlineKeyboardButton(text="📝 Інструкція SOS", callback_data=AdminGenCb(action="sos", id=gen.id).pack()))
    builder.row(InlineKeyboardButton(text="📎 Фото / PDF", callback_data=AdminGenCb(action="media", id=gen.id).pack()))
    if media_count:
        builder.row(InlineKeyboardButton(text=f"🗑 Прибрати вкладення ({media_count})",
                                         callback_data=AdminGenCb(action="media_clear", id=gen.id).pack()))
    builder.row(InlineKeyboardButton(text="🔙 До списку", callback_data="admin_generators"))
    return text, builder.as_markup()


def _media_done_kb(gen_id: int) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Готово", callback_data=AdminGenCb(action="view", id=gen_id).pack()))
    return builder.as_markup()


def _cancel_to_generators_kb() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_generators"))
    return builder.as_markup()


def _is_menu_or_command(message: types.Message) -> bool:
    """A menu button or /command during text input cancels the step."""
    return message.text in MENU_BUTTONS or (message.text or "").startswith("/")


@router.callback_query(_admin_only, F.data == "admin_generators")
async def admin_generators_list(callback: types.CallbackQuery, state: FSMContext, generator_service: GeneratorService):
    if await state.get_state() in _GEN_INPUT_STATES:
        await state.clear()
    text, kb = await _generators_list_text_kb(generator_service)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(_admin_only, AdminGenCb.filter(F.action == "view"))
async def admin_generator_view(callback: types.CallbackQuery, callback_data: AdminGenCb, state: FSMContext, generator_service: GeneratorService):
    if await state.get_state() in _GEN_INPUT_STATES:  # "✅ Готово" after attaching files
        await state.clear()
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    text, kb = _generator_details(gen)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(_admin_only, AdminGenCb.filter(F.action == "toggle"))
async def admin_generator_toggle(callback: types.CallbackQuery, callback_data: AdminGenCb, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    gen = await generator_service.set_active(callback.from_user.id, gen.id, not gen.is_active)
    text, kb = _generator_details(gen)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("✅ Увімкнено" if gen.is_active else "⛔ Вимкнено")


@router.callback_query(_admin_only, AdminGenCb.filter(F.action == "sos"))
async def admin_generator_sos_start(callback: types.CallbackQuery, callback_data: AdminGenCb, state: FSMContext, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_gen_instructions)
    await state.update_data(gen_id=gen.id)
    await callback.message.edit_text(
        f"📝 <b>Інструкція SOS для {html.escape(gen.name)}</b>\n\n"
        "Надішліть текст інструкції запуску одним повідомленням (форматування збережеться).",
        reply_markup=_cancel_to_generators_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(_admin_only, AdminStates.waiting_for_gen_instructions)
async def admin_generator_sos_input(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if _is_menu_or_command(message):
        await state.clear()
        await message.answer("❌ Скасовано. Оберіть пункт меню ще раз.")
        return
    if not message.text or len(message.text) > SOS_TEXT_MAX_LEN:
        await message.answer(f"⚠️ Надішліть текст до {SOS_TEXT_MAX_LEN} символів.")
        return

    data = await state.get_data()
    # html_text keeps the admin's formatting and escapes everything else
    gen = await generator_service.set_instructions(message.from_user.id, data.get("gen_id"), message.html_text)
    await state.clear()
    if not gen:
        await message.answer("❌ Генератор не знайдено.")
        return
    text, kb = _generator_details(gen)
    await message.answer("✅ Інструкцію збережено!\n\n" + text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(_admin_only, AdminGenCb.filter(F.action == "hours"))
async def admin_generator_hours_start(callback: types.CallbackQuery, callback_data: AdminGenCb, state: FSMContext, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_gen_hours)
    await state.update_data(gen_id=gen.id)
    await callback.message.edit_text(
        f"⏱ <b>Мотогодини {html.escape(gen.name)}</b>\n\n"
        f"Зараз: {gen.total_hours_run or 0.0:.1f} год.\n"
        "Надішліть, скільки додати або відняти, напр. <code>+2.5</code> або <code>-1</code>.\n"
        f"Паливо зміниться разом з годинами: {gen.consumption_rate:.1f} л за кожну годину "
        "(додані години списують, відняті повертають).",
        reply_markup=_cancel_to_generators_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(_admin_only, AdminStates.waiting_for_gen_hours)
async def admin_generator_hours_input(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if _is_menu_or_command(message):
        await state.clear()
        await message.answer("❌ Скасовано. Оберіть пункт меню ще раз.")
        return
    try:
        delta = float((message.text or "").strip().replace(",", "."))
    except ValueError:
        delta = 0.0
    if not 0 < abs(delta) <= HOURS_DELTA_MAX:  # also rejects nan/inf
        await message.answer(f"⚠️ Введіть число годин, напр. +2.5 або -1 (до {HOURS_DELTA_MAX}).")
        return

    gen = await generator_service.adjust_total_hours(message.from_user.id, (await state.get_data()).get("gen_id"), delta)
    await state.clear()
    if not gen:
        await message.answer("❌ Генератор не знайдено.")
        return
    text, kb = _generator_details(gen)
    await message.answer(f"✅ Мотогодини змінено на {delta:+.1f} год.\n\n" + text, reply_markup=kb, parse_mode="HTML")


def _maint_step_kb(gen_id: int, action: str, text: str) -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=text, callback_data=AdminGenCb(action=action, id=gen_id).pack()))
    builder.row(InlineKeyboardButton(text="🔙 Скасувати", callback_data="admin_generators"))
    return builder.as_markup()


@router.callback_query(_admin_only, AdminGenCb.filter(F.action == "maint"))
async def admin_maint_start(callback: types.CallbackQuery, callback_data: AdminGenCb, state: FSMContext, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_maint_date)
    await state.update_data(gen_id=gen.id)
    await callback.message.edit_text(
        f"🔧 <b>ТО {html.escape(gen.name)}</b>\n\nКоли зробили ТО? Надішліть дату <code>ДД.ММ.РРРР</code> або натисніть «Сьогодні».",
        reply_markup=_maint_step_kb(gen.id, "maint_today", "📅 Сьогодні"),
        parse_mode="HTML"
    )
    await callback.answer()


async def _ask_maint_hours(message: types.Message, state: FSMContext, gen, done_at: datetime, edit: bool) -> None:
    await state.set_state(AdminStates.waiting_for_maint_hours)
    await state.update_data(maint_done_at=done_at.isoformat())
    current = gen.total_hours_run or 0.0
    text = (f"🔧 <b>ТО {html.escape(gen.name)}</b> від {done_at:%d.%m.%Y}\n\n"
            f"Скільки мотогодин було на момент ТО? Надішліть число (0–{current:.1f}) або натисніть «Поточні».")
    kb = _maint_step_kb(gen.id, "maint_cur", f"⏱ Поточні ({current:.1f} год)")
    await (message.edit_text if edit else message.answer)(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(_admin_only, AdminStates.waiting_for_maint_date, AdminGenCb.filter(F.action == "maint_today"))
async def admin_maint_today(callback: types.CallbackQuery, callback_data: AdminGenCb, state: FSMContext, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await state.clear()
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    await _ask_maint_hours(callback.message, state, gen, local_to_utc(datetime.combine(now_local().date(), time(12))), edit=True)
    await callback.answer()


@router.message(_admin_only, AdminStates.waiting_for_maint_date)
async def admin_maint_date_input(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if _is_menu_or_command(message):
        await state.clear()
        await message.answer("❌ Скасовано. Оберіть пункт меню ще раз.")
        return
    try:
        day = datetime.strptime((message.text or "").strip(), "%d.%m.%Y").date()
    except ValueError:
        day = None
    if day is None or day > now_local().date() or day.year < 2000:
        await message.answer("⚠️ Надішліть дату у форматі ДД.ММ.РРРР, не пізніше сьогодні.")
        return
    gen = await generator_service.get_by_id((await state.get_data()).get("gen_id"))
    if not gen:
        await state.clear()
        await message.answer("❌ Генератор не знайдено.")
        return
    # Noon Kyiv time: the stored UTC moment stays on the same local date
    await _ask_maint_hours(message, state, gen, local_to_utc(datetime.combine(day, time(12))), edit=False)


async def _save_maint(state: FSMContext, generator_service: GeneratorService, user_id: int, hours: float | None):
    """hours=None: the generator's current total."""
    data = await state.get_data()
    await state.clear()
    gen = await generator_service.get_by_id(data.get("gen_id"))
    if not gen:
        return None
    hours = (gen.total_hours_run or 0.0) if hours is None else hours
    return await generator_service.set_maintenance(user_id, gen.id, datetime.fromisoformat(data["maint_done_at"]), hours)


@router.callback_query(_admin_only, AdminStates.waiting_for_maint_hours, AdminGenCb.filter(F.action == "maint_cur"))
async def admin_maint_current_hours(callback: types.CallbackQuery, state: FSMContext, generator_service: GeneratorService):
    gen = await _save_maint(state, generator_service, callback.from_user.id, None)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    text, kb = _generator_details(gen)
    await callback.message.edit_text("✅ ТО записано!\n\n" + text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.message(_admin_only, AdminStates.waiting_for_maint_hours)
async def admin_maint_hours_input(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if _is_menu_or_command(message):
        await state.clear()
        await message.answer("❌ Скасовано. Оберіть пункт меню ще раз.")
        return
    gen = await generator_service.get_by_id((await state.get_data()).get("gen_id"))
    current = (gen.total_hours_run or 0.0) if gen else 0.0
    try:
        hours = float((message.text or "").strip().replace(",", "."))
    except ValueError:
        hours = -1.0
    if not 0 <= hours <= current:  # also rejects nan
        await message.answer(f"⚠️ Введіть число від 0 до {current:.1f}.")
        return
    gen = await _save_maint(state, generator_service, message.from_user.id, hours)
    if not gen:
        await message.answer("❌ Генератор не знайдено.")
        return
    text, kb = _generator_details(gen)
    await message.answer("✅ ТО записано!\n\n" + text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(_admin_only, AdminGenCb.filter(F.action == "maint_int"))
async def admin_maint_interval_start(callback: types.CallbackQuery, callback_data: AdminGenCb, state: FSMContext, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_maint_interval)
    await state.update_data(gen_id=gen.id)
    await callback.message.edit_text(
        f"🗓 <b>Інтервал ТО {html.escape(gen.name)}</b>\n\n"
        f"Зараз: кожні {gen.maint_interval_hours:g} год або {gen.maint_interval_months} міс (що настане раніше).\n"
        "Надішліть два числа: мотогодини і місяці, напр. <code>200 12</code>.",
        reply_markup=_cancel_to_generators_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(_admin_only, AdminStates.waiting_for_maint_interval)
async def admin_maint_interval_input(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if _is_menu_or_command(message):
        await state.clear()
        await message.answer("❌ Скасовано. Оберіть пункт меню ще раз.")
        return
    parts = (message.text or "").replace(",", ".").split()
    try:
        hours, months = float(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        hours, months = 0.0, 0
    if len(parts) != 2 or not 1 <= hours <= MAINT_HOURS_MAX or not 1 <= months <= MAINT_MONTHS_MAX:
        await message.answer(f"⚠️ Надішліть два числа: години (1–{MAINT_HOURS_MAX}) і місяці (1–{MAINT_MONTHS_MAX}), напр. 200 12.")
        return
    gen = await generator_service.set_maintenance_interval(message.from_user.id, (await state.get_data()).get("gen_id"), hours, months)
    await state.clear()
    if not gen:
        await message.answer("❌ Генератор не знайдено.")
        return
    text, kb = _generator_details(gen)
    await message.answer("✅ Інтервал ТО збережено!\n\n" + text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(_admin_only, AdminGenCb.filter(F.action == "media"))
async def admin_generator_media_start(callback: types.CallbackQuery, callback_data: AdminGenCb, state: FSMContext, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_gen_media)
    await state.update_data(gen_id=gen.id)
    await callback.message.edit_text(
        f"📎 <b>Вкладення до інструкції {html.escape(gen.name)}</b>\n\n"
        f"Надсилайте фото або PDF по одному (до {SOS_MEDIA_MAX} разом із наявними: "
        f"{len(gen.instructions_media or [])}). Коли закінчите, натисніть «✅ Готово».",
        reply_markup=_media_done_kb(gen.id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(_admin_only, AdminStates.waiting_for_gen_media)
async def admin_generator_media_input(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if message.text and _is_menu_or_command(message):
        await state.clear()
        await message.answer("❌ Скасовано. Оберіть пункт меню ще раз.")
        return

    gen_id = (await state.get_data()).get("gen_id")
    mime = (message.document.mime_type or "") if message.document else ""
    if message.photo:
        kind, file_id = "photo", message.photo[-1].file_id
    elif mime == "application/pdf" or mime.startswith("image/"):  # images sent "as file" stay files
        kind, file_id = "document", message.document.file_id
    else:
        await message.answer("⚠️ Надішліть фото або PDF-файл.", reply_markup=_media_done_kb(gen_id))
        return

    gen = await generator_service.get_by_id(gen_id)
    if not gen:
        await state.clear()
        await message.answer("❌ Генератор не знайдено.")
        return
    if len(gen.instructions_media or []) >= SOS_MEDIA_MAX:
        await message.answer(f"⚠️ Вже {SOS_MEDIA_MAX} вкладень — більше не можна. Натисніть «✅ Готово».",
                             reply_markup=_media_done_kb(gen_id))
        return

    gen = await generator_service.add_instruction_media(message.from_user.id, gen_id, kind, file_id)
    await message.answer(
        f"✅ Додано ({len(gen.instructions_media)}/{SOS_MEDIA_MAX}). Надішліть ще або натисніть «✅ Готово».",
        reply_markup=_media_done_kb(gen_id)
    )


@router.callback_query(_admin_only, AdminGenCb.filter(F.action == "media_clear"))
async def admin_generator_media_clear(callback: types.CallbackQuery, callback_data: AdminGenCb, generator_service: GeneratorService):
    gen = await generator_service.clear_instruction_media(callback.from_user.id, callback_data.id)
    if not gen:
        await callback.answer("Генератор не знайдено", show_alert=True)
        return
    text, kb = _generator_details(gen)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("🗑 Вкладення прибрано")


@router.callback_query(_admin_only, F.data == "admin_gen_add")
async def admin_generator_add_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_gen_name)
    await callback.message.edit_text(
        "➕ <b>Новий генератор</b>\n\n"
        f"Введіть назву (1–{GEN_NAME_MAX_LEN} символів, без &lt; &gt; &amp;).\n"
        "Бак 40 л і споживання 2 л/год можна змінити потім у «🔄 Керування» → «🔧 Корегування».",
        reply_markup=_cancel_to_generators_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(_admin_only, AdminStates.waiting_for_gen_name)
async def admin_generator_add_input(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    if _is_menu_or_command(message):
        await state.clear()
        await message.answer("❌ Скасовано. Оберіть пункт меню ще раз.")
        return
    name = (message.text or "").strip()
    # Names go into HTML messages unescaped across the bot, so forbid HTML-special characters
    if not 1 <= len(name) <= GEN_NAME_MAX_LEN or any(c in name for c in "<>&"):
        await message.answer(f"⚠️ Назва має містити 1–{GEN_NAME_MAX_LEN} символів без &lt; &gt; &amp;. Спробуйте ще раз.", parse_mode="HTML")
        return

    gen = await generator_service.add_generator(message.from_user.id, name)
    if not gen:
        await message.answer("⚠️ Генератор з такою назвою вже існує. Введіть іншу назву.")
        return

    await state.clear()
    text, kb = await _generators_list_text_kb(generator_service)
    await message.answer(f"✅ Генератор <b>{html.escape(name)}</b> додано!\n\n" + text, reply_markup=kb, parse_mode="HTML")
