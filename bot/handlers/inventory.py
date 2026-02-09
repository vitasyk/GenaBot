from aiogram import Router, F, types
import logging
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from bot.database.models import UserRole, GenStatus
from bot.database.repositories.user import UserRepository
from bot.keyboards.refuel_kb import get_refuel_kb, get_amount_kb
from bot.keyboards.inventory_kb import get_inventory_kb
from bot.services.generator import GeneratorService
from bot.services.inventory import InventoryService
from aiogram.fsm.context import FSMContext
from bot.states import InventoryStates, RefuelAccumulatorStates

router = Router()

@router.message(F.text == "📦 Склад")
async def check_stock(message: types.Message, inventory_service: InventoryService, user_repo: UserRepository):
    from bot.config import config
    is_admin = message.from_user.id in config.ADMIN_IDS
    
    stats = await inventory_service.get_detailed_stats()
    
    stock_liters = stats["stock_liters"]
    stock_cans = stats["stock_cans"]
    last_refill = stats["last_refill_date"]
    avg_h = stats["avg_hourly_consumption"]
    total_w = stats["total_weekly_consumption"]
    hours_left = stats["hours_left"]
    
    text = "📦 <b>Склад палива</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"🛒 Залишок: <b>{stock_cans:.2f}</b> каністр\n"
    text += f"💧 Обсяг: {stock_liters} літрів\n\n"
    
    if last_refill:
        text += f"📅 Останнє поповнення: {last_refill.strftime('%d.%m.%Y')}\n"
    
    if avg_h > 0.001:
        days_left = hours_left / 24.0
        text += f"📉 Витрачено за 7 днів: <b>{total_w:.1f}</b> л\n"
        text += f"📊 Сер. витрата (доба): <b>{stats['avg_daily_consumption']:.1f}</b> л\n"
        text += f"📊 Сер. витрата: ~<b>{avg_h:.2f}</b> л/год ⏳\n"
        text += f" Вистачить на: ~<b>{hours_left:.1f}</b> год"
        if days_left >= 1.0:
            text += f" (≈{days_left:.1f} дн.)"
        text += "\n"
    else:
        text += "📉 Витрата: Немає даних (останні 7 днів)\n"
        
    text += "➖➖➖➖➖➖➖➖➖➖"
    await message.answer(text, reply_markup=get_inventory_kb(is_admin), parse_mode="HTML")

@router.callback_query(F.data == "stock_close")
async def stock_close_callback(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()

@router.callback_query(F.data == "stock_correct_date")
async def stock_date_selector_callback(callback: types.CallbackQuery, user_repo: UserRepository):
    from bot.config import config
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Тільки для адміністраторів", show_alert=True)
        return

    # Generate dates for the last 7 days
    from datetime import datetime, timedelta
    builder = InlineKeyboardBuilder()
    now = datetime.now()
    
    # 2 rows of 4 buttons
    for i in range(7):
        dt = now - timedelta(days=i)
        label = "Сьогодні" if i == 0 else "Вчора" if i == 1 else dt.strftime("%d.%m")
        builder.add(InlineKeyboardButton(text=label, callback_data=f"stock_set_date_{dt.strftime('%Y-%m-%d')}"))
    
    builder.adjust(4)
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="stock_back_to_main"))

    await callback.message.edit_text(
        "📅 <b>Корегування дати поповнення</b>\n"
        "Оберіть дату останнього надходження палива (ADD_FUEL):",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "stock_back_to_main")
