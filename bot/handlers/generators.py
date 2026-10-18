from aiogram import Router, F, types
import logging
from aiogram.fsm.context import FSMContext
from bot.states import GenStates
from bot.services.generator import GeneratorService
from bot.keyboards.inline_kb import (
    STALE_MENU_TEXT,
    GenCb,
    get_generator_control_kb,
    get_generator_pick_kb,
)
from bot.keyboards.main_kb import MENU_BUTTONS
from bot.database.models import GenStatus
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

router = Router()

async def _get_status_panel(generator_service: GeneratorService, with_keyboard: bool = True, exclude_correction: bool = False):
    logging.info("Status panel requested - v2.0")
    gens = await generator_service.get_status()
    
    # Weather info
    try:
        temp = await generator_service.weather.get_current_temperature()
        factor = generator_service.weather.get_consumption_factor(temp)
    except:
        temp = 0
        factor = 1.0

    text = "⚡ <b>Статус генераторів</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n\n"
    for g in gens:
        capacity = g.tank_capacity
        rate = g.consumption_rate
        
        # Weather adjusted rate
        adj_rate = rate * factor
        
        if g.status == GenStatus.running:
            status_icon = "🟢"
            status_text = "ПРАЦЮЄ"
        elif g.status == GenStatus.standby:
            status_icon = "🟡"
            status_text = "ЧЕРГУЄ (STANDBY)"
        else:
            status_icon = "🔴"
            status_text = "ЗУПИНЕНО"
        
        antigel_icon = " ❄️" if g.fuel_since_antigel >= 80 else ""
        text += f"{status_icon} <b>{g.name}</b>{antigel_icon}: {status_text}\n"
        
        # Runtime prediction
        hours_left = (g.fuel_level / adj_rate) if adj_rate > 0 else 0
        
        text += f"   ⛽ <b>Залишок:</b> {g.fuel_level:.1f} л (бак {capacity:.1f} л)\n"
        
        if factor > 1.0:
            text += f"   ❄️ <i>Поправка на мороз ({temp:.0f}°C): +{int((factor-1)*100)}% витрати</i>\n"
        
        if g.status == GenStatus.running:
             text += f"   ⏳ <b>Вистачить на:</b> ~{hours_left:.1f} год\n"
             if g.current_run_start:
                  # Convert UTC to Configured Timezone
                  from bot.config import config
                  from datetime import timezone
                  import zoneinfo
                  
                  try:
                      tz = zoneinfo.ZoneInfo(config.TIMEZONE)
                      # Ensure current_run_start is aware (it's naive usually in SQLAlchemy if not forced)
                      # Assuming it's UTC naive
                      utc_time = g.current_run_start.replace(tzinfo=timezone.utc)
                      local_time = utc_time.astimezone(tz)
                      time_str = local_time.strftime('%H:%M')
                  except Exception as e:
                      # Fallback
                      logging.error(f"Timezone error: {e}")
                      time_str = g.current_run_start.strftime('%H:%M UTC')

                  text += f"   🕒 <b>Запущено о:</b> {time_str}\n"
        else:
             text += f"   💤 <b>Очікуваний час роботи:</b> ~{hours_left:.1f} год\n"
             
        text += f"   📊 <b>Всього відпрацьовано:</b> {g.total_hours_run or 0.0:.1f} год\n"
        text += f"   📉 <b>Споживання:</b> {rate:.1f} л/год\n"
        # Warming recommendation
        warm_rec = await generator_service.get_warming_recommendation(g.name)
        if warm_rec:
            text += f"   {warm_rec}\n"
            
        text += "\n"
    text += "➖➖➖➖➖➖➖➖➖➖"

    kb = get_generator_control_kb(gens, exclude_correction=exclude_correction, exclude_stop_all=exclude_correction) if with_keyboard else None

    if kb:
        # Add Notification Toggle Button
        notify_status = await generator_service.get_notify_start_status()
        text_status = "🔔 Сповіщення: ON" if notify_status else "🔕 Сповіщення: OFF"
        kb.inline_keyboard.append([InlineKeyboardButton(text=text_status, callback_data="toggle_notify_start")])
        
        # Add Close button for Status menu (when exclude_correction is True)
        if exclude_correction:
            kb.inline_keyboard.append([InlineKeyboardButton(text="❌ Закрити", callback_data="status_close")])
        
    return text, kb

@router.callback_query(F.data == "toggle_notify_start")
async def toggle_notify_handler(callback: types.CallbackQuery, generator_service: GeneratorService):
    new_state = await generator_service.toggle_notify_start()
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    state_str = "увімкнено" if new_state else "вимкнено"
    await callback.answer(f"Сповіщення {state_str}!")

