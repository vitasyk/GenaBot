from aiogram import Router, F, types
import html
import logging
from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton
from bot.database.repositories.user import UserRepository
from bot.keyboards.inline_kb import STALE_MENU_TEXT, GenCb, status_icon
from bot.keyboards.refuel_kb import get_refuel_kb, get_refuel_accumulator_kb
from bot.keyboards.inventory_kb import get_inventory_kb
from bot.services.antigel import format_advice
from bot.services.generator import GeneratorService
from bot.services.inventory import LITERS_PER_CAN, InventoryService
from bot.utils.clock import now_local, utc_to_local
from aiogram.fsm.context import FSMContext
from bot.states import RefuelAccumulatorStates

router = Router()

ANTIGEL_WARNING_MARK = "⚠️ УВАГА: ПОТРІБНА ПРИСАДКА!"

REFUEL_PROMPT = "Куди заправляємо?"
NO_ACTIVE_GENERATORS = "Немає активних генераторів. Адміністратор може увімкнути їх в адмін-панелі → ⚙️ Генератори."


async def _stock_text(inventory_service: InventoryService) -> str:
    """Stock overview shown by "📦 Склад" and every screen that returns to it."""
    stats = await inventory_service.get_detailed_stats()
    current_week_usage = await inventory_service.get_current_week_usage()
    avg_h = stats["avg_hourly_consumption"]
    hours_left = stats["hours_left"]

    text = "📦 <b>Склад палива</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"🛒 Залишок: <b>{stats['stock_cans']:.2f}</b> каністр\n"
    text += f"💧 Обсяг: {stats['stock_liters']} літрів\n\n"

    if stats["last_refill_date"]:
        text += f"📅 Останнє поповнення: {utc_to_local(stats['last_refill_date']).strftime('%d.%m.%Y')}\n"

    if avg_h > 0.001:
        days_left = hours_left / 24.0
        text += f"📉 Тиждень (Пн-Нд): <b>{current_week_usage:.1f}</b> л\n"
        text += f"📉 Останні 7 днів: <b>{stats['total_weekly_consumption']:.1f}</b> л\n"
        text += f"📊 Сер. витрата (доба): <b>{stats['avg_daily_consumption']:.1f}</b> л\n"
        text += f"📊 Сер. витрата: ~<b>{avg_h:.2f}</b> л/год ⏳\n"
        text += f" Вистачить на: ~<b>{hours_left:.1f}</b> год"
        if days_left >= 1.0:
            text += f" (≈{days_left:.1f} дн.)"
        text += "\n"
    else:
        text += "📉 Витрата: Немає даних (останні 7 днів)\n"

    text += "➖➖➖➖➖➖➖➖➖➖"
    return text


@router.message(F.text == "📦 Склад")
async def check_stock(message: types.Message, inventory_service: InventoryService):
    from bot.config import config
    is_admin = message.from_user.id in config.ADMIN_IDS
    text = await _stock_text(inventory_service)
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
    from datetime import timedelta
    builder = InlineKeyboardBuilder()
    now = now_local()  # Kyiv date: the container clock is UTC

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

@router.callback_query(F.data == "stock_history")
async def stock_history_callback(callback: types.CallbackQuery, inventory_service: InventoryService):
    from bot.config import config
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Тільки для адміністраторів", show_alert=True)
        return

    history = await inventory_service.get_consumption_history(limit=10)

    if not history:
        await callback.answer("ℹ️ Історія порожня", show_alert=True)
        return

    text = "📜 <b>Історія витрат (останні 10)</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"

    for item in history:
        dt = utc_to_local(item['date']).strftime('%d.%m %H:%M')
        amount = item['amount']
        user = item['user']
        # Try to clean up amount string if it contains "Taken: "
        if "Taken: " in str(amount):
            amount = str(amount).replace("Taken: ", "")

        text += f"⛽ <b>{amount}</b>л | {dt}\n"
        text += f"👤 {user}\n"
        text += "------------------\n"

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="stock_back_to_main"))

    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "stock_back_to_main")
async def stock_back_handler(callback: types.CallbackQuery, inventory_service: InventoryService):
    from bot.config import config
    is_admin = callback.from_user.id in config.ADMIN_IDS
    text = await _stock_text(inventory_service)
    await callback.message.edit_text(text, reply_markup=get_inventory_kb(is_admin), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data.startswith("stock_set_date_"))
async def stock_process_date_callback(callback: types.CallbackQuery, inventory_service: InventoryService):
    from bot.config import config
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Тільки для адміністраторів", show_alert=True)
        return

    date_str = callback.data.replace("stock_set_date_", "")
    from datetime import datetime
    new_date = datetime.strptime(date_str, "%Y-%m-%d")

    success = await inventory_service.update_last_refill_date(callback.from_user.id, new_date)

    if success:
        await callback.answer(f"✅ Дату змінено на {new_date.strftime('%d.%m')}")
        # Return to main inventory view
        await stock_back_handler(callback, inventory_service)
    else:
        await callback.answer("❌ Помилка: лог поповнення не знайдено", show_alert=True)

