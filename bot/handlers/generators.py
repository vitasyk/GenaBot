import html

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

from bot.database.models import GenStatus
from bot.keyboards.callbacks import GenCallback
from bot.keyboards.inline_kb import get_generator_control_kb, get_generator_select_kb
from bot.keyboards.main_kb import MAIN_MENU_TEXTS
from bot.services.generator import GeneratorService
from bot.states import GenStates

router = Router()

GEN_NOT_FOUND_TEXT = "Генератор не знайдено або його вимкнено"

async def _get_status_panel(generator_service: GeneratorService, with_keyboard: bool = True,
                            exclude_correction: bool = False) -> tuple[str, types.InlineKeyboardMarkup | None]:
    gens = await generator_service.get_status()

    # Returns a fallback temperature (factor 1.0) when the weather API is down
    temp = await generator_service.weather.get_current_temperature()
    factor = generator_service.weather.get_consumption_factor(temp)

    text = "⚡ <b>Статус генераторів</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n\n"
    if not gens:
        text += "Немає активних генераторів. Адміністратор може додати їх в адмін-панелі.\n\n"
    for g in gens:
        rate = g.consumption_rate
        adj_rate = rate * factor

        if g.status == GenStatus.running:
            status_icon, status_text = "🟢", "ПРАЦЮЄ"
        elif g.status == GenStatus.standby:
            status_icon, status_text = "🟡", "ЧЕРГУЄ (STANDBY)"
        else:
            status_icon, status_text = "🔴", "ЗУПИНЕНО"

        text += f"{status_icon} <b>{html.escape(g.name)}</b>: {status_text}\n"

        hours_left = (g.fuel_level / adj_rate) if adj_rate > 0 else 0
        text += f"   ⛽ <b>Залишок:</b> {g.fuel_level:.1f} л (бак {g.tank_capacity:.1f} л)\n"

        if factor > 1.0:
            text += f"   ❄️ <i>Поправка на мороз ({temp:.0f}°C): +{int((factor-1)*100)}% витрати</i>\n"

        if g.status == GenStatus.running:
            text += f"   ⏳ <b>Вистачить на:</b> ~{hours_left:.1f} год\n"
            if g.current_run_start:
                text += f"   🕒 <b>Запущено о:</b> {g.current_run_start.strftime('%H:%M')}\n"
        else:
            text += f"   💤 <b>Очікуваний час роботи:</b> ~{hours_left:.1f} год\n"

        text += f"   📊 <b>Всього відпрацьовано:</b> {g.total_hours_run or 0.0:.1f} год\n"
        text += f"   📉 <b>Споживання:</b> {rate:.1f} л/год\n\n"
    text += "➖➖➖➖➖➖➖➖➖➖"

    kb = get_generator_control_kb(gens, exclude_correction=exclude_correction) if with_keyboard else None
    return text, kb

def _get_correction_keyboard() -> types.InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⛽ Залишок палива", callback_data="correct_mode_fuel"))
    builder.row(InlineKeyboardButton(text="🛢️ Об'єм бака", callback_data="correct_mode_tank"))
    builder.row(InlineKeyboardButton(text="📉 Споживання (л/год)", callback_data="correct_mode_rate"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="correct_fuel_menu"))
    return builder.as_markup()

async def _cancel_on_menu_button(message: types.Message, state: FSMContext) -> bool:
    """A menu button pressed instead of a number cancels the correction."""
    if message.text in MAIN_MENU_TEXTS:
        await state.clear()
        await message.answer("❌ Корегування скасовано. Оберіть пункт меню ще раз.")
        return True
    return False

def _parse_non_negative(text: str | None) -> float | None:
    try:
        value = float((text or "").replace(",", "."))
    except ValueError:
        return None
    return value if value >= 0 else None

async def _refresh_status(callback: types.CallbackQuery, generator_service: GeneratorService) -> None:
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@router.message(F.text.in_({"⚡ Статус", "⚡ Status"}))
async def check_status(message: types.Message, generator_service: GeneratorService):
    text, kb = await _get_status_panel(generator_service, with_keyboard=True, exclude_correction=True)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.message(F.text == "🔄 Керування")
