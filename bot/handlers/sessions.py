import html
import logging

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from datetime import datetime
from aiogram import Bot

from bot.states import SessionStates
from bot.database.main import session_maker
from bot.database.repositories.session import OPEN_STATUSES, SessionRepository
from bot.database.repositories.user import UserRepository
from bot.services.notifier import NotifierService
from bot.services.generator import GeneratorService
from bot.services.inventory import InventoryService
from bot.database.repositories.logs import LogRepository
from bot.database.models import SessionStatus
from bot.keyboards.session_kb import (
    get_in_progress_kb, 
    get_gen_choice_kb,
    get_gen_selection_kb,
    get_skip_kb
)

router = Router()

@router.callback_query(F.data.startswith("session_start:"))
async def start_session_handler(callback: CallbackQuery):
    session_id = int(callback.data.split(":")[1])
    
    async with session_maker() as session:
        repo = SessionRepository(session)
        # Never reopens a completed/cancelled session from an old button
        updated_session = await repo.update_status(session_id, SessionStatus.in_progress, only_from=OPEN_STATUSES)

        if not updated_session:
            await callback.answer("Сесію вже завершено або скасовано.", show_alert=True)
            return

        deadline_str = updated_session.deadline.strftime("%H:%M")

        msg_text = (f"⚙️ <b>Сесія в процесі</b>\n\n"
                    f"Розпочав: {html.escape(callback.from_user.full_name)}\n"
                    f"Дедлайн (світло): {deadline_str}\n\n"
                    f"Натисніть 'Завершити', коли заправите генератор.")
        
        await callback.message.edit_text(msg_text, reply_markup=get_in_progress_kb(session_id), parse_mode="HTML")
        await callback.answer("Сесію розпочато!")

@router.callback_query(F.data.startswith("session_complete:"))
async def complete_session_start(callback: CallbackQuery, state: FSMContext, generator_service: GeneratorService):
    session_id = int(callback.data.split(":")[1])
    await state.update_data(session_id=session_id, selected_gens=[])
    
    statuses = await _get_gen_statuses(generator_service)
    
    await callback.message.edit_text(
        "⚡️ <b>Завершення сесії</b>\n\n"
        "Оберіть генератори які були заправлені:",
        reply_markup=get_gen_selection_kb([], statuses=statuses),
        parse_mode="HTML"
    )
    await state.set_state(SessionStates.selecting_generators)
    await callback.answer()

async def _get_gen_statuses(generator_service: GeneratorService) -> dict:
    gens = await generator_service.get_status()
    from bot.database.models import GenStatus
    status_map = {}
    for g in gens:
        icon = "🔴"
        if g.status == GenStatus.running: icon = "🟢"
        elif g.status == GenStatus.standby: icon = "🟡"
        status_map[g.name] = icon
    return status_map

@router.callback_query(SessionStates.selecting_generators, F.data.startswith("toggle_gen:"))
async def toggle_generator(callback: CallbackQuery, state: FSMContext, generator_service: GeneratorService):
    gen_name = callback.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("selected_gens", [])
    
    # Toggle
    if gen_name in selected:
        selected.remove(gen_name)
    else:
        selected.append(gen_name)
    
    await state.update_data(selected_gens=selected)
    
    statuses = await _get_gen_statuses(generator_service)
    
    # Update keyboard
    await callback.message.edit_reply_markup(
        reply_markup=get_gen_selection_kb(selected, statuses=statuses)
    )
    await callback.answer()

