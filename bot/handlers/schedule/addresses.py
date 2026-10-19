"""Which queue an address is in, and which streets a queue covers (HOE Excel lists)."""
import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message

from bot.config import config
from bot.handlers.schedule.queue import QUEUE_PATTERN
from bot.services.hoe_addresses import (
    AddressRow,
    HoeAddressError,
    HoeAddressService,
    find_by_address,
    split_house,
    streets_for_queue,
)
from bot.states import ScheduleStates

logger = logging.getLogger(__name__)

router = Router()
addresses = HoeAddressService()

MAX_ADDRESS_RESULTS = 15
MAX_MESSAGE_CHARS = 3500  # Telegram limit is 4096; longer lists go as a .txt file


async def _rows_or_none(message: Message) -> list[AddressRow] | None:
    wait = await message.answer("🔍 Завантажую списки HOE...")
    try:
        return await addresses.get_rows()
    except HoeAddressError as e:
        logger.warning("HOE address lists unavailable: %s", e)
        await message.answer(f"❌ Не вдалося отримати списки HOE: {html.escape(str(e))}.\nСпробуйте пізніше.")
        return None
    finally:
        await wait.delete()


async def _send_long(message: Message, text: str, filename: str, caption: str) -> None:
    """Plain text as a message, or as a .txt file when it doesn't fit (HOE data is escaped)."""
    if len(text) <= MAX_MESSAGE_CHARS:
        await message.answer(html.escape(text), parse_mode="HTML")
    else:
        await message.answer_document(BufferedInputFile(text.encode("utf-8"), filename=filename), caption=caption)


@router.message(F.text == "🏠 Черга за адресою")
async def address_start(message: Message, state: FSMContext):
    await state.set_state(ScheduleStates.waiting_for_address)
    await message.answer(
        "🏠 Введіть вулицю і номер будинку, за потреби з населеним пунктом.\n"
        "Наприклад: <code>Бандери 22</code> або <code>Антонівці Садова 13а</code>",
        parse_mode="HTML",
    )


@router.message(ScheduleStates.waiting_for_address, F.text)
async def address_search(message: Message, state: FSMContext):
    await state.clear()
    rows = await _rows_or_none(message)
    if rows is None:
        return
    found = find_by_address(rows, message.text)
    if not found:
        await message.answer("🤷 Нічого не знайдено. Перевірте назву вулиці або введіть без номера будинку.")
        return

    _, house = split_house(message.text)
    lines = []
    for r in found[:MAX_ADDRESS_RESULTS]:
        if house:
            lines.append(f"🏠 {r.settlement}, {r.street}, буд. {house} → черга {r.queue}")
        else:
            lines.append(f"🏠 {r.settlement}, {r.street} → черга {r.queue}\n   буд.: {', '.join(r.houses)}")
    if len(found) > MAX_ADDRESS_RESULTS:
        lines.append(f"\n…ще {len(found) - MAX_ADDRESS_RESULTS}. Уточніть запит (населений пункт, номер будинку).")
    await _send_long(message, "\n".join(lines), "adresa.txt", "🏠 Результати пошуку (у файлі)")


@router.message(F.text == "📋 Вулиці черги")
async def queue_streets_start(message: Message, state: FSMContext):
    await state.set_state(ScheduleStates.waiting_for_queue_streets)
    await message.answer(
        "📋 Введіть чергу і, за потреби, населений пункт.\n"
        f"Наприклад: <code>{html.escape(config.QUEUE_NUMBER)} Хмельницький</code>",
        parse_mode="HTML",
    )


@router.message(ScheduleStates.waiting_for_queue_streets, F.text)
async def queue_streets_list(message: Message, state: FSMContext):
    queue, _, settlement = message.text.strip().replace(",", ".", 1).partition(" ")
    if not QUEUE_PATTERN.fullmatch(queue):
        await message.answer("⚠️ Спочатку черга: число, крапка, число — наприклад <code>1.1 Хмельницький</code>.",
                             parse_mode="HTML")
        return
    await state.clear()
    rows = await _rows_or_none(message)
    if rows is None:
        return
    found = streets_for_queue(rows, queue, settlement.strip())
    if not found:
        await message.answer(f"🤷 Для черги {queue} нічого не знайдено.")
        return

    lines, current = [f"Черга {queue}: {len(found)} вулиць"], None
    for r in sorted(found, key=lambda r: (r.settlement, r.street)):
        if r.settlement != current:
            current = r.settlement
            lines.append(f"\n{current}")
        lines.append(f"• {r.street}: {', '.join(r.houses)}")
    await _send_long(message, "\n".join(lines), f"cherga_{queue}.txt",
                     f"📋 Черга {queue}: {len(found)} вулиць (список у файлі)")