async def switch_gen_menu(message: types.Message, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await message.answer("Оберіть дію:", reply_markup=get_generator_control_kb(gens), parse_mode="HTML")

@router.callback_query(GenCallback.filter(F.action == "start"))
async def start_generator_callback(callback: types.CallbackQuery, callback_data: GenCallback,
                                   generator_service: GeneratorService):
    gen = await generator_service.get_active(callback_data.gen_id)
    if not gen:
        await callback.answer(GEN_NOT_FOUND_TEXT, show_alert=True)
        return

    await generator_service.start_generator(callback.from_user.id, gen.name)
    await _refresh_status(callback, generator_service)
    await callback.answer(f"✅ {gen.name} запущено!")

@router.callback_query(GenCallback.filter(F.action == "standby"))
async def standby_generator_callback(callback: types.CallbackQuery, callback_data: GenCallback,
                                     generator_service: GeneratorService):
    gen = await generator_service.get_active(callback_data.gen_id)
    if not gen:
        await callback.answer(GEN_NOT_FOUND_TEXT, show_alert=True)
        return

    await generator_service.set_standby(callback.from_user.id, gen.name)
    await _refresh_status(callback, generator_service)
    await callback.answer(f"🟡 {gen.name} в режимі очікування!")

@router.callback_query(F.data == "stop_all_gens")
async def stop_all_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    await generator_service.stop_all(callback.from_user.id)
    await _refresh_status(callback, generator_service)
    await callback.answer("🛑 Всі генератори зупинено!")

@router.callback_query(F.data == "correct_fuel_menu")
async def correction_menu(callback: types.CallbackQuery, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await callback.message.edit_text(
        "🔧 <b>Корегування</b>\nОберіть генератор:",
        reply_markup=get_generator_select_kb(gens, "correct", "🔙 Скасувати", "gen_status_back"),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "gen_status_back")
async def back_to_status_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    await _refresh_status(callback, generator_service)
    await callback.answer()

@router.callback_query(GenCallback.filter(F.action == "correct"))
async def correct_options(callback: types.CallbackQuery, callback_data: GenCallback, state: FSMContext,
                          generator_service: GeneratorService):
    gen = await generator_service.get_active(callback_data.gen_id)
    if not gen:
        await callback.answer(GEN_NOT_FOUND_TEXT, show_alert=True)
        return

    await state.update_data(gen_name=gen.name)
    await callback.message.edit_text(
        f"⚙️ <b>{html.escape(gen.name)}</b>\nЩо хочете змінити?",
        reply_markup=_get_correction_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()

CORRECTION_MODES = {
    "fuel": (GenStates.waiting_for_fuel_amount, "точний залишок палива (л)"),
    "tank": (GenStates.waiting_for_tank_capacity, "об'єм бака (л)"),
    "rate": (GenStates.waiting_for_consumption_rate, "споживання (л/год)"),
}

@router.callback_query(F.data.startswith("correct_mode_"))
async def correct_init(callback: types.CallbackQuery, state: FSMContext):
    mode = CORRECTION_MODES.get(callback.data.removeprefix("correct_mode_"))
    gen_name = (await state.get_data()).get("gen_name")
    if not mode or not gen_name:
        await callback.answer("Оберіть генератор ще раз", show_alert=True)
        return

    next_state, what = mode
    await state.set_state(next_state)
    await callback.message.answer(f"✍️ Введіть {what} для <b>{html.escape(gen_name)}</b>:", parse_mode="HTML")
    await callback.answer()

async def _read_correction(message: types.Message, state: FSMContext) -> tuple[str, float] | None:
    """Common part of the three correction inputs: cancel, parse, generator name from FSM."""
    if await _cancel_on_menu_button(message, state):
        return None
    value = _parse_non_negative(message.text)
    if value is None:
        await message.answer("❌ Введіть невід'ємне число (наприклад 35.5)")
        return None
    return (await state.get_data()).get("gen_name"), value

async def _finish_correction(message: types.Message, state: FSMContext, title: str, gen_name: str, value_text: str):
    # set_state(None) leaves FSM data (gen_name) for the next correction from the same menu
    await state.set_state(state=None)
    await message.answer(
        f"✅ <b>{title}</b>\n{html.escape(gen_name)}: {value_text}\n\nЩо ще змінити?",
        parse_mode="HTML",
        reply_markup=_get_correction_keyboard()
    )

@router.message(GenStates.waiting_for_fuel_amount)
async def process_correction_fuel(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    result = await _read_correction(message, state)
    if not result:
        return
    gen_name, liters = result
    await generator_service.correct_fuel(message.from_user.id, gen_name, liters)
    await _finish_correction(message, state, "Залишок оновлено!", gen_name, f"{liters}л")

@router.message(GenStates.waiting_for_tank_capacity)
async def process_correction_tank(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    result = await _read_correction(message, state)
    if not result:
        return
    gen_name, capacity = result
    gen = await generator_service.repo.get_by_name(gen_name)
    if not gen:
        await message.answer("❌ Генератор не знайдено. Спробуйте оновити меню.")
        await state.clear()
        return
    await generator_service.update_generator_specs(message.from_user.id, gen_name, capacity, gen.consumption_rate)
    await _finish_correction(message, state, "Об'єм бака оновлено!", gen_name, f"{capacity}л")

@router.message(GenStates.waiting_for_consumption_rate)
async def process_correction_rate(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    result = await _read_correction(message, state)
    if not result:
        return
    gen_name, rate = result
    gen = await generator_service.repo.get_by_name(gen_name)
    if not gen:
        await message.answer("❌ Генератор не знайдено. Спробуйте оновити меню.")
        await state.clear()
        return
    await generator_service.update_generator_specs(message.from_user.id, gen_name, gen.tank_capacity, rate)
    await _finish_correction(message, state, "Споживання оновлено!", gen_name, f"{rate}л/год")
