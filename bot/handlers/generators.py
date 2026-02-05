from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from bot.states import GenStates
from bot.services.generator import GeneratorService
from bot.keyboards.inline_kb import get_generator_control_kb
from bot.database.models import GenStatus, UserRole
from bot.database.repositories.user import UserRepository
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

router = Router()

async def _get_status_panel(generator_service: GeneratorService, with_keyboard: bool = True, exclude_correction: bool = False):
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
                  text += f"   🕒 <b>Запущено о:</b> {g.current_run_start.strftime('%H:%M')}\n"
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
    
    kb = get_generator_control_kb(exclude_correction=exclude_correction) if with_keyboard else None
    
    if kb:
        # Add Notification Toggle Button
        notify_status = await generator_service.get_notify_start_status()
        text_status = "🔔 Сповіщення: ON" if notify_status else "🔕 Сповіщення: OFF"
        # Access internal list to append row (Standard aiogram Type)
        kb.inline_keyboard.append([InlineKeyboardButton(text=text_status, callback_data="toggle_notify_start")])
        
    return text, kb

@router.callback_query(F.data == "toggle_notify_start")
async def toggle_notify_handler(callback: types.CallbackQuery, generator_service: GeneratorService):
    new_state = await generator_service.toggle_notify_start()
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    state_str = "увімкнено" if new_state else "вимкнено"
    await callback.answer(f"Сповіщення {state_str}!")

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

@router.message(F.text == "🔄 Керування")
async def switch_gen_menu(message: types.Message, user_repo: UserRepository):
    user = await user_repo.get_by_id(message.from_user.id)
    if not user or user.role != UserRole.admin:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return

    await message.answer("Оберіть дію:", reply_markup=get_generator_control_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("start_gen_"))
async def start_generator_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    gen_names = {"start_gen_1": "GEN-1 (003)", "start_gen_2": "GEN-2 (036) WILSON"}
    gen_name = gen_names.get(callback.data)
    if not gen_name:
        await callback.answer("Помилка: Генератор не знайдений")
        return
        
    # Check for warming recommendation
    warm_rec = await generator_service.get_warming_recommendation(gen_name)
    warning_text = ""
    if warm_rec:
        warning_text = f"\n\n{warm_rec}"
        
    await generator_service.start_generator(callback.from_user.id, gen_name)
    
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text + warning_text, reply_markup=kb, parse_mode="HTML")
    await callback.answer(f"✅ {gen_name} запущено!")

@router.callback_query(F.data.startswith("standby_gen_"))
async def standby_generator_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    gen_names = {"standby_gen_1": "GEN-1 (003)", "standby_gen_2": "GEN-2 (036) WILSON"}
    gen_name = gen_names.get(callback.data)
    if not gen_name:
        await callback.answer("Помилка: Генератор не знайдений")
        return
        
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
async def correction_menu(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="GEN-1 (003)", callback_data="correct_select_GEN-1 (003)"),
        InlineKeyboardButton(text="GEN-2 (036) WILSON", callback_data="correct_select_GEN-2 (036) WILSON")
    )
    builder.row(InlineKeyboardButton(text="🔙 Скасувати", callback_data="gen_status_back")) 
    
    await callback.message.edit_text("🔧 <b>Корегування</b>\nОберіть генератор:", reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "gen_status_back")
async def back_to_status_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    text, kb = await _get_status_panel(generator_service, exclude_correction=True)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("correct_select_"))
async def correct_options(callback: types.CallbackQuery, state: FSMContext):
    gen_name = callback.data.split("_")[2]
    await state.update_data(gen_name=gen_name)
    
    await callback.message.edit_text(f"⚙️ <b>{gen_name}</b>\nЩо хочете змінити?", reply_markup=_get_correction_keyboard(), parse_mode="HTML")

@router.callback_query(F.data.startswith("correct_mode_"))
async def correct_init(callback: types.CallbackQuery, state: FSMContext):
    mode = callback.data.split("_")[2]
    data = await state.get_data()
    gen_name = data.get("gen_name")
    
    if mode == "fuel":
        await state.set_state(GenStates.waiting_for_fuel_amount)
        txt = f"✍️ Введіть точний залишок палива (л) для <b>{gen_name}</b>:"
    elif mode == "tank":
        await state.set_state(GenStates.waiting_for_tank_capacity)
        txt = f"✍️ Введіть об'єм бака (л) для <b>{gen_name}</b>:"
    elif mode == "rate":
        await state.set_state(GenStates.waiting_for_consumption_rate)
        txt = f"✍️ Введіть споживання (л/год) для <b>{gen_name}</b>:"
        
    await callback.message.answer(txt, parse_mode="HTML")
    await callback.answer()

@router.message(GenStates.waiting_for_fuel_amount)
async def process_correction_fuel(message: types.Message, state: FSMContext, generator_service: GeneratorService):
    # Check if user clicked a menu button
    if message.text in ["⛽ Заправити", "📦 Склад", "⚡ Статус", "🌡️ Прогноз", "🔄 Керування", "🆘 Інструкція (SOS)", "📊 Адмін-панель"]:
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
        if message.text in ["⛽ Заправити", "📦 Склад", "⚡ Статус", "🌡️ Прогноз", "🔄 Керування", "🆘 Інструкція (SOS)", "📊 Адмін-панель"]:
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
        if message.text in ["⛽ Заправити", "📦 Склад", "⚡ Статус", "🌡️ Прогноз", "🔄 Керування", "🆘 Інструкція (SOS)", "📊 Адмін-панель"]:
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
