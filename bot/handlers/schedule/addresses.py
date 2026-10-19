"""Which queue an address is in, and which streets a queue covers (HOE Excel lists)."""
import html
import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import config
from bot.keyboards.main_kb import MENU_BUTTONS
from bot.keyboards.schedule_kb import QueuePageCb, get_queue_pages_kb
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

# Whole queue ("1") or subqueue ("1.1")
QUEUE_INPUT = re.compile(r"\d{1,2}(\.\d)?")
MAX_ADDRESS_RESULTS = 15
MAX_MESSAGE_CHARS = 3500  # Telegram limit is 4096; longer queue lists are paged, address results go as a file
MAX_PLACE_BYTES = 40  # callback data is limited to 64 bytes
TRY_AGAIN = "Перевірте написання і надішліть ще раз (можна частину назви) або натисніть «🔙 Головне меню»."


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


@router.message(ScheduleStates.waiting_for_address, F.text, ~F.text.in_(MENU_BUTTONS))  # menu buttons keep working
async def address_search(message: Message, state: FSMContext):
    rows = await _rows_or_none(message)
    if rows is None:
        return
    found = find_by_address(rows, message.text)
    if not found:  # stay in input mode: the next message is another try
        await message.answer(f"🤷 Нічого не знайдено. {TRY_AGAIN}")
        return
    await state.clear()

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
        "📋 Введіть чергу (<code>1</code>) або підчергу (<code>1.1</code>) і, за потреби, населений пункт.\n"
        f"Наприклад: <code>{html.escape(config.QUEUE_NUMBER)} Хмельницький</code>",
        parse_mode="HTML",
    )


@router.message(ScheduleStates.waiting_for_queue_streets, F.text, ~F.text.in_(MENU_BUTTONS))
async def queue_streets_list(message: Message, state: FSMContext):
    queue, _, settlement = message.text.strip().replace(",", ".", 1).partition(" ")
    if not QUEUE_INPUT.fullmatch(queue):
        await message.answer("⚠️ Спочатку черга або підчерга — наприклад <code>1 Хмельницький</code> "
                             "чи <code>1.1 Хмельницький</code>.",
                             parse_mode="HTML")
        return
    place = settlement.strip().replace(":", " ")  # ":" separates callback data fields
    if len(place.encode()) > MAX_PLACE_BYTES:
        await message.answer("⚠️ Задовга назва населеного пункту, введіть коротше (можна частину назви).")
        return
    rows = await _rows_or_none(message)
    if rows is None:
        return
    pages = _queue_pages(rows, queue, place)
    if not pages:  # stay in input mode: the next message is another try
        where = f" у «{place}»" if place else ""
        await message.answer(f"🤷 Для черги {queue}{where} нічого не знайдено. {TRY_AGAIN}")
        return
    await state.clear()
    await message.answer(html.escape(pages[0]), parse_mode="HTML",
                         reply_markup=get_queue_pages_kb(queue, place, 0, len(pages)))


@router.callback_query(QueuePageCb.filter())
async def queue_streets_page(callback: CallbackQuery, callback_data: QueuePageCb):
    try:
        rows = await addresses.get_rows()
    except HoeAddressError as e:
        logger.warning("HOE address lists unavailable: %s", e)
        await callback.answer("❌ Списки HOE зараз недоступні", show_alert=True)
        return
    pages = _queue_pages(rows, callback_data.queue, callback_data.place)
    if not pages:
        await callback.answer("🤷 Список змінився, запитайте ще раз", show_alert=True)
        return
    page = min(callback_data.page, len(pages) - 1)  # lists may shrink after a refresh
    await callback.message.edit_text(
        html.escape(pages[page]), parse_mode="HTML",
        reply_markup=get_queue_pages_kb(callback_data.queue, callback_data.place, page, len(pages)),
    )
    await callback.answer()


@router.callback_query(F.data == "qst_noop")
async def queue_streets_page_counter(callback: CallbackQuery):
    await callback.answer()


def paginate(lines: list[str], limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Join lines into pages of at most `limit` characters, never splitting a line."""
    pages: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if current and len(candidate) > limit:
            pages.append(current)
            candidate = line
        current = candidate
    if current:
        pages.append(current)
    return pages


def _queue_pages(rows: list[AddressRow], queue: str, place: str) -> list[str]:
    """Pages of the queue's streets grouped by settlement, each with a header; [] when nothing matches."""
    found = streets_for_queue(rows, queue, place)
    if not found:
        return []
    lines, current = [], None
    for r in sorted(found, key=lambda r: (r.settlement, r.street, r.queue)):
        if r.settlement != current:
            current = r.settlement
            lines.append(f"\n{current}")
        sub = f" [{r.queue}]" if r.queue != queue else ""  # whole queue asked: show the subqueue
        lines.append(f"• {r.street}{sub}: {', '.join(r.houses)}")
    title = f"📋 Черга {queue}{f' · {place}' if place else ''}: {len(found)} вулиць"
    pages = paginate(lines, MAX_MESSAGE_CHARS - len(title) - 20)
    return [f"{title} — стор. {i}/{len(pages)}\n{p.strip()}" for i, p in enumerate(pages, 1)]
