import html

from aiogram import F, Router, types
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.config import config
from bot.keyboards.main_kb import MENU_BUTTONS
from bot.services.generator import GeneratorService
from bot.states import AdminStates

router = Router()

# --- Generator Management Handlers ---

GEN_NAME_MAX_LEN = 32
SOS_TEXT_MAX_LEN = 3500  # leaves room for the title within Telegram's 4096 limit
SOS_MEDIA_MAX = 10  # Telegram sends at most 10 files in one album
_admin_only = F.from_user.id.in_(config.ADMIN_IDS)
_GEN_INPUT_STATES = {
    AdminStates.waiting_for_gen_name.state,
    AdminStates.waiting_for_gen_instructions.state,
    AdminStates.waiting_for_gen_media.state,
}


class AdminGenCb(CallbackData, prefix="adm_gen"):
    action: str  # view, toggle, sos, media, media_clear
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
    media_count = len(gen.instructions_media or [])
    text += f"🆘 <b>Інструкція SOS:</b> {'додано' if gen.instructions else 'не додано'}"
    text += f", вкладень: {media_count}"

    builder = InlineKeyboardBuilder()
    toggle_text = "⛔ Вимкнути" if gen.is_active else "✅ Увімкнути"
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data=AdminGenCb(action="toggle", id=gen.id).pack()))
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
