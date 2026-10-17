import html

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from bot.states import SessionStates
from bot.database.main import session_maker
from bot.database.repositories.session import SessionRepository
from bot.database.models import SessionStatus
from bot.generator_specs import LITERS_PER_CAN
from bot.keyboards.callbacks import ALL_GENERATORS_ID, GenCallback
from bot.keyboards.session_kb import (
    get_in_progress_kb,
    get_gen_choice_kb,
    get_skip_kb
)
from bot.services.generator import GeneratorService

router = Router()

ALL_GENERATORS_LABEL = "Усі"

@router.callback_query(F.data.startswith("session_start:"))
async def start_session_handler(callback: CallbackQuery):
    session_id = int(callback.data.split(":")[1])

    async with session_maker() as session:
        repo = SessionRepository(session)
        # Only a pending session can be started: an old button must not reopen a finished one
        updated_session = await repo.update_status(
            session_id, SessionStatus.in_progress, expected_status=SessionStatus.pending
        )

    if not updated_session:
        await callback.answer("Сесію вже розпочато, завершено або скасовано.", show_alert=True)
        return

    msg_text = (f"⚙️ <b>Сесія в процесі</b>\n\n"
                f"Розпочав: {html.escape(callback.from_user.full_name)}\n"
                f"Дедлайн (світло): {updated_session.deadline.strftime('%H:%M')}\n\n"
                f"Натисніть 'Завершити', коли заправите генератор.")

    await callback.message.edit_text(msg_text, reply_markup=get_in_progress_kb(session_id), parse_mode="HTML")
    await callback.answer("Сесію розпочато!")

@router.callback_query(F.data.startswith("session_complete:"))
async def complete_session_start(callback: CallbackQuery, state: FSMContext, generator_service: GeneratorService):
    session_id = int(callback.data.split(":")[1])
    await state.update_data(session_id=session_id)

    gens = await generator_service.get_status()
    await callback.message.edit_text("⚡️ <b>Завершення сесії</b>\n\nЯкий генератор заправили?",
                                     reply_markup=get_gen_choice_kb(gens), parse_mode="HTML")
    await state.set_state(SessionStates.waiting_for_generator)
    await callback.answer()

@router.callback_query(SessionStates.waiting_for_generator, GenCallback.filter(F.action == "session"))
async def generator_chosen(callback: CallbackQuery, callback_data: GenCallback, state: FSMContext,
                           generator_service: GeneratorService):
    if callback_data.gen_id == ALL_GENERATORS_ID:
        gen_name = ALL_GENERATORS_LABEL
    else:
        gen = await generator_service.get_by_id(callback_data.gen_id)
        if not gen:
            await callback.answer("Генератор не знайдено", show_alert=True)
            return
        gen_name = gen.name
    await state.update_data(gen_name=gen_name)

    await callback.message.edit_text("⛽️ <b>Скільки літрів палива залили?</b>\n\n"
                                     "Введіть число (наприклад: 20.5).",
                                     reply_markup=None, parse_mode="HTML")
    await state.set_state(SessionStates.waiting_for_liters)
    await callback.answer()

@router.message(SessionStates.waiting_for_liters)
async def liters_input(message: Message, state: FSMContext):
    try:
        liters = float((message.text or "").strip().replace(",", "."))
    except ValueError:
        liters = -1.0
    if liters <= 0:
        await message.answer("⚠️ Будь ласка, введіть коректне число (наприклад 10.5).")
        return

    await state.update_data(liters=liters)
    await message.answer("📝 <b>Додати нотатки?</b>\n(наприклад: 'залив масло', 'були проблеми')\n\n"
                         "Натисніть 'Пропустити', якщо немає.",
                         reply_markup=get_skip_kb(), parse_mode="HTML")
    await state.set_state(SessionStates.waiting_for_notes)

@router.callback_query(SessionStates.waiting_for_notes, F.data == "skip_step")
@router.message(SessionStates.waiting_for_notes)
async def finish_session(event: Message | CallbackQuery, state: FSMContext):
    data = await state.get_data()
    notes = event.text if isinstance(event, Message) else None
    if isinstance(event, CallbackQuery):
        await event.answer()

    session_id = data.get("session_id")
    gen_choice = data.get("gen_name")
    liters = data.get("liters")
    await state.clear()

    reply = event.message.edit_text if isinstance(event, CallbackQuery) else event.answer
    if session_id is None or liters is None:
        await reply("⚠️ Дані сесії втрачено. Натисніть 'Завершити сесію' ще раз.")
        return

    cans = liters / LITERS_PER_CAN
    async with session_maker() as session:
        completed_session = await SessionRepository(session).complete_session(
            session_id=session_id,
            completed_by=event.from_user.id,
            gen_name=gen_choice,
            liters=liters,
            cans=cans,
            notes=notes
        )

    msg = (f"✅ <b>Сесію # {session_id} завершено!</b>\n\n"
           f"👤 Воркер: {html.escape(event.from_user.full_name)}\n"
           f"⚡️ Генератор: {html.escape(gen_choice or '—')}\n"
           f"⛽️ Паливо: {liters}л ({cans:.1f} кан)\n"
           f"🕒 Час: {completed_session.end_time.strftime('%H:%M')}")
    await reply(msg, parse_mode="HTML")