@router.callback_query(SessionStates.selecting_generators, F.data == "gen_confirm")
async def confirm_generators(callback: CallbackQuery, state: FSMContext, generator_service: GeneratorService):
    data = await state.get_data()
    selected_gens = data.get("selected_gens", [])
    
    if not selected_gens:
        await callback.answer("Оберіть хоча б один генератор!", show_alert=True)
        return
    
    # Start collecting fuel amounts
    await state.update_data(
        gen_fuel_data={},  # Will store {gen_name: liters}
        current_gen_index=0
    )
    
    first_gen = selected_gens[0]
    statuses = await _get_gen_statuses(generator_service)
    gen_emoji = statuses.get(first_gen, "🔴")
    
    await callback.message.edit_text(
        f"⛽️ {gen_emoji} <b>{first_gen}</b>\n\n"
        f"Скільки літрів залили до {first_gen}?\n"
        "Введіть число (наприклад: 20.5).",
        reply_markup=None,
        parse_mode="HTML"
    )
    await state.set_state(SessionStates.waiting_for_liters)
    await callback.answer()

@router.callback_query(SessionStates.waiting_for_generator, F.data.startswith("gen_choice:"))
async def generator_chosen(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    await state.update_data(gen_name=choice)
    
    await callback.message.edit_text("⛽️ <b>Скільки літрів палива залили?</b>\n\n"
                                     "Введіть число (наприклад: 20.5).", 
                                     reply_markup=None,
                                     parse_mode="HTML")
    await state.set_state(SessionStates.waiting_for_liters)
    await callback.answer()

@router.message(SessionStates.waiting_for_liters)
async def liters_input(message: Message, state: FSMContext, generator_service: GeneratorService):
    try:
        liters = float(message.text.strip().replace(",", "."))
        data = await state.get_data()
        
        # Check if we're using multi-generator flow
        if "selected_gens" in data and "gen_fuel_data" in data:
            # Multi-generator flow
            selected_gens = data["selected_gens"]
            current_index = data["current_gen_index"]
            gen_fuel_data = data.get("gen_fuel_data", {})
            
            # Store fuel for current generator
            current_gen = selected_gens[current_index]
            gen_fuel_data[current_gen] = liters
            
            # Move to next generator
            next_index = current_index + 1
            
            if next_index < len(selected_gens):
                # Ask for next generator
                await state.update_data(
                    gen_fuel_data=gen_fuel_data,
                    current_gen_index=next_index
                )
                
                next_gen = selected_gens[next_index]
                statuses = await _get_gen_statuses(generator_service)
                gen_emoji = statuses.get(next_gen, "🔴")
                
                await message.answer(
                    f"⛽️ {gen_emoji} <b>{next_gen}</b>\n\n"
                    f"Скільки літрів залили до {next_gen}?\n"
                    "Введіть число (наприклад: 20.5).",
                    parse_mode="HTML"
                )
            else:
                # All generators done, ask if Anti-Gel was added
                await state.update_data(gen_fuel_data=gen_fuel_data)
                from bot.keyboards.session_kb import get_antigel_kb
                await message.answer(
                    "💉 <b>Ви додавали антигель (Anti-Gel)?</b>\n"
                    "Це важливо для моніторингу залишку присадки.",
                    reply_markup=get_antigel_kb(),
                    parse_mode="HTML"
                )
                await state.set_state(SessionStates.waiting_for_antigel)
        else:
            # Old single-generator flow (fallback)
            await state.update_data(liters=liters)
            await message.answer(
                "📝 <b>Додати нотатки?</b>\n(наприклад: 'залив масло', 'були проблеми')\n\n"
                "Натисніть 'Пропустити', якщо немає.", 
                reply_markup=get_skip_kb(),
                parse_mode="HTML"
            )
            await state.set_state(SessionStates.waiting_for_notes)
        
    except ValueError:
        await message.answer("⚠️ Будь ласка, введіть коректне число (наприклад 10.5).")

@router.callback_query(SessionStates.waiting_for_antigel, F.data.startswith("antigel:"))
async def process_antigel(callback: CallbackQuery, state: FSMContext):
    added = callback.data == "antigel:yes"
    await state.update_data(antigel_added=added)
    
    from bot.keyboards.session_kb import get_skip_kb
    await callback.message.edit_text(
        "📝 <b>Додати нотатки?</b>\n"
        "(наприклад: 'залив масло', 'були проблеми')\n\n"
        "Якщо немає - натисніть 'Пропустити'.",
        reply_markup=get_skip_kb(),
        parse_mode="HTML"
    )
    await state.set_state(SessionStates.waiting_for_notes)
    await callback.answer()

@router.callback_query(SessionStates.waiting_for_notes, F.data == "skip_step")
async def skip_note_callback(callback: CallbackQuery, state: FSMContext, bot: Bot, generator_service: GeneratorService, inventory_service: InventoryService):
    await finish_session(callback, state, bot, notes=None, generator_service=generator_service, inventory_service=inventory_service)

@router.message(SessionStates.waiting_for_notes)
async def process_notes(message: Message, state: FSMContext, bot: Bot, generator_service: GeneratorService, inventory_service: InventoryService):
    await finish_session(message, state, bot, notes=message.text, generator_service=generator_service, inventory_service=inventory_service)

async def finish_session(event: Message | CallbackQuery, state: FSMContext, bot: Bot, notes: str | None, generator_service: GeneratorService = None, inventory_service: InventoryService = None):
    data = await state.get_data()
    # Clear first: if the reply fails, the worker must not stay on this step and complete again
    await state.clear()
    if isinstance(event, CallbackQuery):
        await event.answer()
    reply = event.message.edit_text if isinstance(event, CallbackQuery) else event.answer

    session_id = data.get("session_id")
    gen_fuel_data = data.get("gen_fuel_data") or {}
    if session_id is None or not gen_fuel_data:
        await reply("⚠️ Дані сесії втрачено. Натисніть «✅ Завершити сесію» ще раз.")
        return

    user_id = event.from_user.id
    antigel_added = data.get("antigel_added", False)
    total_liters = sum(gen_fuel_data.values())
    total_cans = total_liters / 20.0
    gen_summary = ", ".join(f"{name}: {liters}л" for name, liters in gen_fuel_data.items())

    # Complete first: only the worker who actually closes the session deducts fuel
    async with session_maker() as session:
        completed_session = await SessionRepository(session).complete_session(
            session_id=session_id,
            completed_by=user_id,
            gen_name=gen_summary,
            liters=total_liters,
            cans=total_cans,
            notes=notes
        )
    if not completed_session:
        await reply("ℹ️ Цю сесію вже завершено. Паливо повторно не списано.")
        return

    new_stock_cans = None
    if inventory_service:
        try:
            new_stock_cans = await inventory_service.take_fuel(user_id, total_liters) / 20.0
        except Exception:
            logging.exception(f"Failed to deduct fuel for session {session_id}, user_id={user_id}")

    if generator_service:
        for name, liters in gen_fuel_data.items():
            try:
                await generator_service.log_refuel(user_id, name, liters)
                if antigel_added:
                    await generator_service.reset_antigel(user_id, name)
            except Exception:
                logging.exception(f"Failed to log refuel for {name}, session {session_id}")

    statuses = await _get_gen_statuses(generator_service)
    gen_list = "\n".join(
        f"  • {statuses.get(name, '🔴')} {html.escape(name)}: {liters}л" for name, liters in gen_fuel_data.items()
    )
    msg = (
        f"✅ <b>Сесію #{session_id} завершено!</b>\n\n"
        f"👤 Воркер: {html.escape(event.from_user.full_name)}\n"
        f"⚡️ Генератори:\n{gen_list}\n"
        f"⛽️ Всього: {total_liters}л ({total_cans:.1f} кан)\n"
        f"💉 Антигель: {'✅ Так' if antigel_added else '❌ Ні'}\n"
        f"🕒 Час: {completed_session.end_time.strftime('%H:%M')}"
    )
    if new_stock_cans is not None:
        msg += f"\n📦 Залишок на складі: {new_stock_cans:.2f} кан"
    if notes:
        msg += f"\n📝 Нотатки: {html.escape(notes)}"

    await NotifierService(bot).notify_admins(f"📦 <b>Звіт про заправку (Сесія #{session_id})</b>\n\n{msg}")
    await reply(msg, parse_mode="HTML")