@router.callback_query(F.data == "status_close")
async def status_close_handler(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass  # Message already deleted or not found
    await callback.answer()

def _get_correction_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⛽ Залишок палива", callback_data="correct_mode_fuel"))
    builder.row(InlineKeyboardButton(text="🛢️ Об'єм бака", callback_data="correct_mode_tank"))
    builder.row(InlineKeyboardButton(text="📉 Споживання (л/год)", callback_data="correct_mode_rate"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="correct_fuel_menu"))
    return builder.as_markup()

@router.message(F.text.in_({"⚡ Статус", "⚡ Status"}))
async def check_status(message: types.Message, generator_service: GeneratorService):
    text, kb = await _get_status_panel(generator_service, with_keyboard=True, exclude_correction=True)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "gen_status_back")
async def back_to_status_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.message(F.text == "🔄 Керування")
async def switch_gen_menu(message: types.Message, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await message.answer("Оберіть дію:", reply_markup=get_generator_control_kb(gens), parse_mode="HTML")

# Buttons sent before generators moved to the DB carry names/positions instead of ids.
_STALE_PREFIXES = (
    "start_gen_", "standby_gen_", "correct_select_", "refuel_select_", "refuel_confirm_",
    "sos_gen_", "toggle_gen:", "gen_choice:", "antigel_reset_",
)

@router.callback_query(F.data.startswith(_STALE_PREFIXES))
async def stale_generator_button(callback: types.CallbackQuery):
    await callback.answer(STALE_MENU_TEXT, show_alert=True)

async def _active_gen_or_alert(callback: types.CallbackQuery, generator_service: GeneratorService, gen_id: int):
    gen = await generator_service.get_active(gen_id)
    if not gen:
        await callback.answer(STALE_MENU_TEXT, show_alert=True)
    return gen

@router.callback_query(GenCb.filter(F.action == "start"))
async def start_generator_callback(callback: types.CallbackQuery, callback_data: GenCb, generator_service: GeneratorService):
    gen = await _active_gen_or_alert(callback, generator_service, callback_data.id)
    if not gen:
        return
    gen_name = gen.name

    # Check for warming recommendation
    warm_rec = await generator_service.get_warming_recommendation(gen_name)
    warning_text = ""
    if warm_rec:
        warning_text = f"\n\n{warm_rec}"
        
    await generator_service.start_generator(callback.from_user.id, gen_name)
    
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text + warning_text, reply_markup=kb, parse_mode="HTML")
    await callback.answer(f"✅ {gen_name} запущено!")

@router.callback_query(GenCb.filter(F.action == "standby"))
async def standby_generator_callback(callback: types.CallbackQuery, callback_data: GenCb, generator_service: GeneratorService):
    gen = await _active_gen_or_alert(callback, generator_service, callback_data.id)
    if not gen:
        return
    gen_name = gen.name

    await generator_service.set_standby(callback.from_user.id, gen_name)
    
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer(f"🟡 {gen_name} в режимі очікування!")

@router.callback_query(F.data == "stop_all_gens")
async def stop_all_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    await generator_service.stop_all(callback.from_user.id)
    
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer("🛑 Всі генератори зупинено!")

