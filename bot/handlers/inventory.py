import html
import logging

from aiogram import Router, F, types
from aiogram.exceptions import TelegramBadRequest

from bot.database.models import UserRole
from bot.database.repositories.user import UserRepository
from bot.generator_specs import LITERS_PER_CAN
from bot.keyboards.callbacks import GenCallback, RefuelAmountCallback
from bot.keyboards.inventory_kb import get_inventory_kb
from bot.keyboards.refuel_kb import get_refuel_kb, get_amount_kb
from bot.services.generator import GeneratorService
from bot.services.inventory import InventoryService

router = Router()

STOCK_CHANGES_IN_CANS = {"stock_add_1": 1, "stock_add_5": 5, "stock_dec_1": -1}


def _stock_text(stats: dict) -> str:
    text = "📦 <b>Склад палива</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"🛒 Каністри: <b>{stats['stock_cans']:.2f}</b> шт.\n"
    text += f"💧 Обсяг: {stats['stock_liters']} літрів\n\n"

    if stats["last_refill_date"]:
        text += f"📅 Останнє поповнення: {stats['last_refill_date'].strftime('%d.%m.%Y')}\n"

    if stats["avg_hourly_consumption"] > 0.001:
        text += f"📉 Середня витрата: ~<b>{stats['avg_hourly_consumption']:.2f}</b> л/год\n"
        text += f"⏳ Вистачить на: ~<b>{stats['hours_left']:.1f}</b> год\n"
    else:
        text += "📉 Витрата: Немає даних (останні 7 днів)\n"

    text += "➖➖➖➖➖➖➖➖➖➖"
    return text


@router.message(F.text == "📦 Склад")
async def check_stock(message: types.Message, inventory_service: InventoryService, user_repo: UserRepository):
    user = await user_repo.get_by_id(message.from_user.id)
    is_admin = bool(user and user.role == UserRole.admin)

    stats = await inventory_service.get_detailed_stats()
    await message.answer(_stock_text(stats), reply_markup=get_inventory_kb(is_admin), parse_mode="HTML")

@router.callback_query(F.data == "stock_close")
async def stock_close_callback(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@router.callback_query(F.data.in_(STOCK_CHANGES_IN_CANS.keys()))
async def stock_control_callback(callback: types.CallbackQuery, inventory_service: InventoryService, user_repo: UserRepository):
    user = await user_repo.get_by_id(callback.from_user.id)
    if not user or user.role != UserRole.admin:
        await callback.answer("⛔ Тільки для адміністраторів", show_alert=True)
        return

    cans = STOCK_CHANGES_IN_CANS[callback.data]
    if cans > 0:
        await inventory_service.add_cans(callback.from_user.id, cans)
        msg = f"✅ Додано {cans} шт."
    else:
        await inventory_service.take_fuel(callback.from_user.id, abs(cans) * LITERS_PER_CAN)
        msg = f"✅ Вилучено {abs(cans)} шт."

    stats = await inventory_service.get_detailed_stats()
    try:
        await callback.message.edit_text(_stock_text(stats), reply_markup=get_inventory_kb(is_admin=True), parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer(msg)

@router.message(F.text == "⛽ Заправити")
async def take_fuel_prompt(message: types.Message, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await message.answer("Куди заправляємо?", reply_markup=get_refuel_kb(gens))

@router.callback_query(GenCallback.filter(F.action == "refuel"))
async def select_gen_step(callback: types.CallbackQuery, callback_data: GenCallback, generator_service: GeneratorService):
    gen = await generator_service.get_active(callback_data.gen_id)
    if not gen:
        await callback.answer("Генератор не знайдено або його вимкнено", show_alert=True)
        return

    await callback.message.edit_text(
        f"Вибрано <b>{html.escape(gen.name)}</b>\nСкільки літрів?",
        reply_markup=get_amount_kb(gen.id),
        parse_mode="HTML"
    )
    await callback.answer()

@router.callback_query(F.data == "refuel_close")
async def process_refuel_close(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@router.callback_query(RefuelAmountCallback.filter())
async def process_refuel_confirm(callback: types.CallbackQuery, callback_data: RefuelAmountCallback,
                                 inventory_service: InventoryService, generator_service: GeneratorService):
    gen = await generator_service.get_active(callback_data.gen_id)
    if not gen:
        await callback.answer("Генератор не знайдено або його вимкнено", show_alert=True)
        return
    liters = callback_data.liters

    try:
        new_amount_liters = await inventory_service.take_fuel(callback.from_user.id, liters)
        await generator_service.log_refuel(callback.from_user.id, gen.name, liters)
    except Exception:
        logging.exception(f"Refuel failed user_id={callback.from_user.id} gen={gen.name}")
        await callback.message.answer("❌ Не вдалося записати заправку. Спробуйте ще раз.")
        await callback.answer()
        raise  # DbSessionMiddleware rolls back the half-done transaction

    text = "✅ <b>Заправка успішна!</b>\n"
    text += "➖➖➖➖➖➖➖➖➖➖\n"
    text += f"⛽ <b>{html.escape(gen.name)}</b> +{liters}л\n"
    text += f"📦 Залишок: <b>{new_amount_liters / LITERS_PER_CAN:.2f}</b> каністр"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[[types.InlineKeyboardButton(text="❌ Закрити", callback_data="refuel_close")]]
        )
    )
    await callback.answer()

@router.callback_query(F.data == "fuel_back")
async def back_to_gen_select(callback: types.CallbackQuery, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await callback.message.edit_text("Куди заправляємо?", reply_markup=get_refuel_kb(gens))
    await callback.answer()