@router.callback_query(F.data.in_({"stock_add_1", "stock_add_5", "stock_dec_1"}))
async def stock_control_callback(callback: types.CallbackQuery, inventory_service: InventoryService):
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
        await inventory_service.take_fuel(callback.from_user.id, abs(amount) * LITERS_PER_CAN)
        msg = f"✅ Вилучено {abs(amount)} шт."

    text = await _stock_text(inventory_service)
    try:
        await callback.message.edit_text(text, reply_markup=get_inventory_kb(is_admin=True), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer(msg)

@router.message(F.text == "⛽ Заправити")
async def take_fuel_prompt(message: types.Message, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    if not gens:
        await message.answer(NO_ACTIVE_GENERATORS)
        return
    await message.answer(REFUEL_PROMPT, reply_markup=get_refuel_kb(gens))

@router.callback_query(GenCb.filter(F.action == "refuel"))
async def select_gen_step(callback: types.CallbackQuery, callback_data: GenCb, state: FSMContext, generator_service: GeneratorService):
    gen = await generator_service.get_active(callback_data.id)
    if not gen:
        await callback.answer(STALE_MENU_TEXT, show_alert=True)
        return

    # Initialize accumulator mode
    await state.set_state(RefuelAccumulatorStates.accumulating)
    await state.update_data(gen_id=gen.id, gen_name=gen.name, accumulated_liters=0)

    await callback.message.edit_text(
        f"⛽ <b>{gen.name}</b>\n\nДодайте паливо:\n📊 Всього: 0 л",
        reply_markup=get_refuel_accumulator_kb(),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(RefuelAccumulatorStates.accumulating, F.data.startswith("refuel_add_"))
async def refuel_add_increment(callback: types.CallbackQuery, state: FSMContext):
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
        reply_markup=get_refuel_accumulator_kb(),
        parse_mode="HTML"
    )
    await callback.answer(f"+{increment}л")

# startswith: buttons sent before the switch to generator ids carry "refuel_acc_done_<name>"
@router.callback_query(RefuelAccumulatorStates.accumulating, F.data.startswith("refuel_acc_done"))
async def refuel_accumulator_done(callback: types.CallbackQuery, state: FSMContext, inventory_service: InventoryService, generator_service: GeneratorService):
    data = await state.get_data()
    total_liters = data.get("accumulated_liters", 0)

    # Validate minimum amount (state stays so the user can keep adding)
    if total_liters <= 0:
        await callback.answer("⚠️ Додайте хоча б трохи палива!", show_alert=True)
        return

    await state.clear()

    gen_id = data.get("gen_id")
    gen = await generator_service.get_active(gen_id) if gen_id else None
    if not gen:
        await callback.answer(STALE_MENU_TEXT, show_alert=True)
        return
    gen_name = gen.name

    try:
        # 1. Take EXACT liters from stock
        new_amount_liters = await inventory_service.take_fuel(callback.from_user.id, total_liters)
        # 2. Add specific liters to Generator
        await generator_service.log_refuel(callback.from_user.id, gen_name, total_liters)
    except Exception:
        # Re-raise so DbSessionMiddleware rolls back: never keep stock taken without the generator refuelled
        logging.exception("Refuel failed: user_id=%s gen=%s liters=%s", callback.from_user.id, gen_name, total_liters)
        await callback.message.answer("❌ Не вдалося записати заправку, зміни скасовано. Спробуйте ще раз.")
        await callback.answer()
        raise

    new_amount_cans = new_amount_liters / LITERS_PER_CAN

    # 3. Check Anti-Gel Threshold
    kb_buttons = [
        [types.InlineKeyboardButton(text="❌ Закрити", callback_data="refuel_close")]
    ]
    antigel_warning = ""
    advice = await generator_service.antigel.advise_for(gen)  # gen already counts the poured litres
    if advice.needed:
        antigel_warning = f"\n\n<b>{ANTIGEL_WARNING_MARK}</b>\n{format_advice(gen.name, advice)}"
        kb_buttons.insert(0, [
            types.InlineKeyboardButton(text="✅ Присадку додано", callback_data=GenCb(action="antigel", id=gen.id).pack())
        ])

    text = "✅ <b>Заправка успішна!</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"⛽ {status_icon(gen.status)} <b>{gen_name}</b> +{total_liters}л\n"
    text += f"📦 Залишок: <b>{new_amount_cans:.2f}</b> каністр"
    text += antigel_warning

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    )
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

@router.callback_query(GenCb.filter(F.action == "antigel"))
async def process_antigel_reset(callback: types.CallbackQuery, callback_data: GenCb, generator_service: GeneratorService):
    gen = await generator_service.get_by_id(callback_data.id)
    if not gen:
        await callback.answer(STALE_MENU_TEXT, show_alert=True)
        return
    await generator_service.reset_antigel(callback.from_user.id, gen.name)

    # Update message to remove warning
    text = callback.message.text
    if ANTIGEL_WARNING_MARK in text:
        # The warning block is the tail of the message; message.text is plain, so escape it again
        new_text = html.escape(text.split(ANTIGEL_WARNING_MARK)[0].rstrip()) + "\n\n✅ <b>Присадку додано!</b>"

        await callback.message.edit_text(
            new_text,
            parse_mode="HTML",
            reply_markup=types.InlineKeyboardMarkup(inline_keyboard=[[
                types.InlineKeyboardButton(text="❌ Закрити", callback_data="refuel_close")
            ]])
        )

    await callback.answer("Дані оновлено!")


@router.callback_query(F.data == "fuel_back")
async def back_to_gen_select(callback: types.CallbackQuery, state: FSMContext, generator_service: GeneratorService):
    await state.clear()
    gens = await generator_service.get_status()
    await callback.message.edit_text(REFUEL_PROMPT, reply_markup=get_refuel_kb(gens))
    await callback.answer()