async def stock_back_handler(callback: types.CallbackQuery, inventory_service: InventoryService, user_repo: UserRepository):
    # Reuse check_stock logic but via edit_text
    from bot.config import config
    is_admin = callback.from_user.id in config.ADMIN_IDS
    stats = await inventory_service.get_detailed_stats()
    

    text = "📦 <b>Склад палива</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"🛒 Залишок: <b>{stats['stock_cans']:.2f}</b> каністр\n"
    text += f"💧 Обсяг: {stats['stock_liters']} літрів\n\n"
    
    if stats["last_refill_date"]:
        text += f"📅 Останнє поповнення: {stats['last_refill_date'].strftime('%d.%m.%Y')}\n"
    
    if stats["avg_hourly_consumption"] > 0.001:
        hours_left = stats['hours_left']
        days_left = hours_left / 24.0
        text += f"📉 Витрачено за 7 днів: <b>{stats['total_weekly_consumption']:.1f}</b> л\n"
        text += f"📊 Сер. витрата (доба): <b>{stats['avg_daily_consumption']:.1f}</b> л\n"
        text += f"📊 Сер. витрата: ~<b>{stats['avg_hourly_consumption']:.2f}</b> л/год ⏳\n"
        text += f" Вистачить на: ~<b>{hours_left:.1f}</b> год"
        if days_left >= 1.0:
            text += f" (≈{days_left:.1f} дн.)"
        text += "\n"
    else:
        text += "📉 Витрата: Немає даних (останні 7 днів)\n"
        
    text += "➖➖➖➖➖➖➖➖➖➖"
    await callback.message.edit_text(text, reply_markup=get_inventory_kb(is_admin), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("stock_set_date_"))
async def stock_process_date_callback(callback: types.CallbackQuery, inventory_service: InventoryService, user_repo: UserRepository):
    date_str = callback.data.replace("stock_set_date_", "")
    from datetime import datetime
    new_date = datetime.strptime(date_str, "%Y-%m-%d")
    
    success = await inventory_service.update_last_refill_date(callback.from_user.id, new_date)
    
    if success:
        await callback.answer(f"✅ Дату змінено на {new_date.strftime('%d.%m')}")
        # Return to main inventory view
        await stock_back_handler(callback, inventory_service, user_repo)
    else:
        await callback.answer("❌ Помилка: лог поповнення не знайдено", show_alert=True)

