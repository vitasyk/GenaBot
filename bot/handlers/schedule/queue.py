import html
import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import config
from bot.keyboards.schedule_kb import get_queue_kb, get_schedule_menu_kb
from bot.scheduler import save_runtime_setting
from bot.states import ScheduleStates

logger = logging.getLogger(__name__)

router = Router()

# HOE has 6 queues x 2 subqueues; any other one can be typed in
QUEUE_BUTTONS = [f"{q}.{sub}" for q in range(1, 7) for sub in (1, 2)]
QUEUE_PATTERN = re.compile(r"\d{1,2}\.\d")

# Queue selection (admin only)
async def _save_queue(state: FSMContext, queue: str) -> None:
    config.QUEUE_NUMBER = queue
    await save_runtime_setting(state.storage.redis, "QUEUE_NUMBER", queue)
    logger.info(f"Queue changed to {queue}")

@router.message(F.text == "🔢 Черга")
async def queue_menu(message: Message):
    if message.from_user.id not in config.ADMIN_IDS:
        await message.answer("⛔ Ця функція доступна тільки адміністраторам.")
        return
    await message.answer(
        f"🔢 <b>Яку чергу відстежувати?</b>\n\nЗараз: <b>{html.escape(config.QUEUE_NUMBER)}</b>.\n"
        "Від черги залежать графік, розпізнавання ШІ та сесії заправки.",
        reply_markup=get_queue_kb(QUEUE_BUTTONS, config.QUEUE_NUMBER),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("queue_set:"))
async def queue_set(callback: CallbackQuery, state: FSMContext):
    queue = callback.data.split(":", 1)[1]
    if callback.from_user.id not in config.ADMIN_IDS or not QUEUE_PATTERN.fullmatch(queue):
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await _save_queue(state, queue)
    await callback.message.edit_text(f"✅ Черга: <b>{queue}</b>", parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "queue_custom")
async def queue_custom(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("⛔ Недоступно", show_alert=True)
        return
    await state.set_state(ScheduleStates.waiting_for_queue)
    await callback.message.edit_text("✍️ Введіть номер черги, наприклад <code>4.2</code>.", parse_mode="HTML")
    await callback.answer()

@router.message(ScheduleStates.waiting_for_queue)
async def queue_input(message: Message, state: FSMContext):
    queue = (message.text or "").strip().replace(",", ".")
    if not QUEUE_PATTERN.fullmatch(queue):
        await message.answer("⚠️ Формат: число, крапка, число — наприклад <code>1.1</code>.", parse_mode="HTML")
        return
    await _save_queue(state, queue)
    await state.clear()
    await message.answer(f"✅ Черга: <b>{queue}</b>", parse_mode="HTML",
                         reply_markup=get_schedule_menu_kb(is_admin=True))