@router.callback_query(F.data == "correct_fuel_menu")
async def correction_menu(callback: types.CallbackQuery, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    back = InlineKeyboardButton(text="🔙 Скасувати", callback_data="gen_status_back")
    kb = get_generator_pick_kb(gens, "correct", footer=back)
    await callback.message.edit_text("🔧 <b>Корегування</b>\nОберіть генератор:", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.callback_query(GenCb.filter(F.action == "correct"))
async def correct_options(callback: types.CallbackQuery, callback_data: GenCb, state: FSMContext, generator_service: GeneratorService):
    gen = await _active_gen_or_alert(callback, generator_service, callback_data.id)
    if not gen:
        return
    gen_name = gen.name
    await state.update_data(gen_name=gen_name)

    text = f"⚙️ <b>{gen_name}</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"⛽ <b>Залишок:</b> {gen.fuel_level:.1f} л\n"
    text += f"🛢️ <b>Об'єм бака:</b> {gen.tank_capacity:.1f} л\n"
    text += f"📉 <b>Споживання:</b> {gen.consumption_rate:.1f} л/год\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += "Що хочете змінити?"
    
    await callback.message.edit_text(text, reply_markup=_get_correction_keyboard(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("correct_mode_"))
async def correct_init(callback: types.CallbackQuery, state: FSMContext, generator_service: GeneratorService):
    mode = callback.data.split("_")[2]
    data = await state.get_data()
    gen_name = data.get("gen_name")
    
    # Fetch current value for prompt
    gen = await generator_service.repo.get_by_name(gen_name)
    current_val = 0
    if gen:
        if mode == "fuel": current_val = gen.fuel_level
        elif mode == "tank": current_val = gen.tank_capacity
        elif mode == "rate": current_val = gen.consumption_rate

    if mode == "fuel":
        await state.set_state(GenStates.waiting_for_fuel_amount)
        txt = f"✍️ Введіть точний залишок палива (л) для <b>{gen_name}</b>:\n(Зараз встановлено: <b>{current_val:.1f}</b> л)"
    elif mode == "tank":
        await state.set_state(GenStates.waiting_for_tank_capacity)
        txt = f"✍️ Введіть об'єм бака (л) для <b>{gen_name}</b>:\n(Зараз встановлено: <b>{current_val:.1f}</b> л)"
    elif mode == "rate":
        await state.set_state(GenStates.waiting_for_consumption_rate)
        txt = f"✍️ Введіть споживання (л/год) для <b>{gen_name}</b>:\n(Зараз встановлено: <b>{current_val:.1f}</b> л/год)"
        
    await callback.message.answer(txt, parse_mode="HTML")
    await callback.answer()

@router.message(GenStates.waiting_for_fuel_amount)
async def process_correction_fuel(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    # Check if user clicked a menu button
    if message.text in MENU_BUTTONS:
        await state.clear()
        await message.answer("❌ Корегування скасовано. Оберіть пункт меню ще раз.")
        return

    try:
        liters = float(message.text.replace(",", "."))
        data = await state.get_data()
        gen_name = data.get("gen_name")
        await generator_service.correct_fuel(message.from_user.id, gen_name, liters)
        
        # Clear state but keep data for next interaction? 
        # Actually we need gen_name in state if we want to continue?
        # No, we will just show the menu and when user clicks button it will use data from callback or we need to re-save it?
        # When sending message with keyboard, the state is cleared. 
        # But correct_init expects gen_name in state?
        # Yes, correct_init uses `data = await state.get_data()`.
        # So if we clear state, we lose gen_name.
        # But wait, `correct_options` sets gen_name.
        # If we show menu again, user clicks e.g. "Tank Capacity".
        # This triggers `correct_mode_tank` -> `correct_init`.
        # `correct_init` needs `gen_name`.
        # So we MUST NOT clear the data, or we must re-set it.
        # Ideally, we stay in some state or just keep data in FSM.
        
        # We will clear state (so we are not waiting for text) but KEEP DATA.
        await state.set_state(state=None) 
        # Note: set_state(None) clears state but NOT data. state.clear() clears BOTH.
        
        await message.answer(
            f"✅ <b>Залишок оновлено!</b>\n{gen_name}: {liters}л\n\nЩо ще змінити?", 
            parse_mode="HTML",
            reply_markup=_get_correction_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введіть число (наприклад 35.5)")

@router.message(GenStates.waiting_for_tank_capacity)
async def process_correction_tank(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    try:
        if message.text in MENU_BUTTONS:
            await state.clear()
            await message.answer("❌ Корегування скасовано. Оберіть пункт меню ще раз.")
            return

        val = float(message.text.replace(",", "."))
        data = await state.get_data()
        gen_name = data.get("gen_name")
        ens = await generator_service.repo.get_by_name(gen_name)
        if not ens:
            await message.answer("❌ Генератор не знайдено. Спробуйте оновити меню.")
            await state.clear()
            return

        await generator_service.update_generator_specs(message.from_user.id, gen_name, val, ens.consumption_rate)
        
        await state.set_state(state=None) 
        
        await message.answer(
            f"✅ <b>Об'єм бака оновлено!</b>\n{gen_name}: {val}л\n\nЩо ще змінити?", 
            parse_mode="HTML",
            reply_markup=_get_correction_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введіть число")

@router.message(GenStates.waiting_for_consumption_rate)
async def process_correction_rate(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    try:
        if message.text in MENU_BUTTONS:
            await state.clear()
            await message.answer("❌ Корегування скасовано. Оберіть пункт меню ще раз.")
            return

        val = float(message.text.replace(",", "."))
        data = await state.get_data()
        gen_name = data.get("gen_name")
        ens = await generator_service.repo.get_by_name(gen_name)
        if not ens:
            await message.answer("❌ Генератор не знайдено. Спробуйте оновити меню.")
            await state.clear()
            return

        await generator_service.update_generator_specs(message.from_user.id, gen_name, ens.tank_capacity, val)
        
        await state.set_state(state=None) 
        
        await message.answer(
            f"✅ <b>Споживання оновлено!</b>\n{gen_name}: {val}л/год\n\nЩо ще змінити?", 
            parse_mode="HTML",
            reply_markup=_get_correction_keyboard()
        )
    except ValueError:
        await message.answer("❌ Введіть число")