@router.callback_query(F.data.in_({"stock_add_1", "stock_add_5", "stock_dec_1"}))
async def stock_control_callback(callback: types.CallbackQuery, inventory_service: InventoryService, user_repo: UserRepository):
    from bot.config import config
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Тільки для адміністраторів", show_alert=True)
        return

    action = callback.data
    amount = 0
    if action == "stock_add_1": amount = 1
    elif action == "stock_add_5": amount = 5
    elif action == "stock_dec_1": amount = -1
    
    if amount > 0:
        await inventory_service.add_cans(callback.from_user.id, amount)
        msg = f"✅ Додано {amount} шт."
    else:
        await inventory_service.take_fuel(callback.from_user.id, abs(amount) * 20)
        msg = f"✅ Вилучено {abs(amount)} шт."

    stats = await inventory_service.get_detailed_stats()
    

    text = "📦 <b>Склад палива</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"🛒 Залишок: <b>{stats['stock_cans']:.2f}</b> каністр\n"
    text += f"💧 Обсяг: {stats['stock_liters']} літрів\n\n"
    
    if stats["last_refill_date"]:
        text += f"📅 Останнє поповнення: {stats['last_refill_date'].strftime('%d.%m.%Y')}\n"
    
    if stats["avg_hourly_consumption"] > 0.001:
        hours_left = stats['hours_left']
        days_left = hours_left / 24.0
        text += f"📉 Витрачено за 7 днів: <b>{stats['total_weekly_consumption']:.1f}</b> л\n"
        text += f"📊 Сер. витрата (доба): <b>{stats['avg_daily_consumption']:.1f}</b> л\n"
        text += f"📊 Сер. витрата: ~<b>{stats['avg_hourly_consumption']:.2f}</b> л/год ⏳\n"
        text += f" Вистачить на: ~<b>{hours_left:.1f}</b> год"
        if days_left >= 1.0:
            text += f" (≈{days_left:.1f} дн.)"
        text += "\n"
        
    text += "➖➖➖➖➖➖➖➖➖➖"

    try:
        await callback.message.edit_text(text, reply_markup=get_inventory_kb(is_admin=True), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer(msg)

@router.message(F.text == "⛽ Заправити")
async def take_fuel_prompt(message: types.Message):
    await message.answer("Куди заправляємо?", reply_markup=get_refuel_kb())

@router.callback_query(F.data.startswith("refuel_select_"))
async def select_gen_step(callback: types.CallbackQuery, state: FSMContext):
    from bot.keyboards.refuel_kb import get_refuel_accumulator_kb
    from bot.states import RefuelAccumulatorStates
    
    target = callback.data.split("_")[2]  # Extract gen name
    
    # Initialize accumulator mode
    await state.set_state(RefuelAccumulatorStates.accumulating)
    await state.update_data(gen_name=target, accumulated_liters=0)
    
    await callback.message.edit_text(
        f"⛽ <b>{target}</b>\n\nДодайте паливо:\n📊 Всього: 0 л",
        reply_markup=get_refuel_accumulator_kb(target, 0),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(RefuelAccumulatorStates.accumulating, F.data.startswith("refuel_add_"))
async def refuel_add_increment(callback: types.CallbackQuery, state: FSMContext):
    from bot.keyboards.refuel_kb import get_refuel_accumulator_kb
    
    # Extract increment amount
    increment = int(callback.data.split("_")[2])
    
    # Get current data
    data = await state.get_data()
    gen_name = data.get("gen_name")
    current_total = data.get("accumulated_liters", 0)
    
    # Add increment
    new_total = current_total + increment
    await state.update_data(accumulated_liters=new_total)
    
    # Update message with new total
    await callback.message.edit_text(
        f"⛽ <b>{gen_name}</b>\n\nДодайте паливо:\n📊 Всього: {new_total} л",
        reply_markup=get_refuel_accumulator_kb(gen_name, new_total),
        parse_mode="HTML"
    )
    await callback.answer(f"+{increment}л")

@router.callback_query(RefuelAccumulatorStates.accumulating, F.data.startswith("refuel_acc_done_"))
async def refuel_accumulator_done(callback: types.CallbackQuery, state: FSMContext, inventory_service: InventoryService, generator_service: GeneratorService):
    # Get accumulated data
    data = await state.get_data()
    gen_name = data.get("gen_name")
    total_liters = data.get("accumulated_liters", 0)
    
    # Clear FSM state
    await state.clear()
    
    # Validate minimum amount
    if total_liters <= 0:
        await callback.answer("⚠️ Додайте хоча б трохи палива!", show_alert=True)
        return
    
    # Call existing refuel logic
    try:
        # 1. Take EXACT liters from stock
        new_amount_liters = await inventory_service.take_fuel(callback.from_user.id, total_liters)
        new_amount_cans = new_amount_liters / 20.0
        
        # 2. Add specific liters to Generator
        await generator_service.log_refuel(callback.from_user.id, gen_name, total_liters)
             
        # 3. Check Anti-Gel Threshold
        gen = await generator_service.repo.get_by_name(gen_name)
        antigel_warning = ""
        kb_buttons = [
            [types.InlineKeyboardButton(text="❌ Закрити", callback_data="refuel_close")]
        ]
        
        if gen and gen.fuel_since_antigel >= 80:
            antigel_warning = f"\n\n⚠️ <b>УВАГА: ПОТРІБНА ПРИСАДКА!</b>\nНакопичено <b>{gen.fuel_since_antigel:.1f}л</b> палива. Будь ласка, додайте Anti-Gel!"
            kb_buttons.insert(0, [
                types.InlineKeyboardButton(text="✅ Присадку додано", callback_data=f"antigel_reset_{gen_name}")
            ])
             
        text = "✅ <b>Заправка успішна!</b>\n"
        text += "➖➖➖➖➖➖➖➖➖➖\n"
        
        # Determine current status icon
        status_icon = "🔴"
        if gen and gen.status == GenStatus.running: status_icon = "🟢"
        elif gen and gen.status == GenStatus.standby: status_icon = "🟡"
        
        text += f"⛽ {status_icon} <b>{gen_name}</b> +{total_liters}л\n"
        text += f"📦 Залишок: <b>{new_amount_cans:.2f}</b> каністр"
        text += antigel_warning
        
        await callback.message.edit_text(
            text, 
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Refuel error: {e}")
        await callback.message.answer(f"❌ Помилка: {e}")
        await callback.answer()

@router.callback_query(RefuelAccumulatorStates.accumulating, F.data == "refuel_acc_cancel")
async def refuel_accumulator_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("↩️ Заправку скасовано.")
    await callback.answer()

@router.callback_query(F.data == "refuel_close")
async def process_refuel_close(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@router.callback_query(F.data.startswith("refuel_confirm_"))
async def process_refuel_confirm(callback: types.CallbackQuery, inventory_service: InventoryService, generator_service: GeneratorService):
    # Format: refuel_confirm_GEN-1_20
    parts = callback.data.split("_")
    gen_name = parts[2]
    liters = int(parts[3])
    
    try:
        # 1. Take EXACT liters from stock
        new_amount_liters = await inventory_service.take_fuel(callback.from_user.id, liters)
        new_amount_cans = new_amount_liters / 20.0
        
        # 2. Add specific liters to Generator
        await generator_service.log_refuel(callback.from_user.id, gen_name, liters)
             
        # 3. Check Anti-Gel Threshold
        gen = await generator_service.repo.get_by_name(gen_name)
        antigel_warning = ""
        kb_buttons = [
            [types.InlineKeyboardButton(text="❌ Закрити", callback_data="refuel_close")]
        ]
        
        if gen and gen.fuel_since_antigel >= 80:
            antigel_warning = f"\n\n⚠️ <b>УВАГА: ПОТРІБНА ПРИСАДКА!</b>\nНакопичено <b>{gen.fuel_since_antigel:.1f}л</b> палива. Будь ласка, додайте Anti-Gel!"
            kb_buttons.insert(0, [
                types.InlineKeyboardButton(text="✅ Присадку додано", callback_data=f"antigel_reset_{gen_name}")
            ])
             
        text = "✅ <b>Заправка успішна!</b>\n"
        text += "➖➖➖➖➖➖➖➖➖➖\n"
        
        # Determine current status icon
        status_icon = "🔴"
        if gen and gen.status == GenStatus.running: status_icon = "🟢"
        elif gen and gen.status == GenStatus.standby: status_icon = "🟡"
        
        text += f"⛽ {status_icon} <b>{gen_name}</b> +{liters}л\n"
        text += f"📦 Залишок: <b>{new_amount_cans:.2f}</b> каністр"
        text += antigel_warning
        
        await callback.message.edit_text(
            text, 
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_buttons)
        )
        await callback.answer()
    except Exception as e:
        logging.error(f"Refuel error: {e}")
        await callback.message.answer(f"❌ Помилка: {e}")
        await callback.answer()

@router.callback_query(F.data.startswith("antigel_reset_"))
async def process_antigel_reset(callback: types.CallbackQuery, generator_service: GeneratorService):
    gen_name = callback.data.replace("antigel_reset_", "")
    await generator_service.reset_antigel(callback.from_user.id, gen_name)
    
    # Update message to remove warning
    text = callback.message.text
    if "⚠️ УВАГА: ПОТРІБНА ПРИСАДКА!" in text:
        # Simple cleanup of the warning block
        lines = text.split("\n")
        new_lines = [l for l in lines if "ПОТРІБНА ПРИСАДКА" not in l and "Накопичено" not in l and "додайте Anti-Gel" not in l]
        # Remove empty lines at the end
        while new_lines and not new_lines[-1].strip():
            new_lines.pop()
        
        new_text = "\n".join(new_lines) + "\n\n✅ <b>Присадку додано!</b>"
        
        await callback.message.edit_text(
            new_text,
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="❌ Закрити", callback_data="refuel_close")
            ]])
        )
    
    await callback.answer("Дані оновлено!")


@router.callback_query(F.data == "fuel_back")
async def back_to_gen_select(callback: types.CallbackQuery):
    await callback.message.edit_text("Куди заправляємо?", reply_markup=get_refuel_kb())
