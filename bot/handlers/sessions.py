from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from datetime import datetime

from bot.states import SessionStates
from bot.database.main import session_maker
from bot.database.repositories.session import SessionRepository
from bot.database.models import SessionStatus
from bot.keyboards.session_kb import (
    get_in_progress_kb, 
    get_gen_choice_kb, 
    get_skip_kb
)

router = Router()

@router.callback_query(F.data.startswith("session_start:"))
async def start_session_handler(callback: CallbackQuery):
    session_id = int(callback.data.split(":")[1])
    
    async with session_maker() as session:
        repo = SessionRepository(session)
        # Update status
        updated_session = await repo.update_status(session_id, SessionStatus.in_progress)
        
        if not updated_session:
            await callback.answer("Сесія не знайдена або вже завершена.", show_alert=True)
            return

        # Update message
        workers = []
        if updated_session.worker1_id: workers.append(f"Worker {updated_session.worker1_id}") # Ideally fetch names
        # Just keep it simple for now or fetch names if available in model (relationships not loaded)
        
        deadline_str = updated_session.deadline.strftime("%H:%M")
        
        msg_text = (f"⚙️ <b>Сесія в процесі</b>\n\n"
                    f"Розпочав: {callback.from_user.full_name}\n"
                    f"Дедлайн (світло): {deadline_str}\n\n"
                    f"Натисніть 'Завершити', коли заправите генератор.")
        
        await callback.message.edit_text(msg_text, reply_markup=get_in_progress_kb(session_id))
        await callback.answer("Сесію розпочато!")

@router.callback_query(F.data.startswith("session_complete:"))
async def complete_session_start(callback: CallbackQuery, state: FSMContext):
    session_id = int(callback.data.split(":")[1])
    await state.update_data(session_id=session_id)
    
    await callback.message.edit_text("⚡️ <b>Завершення сесії</b>\n\nЯкий генератор заправили?", 
                                     reply_markup=get_gen_choice_kb())
    await state.set_state(SessionStates.waiting_for_generator)
    await callback.answer()

@router.callback_query(SessionStates.waiting_for_generator, F.data.startswith("gen_choice:"))
async def generator_chosen(callback: CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    await state.update_data(gen_name=choice)
    
    await callback.message.edit_text("⛽️ <b>Скільки літрів палива залили?</b>\n\n"
                                     "Введіть число (наприклад: 20.5).", 
                                     reply_markup=None)
    await state.set_state(SessionStates.waiting_for_liters)
    await callback.answer()

@router.message(SessionStates.waiting_for_liters)
async def liters_input(message: Message, state: FSMContext):
    try:
        liters = float(message.text.strip().replace(",", "."))
        await state.update_data(liters=liters)
        
        # Calculate cans approximately (assume 20L can?)
        # For now just simple estimation or ask separately. 
        # Plan says "Cans: Mapped[float]". Let's assume user inputs LITERS.
        # We can calculate cans later or ask. Let's ask Notes validation.
        
        await message.answer("📝 <b>Додати нотатки?</b>\n(наприклад: 'залив масло', 'були проблеми')\n\nНатисніть 'Пропустити', якщо немає.", 
                             reply_markup=get_skip_kb())
        await state.set_state(SessionStates.waiting_for_notes)
        
    except ValueError:
        await message.answer("⚠️ Будь ласка, введіть коректне число (наприклад 10.5).")

@router.callback_query(SessionStates.waiting_for_notes, F.data == "skip_step")
@router.message(SessionStates.waiting_for_notes)
async def finish_session(event: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    notes = None
    
    if isinstance(event, Message):
        notes = event.text
    elif isinstance(event, CallbackQuery) and event.data == "skip_step":
        notes = None
        # Must answer callback if it was callback
        await event.answer()
        
    session_id = data.get("session_id")
    gen_choice = data.get("gen_name")
    liters = data.get("liters")
    
    user_id = event.from_user.id
    
    async with session_maker() as session:
        repo = SessionRepository(session)
        
        # Assume 1 can = 20L for calculation (Need standard)
        # Or just store 0 for now
        cans = liters / 20.0 
        
        completed_session = await repo.complete_session(
            session_id=session_id,
            completed_by=user_id,
            gen_name=gen_choice,
            liters=liters,
            cans=cans,
            notes=notes
        )
        
        # Final confirmation
        msg = (f"✅ <b>Сесію # {session_id} завершено!</b>\n\n"
               f"👤 Воркер: {event.from_user.full_name}\n"
               f"⚡️ Генератор: {gen_choice}\n"
               f"⛽️ Паливо: {liters}л ({cans:.1f} кан)\n"
               f"🕒 Час: {completed_session.end_time.strftime('%H:%M')}")
        
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(msg)
        else:
            await event.answer(msg)
            
    await state.clear()
