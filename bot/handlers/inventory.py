from aiogram import Router, F, types
import logging
from bot.database.models import UserRole, GenStatus
from bot.database.repositories.user import UserRepository
from bot.keyboards.refuel_kb import get_refuel_kb, get_amount_kb
from bot.keyboards.inventory_kb import get_inventory_kb
from bot.services.generator import GeneratorService
from bot.services.inventory import InventoryService
from aiogram.fsm.context import FSMContext
from bot.states import InventoryStates

router = Router()

@router.message(F.text == "📦 Склад")
async def check_stock(message: types.Message, inventory_service: InventoryService, user_repo: UserRepository):
    user = await user_repo.get_by_id(message.from_user.id)
    is_admin = user and user.role == UserRole.admin
    
    stats = await inventory_service.get_detailed_stats()
    
    stock_liters = stats["stock_liters"]
    stock_cans = stats["stock_cans"]
    last_refill = stats["last_refill_date"]
    avg_h = stats["avg_hourly_consumption"]
    hours_left = stats["hours_left"]
    
    text = "📦 <b>Склад палива</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"🛒 Каністри: <b>{stock_cans:.2f}</b> шт.\n"
    text += f"💧 Обсяг: {stock_liters} літрів\n\n"
    
    if last_refill:
        text += f"📅 Останнє поповнення: {last_refill.strftime('%d.%m.%Y')}\n"
    
    if avg_h > 0.001:
        text += f"📉 Середня витрата: ~<b>{avg_h:.2f}</b> л/год\n"
        text += f"⏳ Вистачить на: ~<b>{hours_left:.1f}</b> год\n"
    else:
        text += "📉 Витрата: Немає даних (останні 7 днів)\n"
        
    text += "➖➖➖➖➖➖➖➖➖➖"
    await message.answer(text, reply_markup=get_inventory_kb(is_admin), parse_mode="HTML")

@router.callback_query(F.data == "stock_close")
async def stock_close_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@router.callback_query(F.data.startswith("stock_"))
async def stock_control_callback(callback: types.CallbackQuery, inventory_service: InventoryService, user_repo: UserRepository):
    user = await user_repo.get_by_id(callback.from_user.id)
    if not user or user.role != UserRole.admin:
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
    text += f"🛒 Каністри: <b>{stats['stock_cans']:.2f}</b> шт.\n"
    text += f"💧 Обсяг: {stats['stock_liters']} літрів\n\n"
    
    if stats["last_refill_date"]:
        text += f"📅 Останнє поповнення: {stats['last_refill_date'].strftime('%d.%m.%Y')}\n"
    
    if stats["avg_hourly_consumption"] > 0.001:
        text += f"📉 Середня витрата: ~<b>{stats['avg_hourly_consumption']:.2f}</b> л/год\n"
        text += f"⏳ Вистачить на: ~<b>{stats['hours_left']:.1f}</b> год\n"
        
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
async def select_gen_step(callback: types.CallbackQuery):
    target = callback.data.split("_")[2] # GEN-1, GEN-2, OTHER
    
    if target == "OTHER":
        # Just confirm taking can, no generator update
        # We need a new state or direct confirmation? 
        # Let's handle OTHER directly here via a confirm call or just do it.
        # To reuse logic, let's just make a special callback or direct call.
        # Simpler: If OTHER, no amount needed.
        # But we need access to services which are in the next handler usually? 
        # Actually handlers have DI.
        # We can't call another handler easily without FSM or trickery.
        # Let's separate logic.
        pass # Handle below in a specific handler or unified regex
        
    await callback.message.edit_text(f"Вибрано <b>{target}</b>\nСкільки літрів?", reply_markup=get_amount_kb(target), parse_mode="HTML")
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
