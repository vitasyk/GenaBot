import html
import logging

from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    InputMediaPhoto,
)

from bot.database.models import UserRole
from bot.database.repositories.user import UserRepository
from bot.keyboards.inline_kb import STALE_MENU_TEXT, GenCb, get_sos_kb
from bot.keyboards.main_kb import get_main_keyboard
from bot.services.generator import GeneratorService

logger = logging.getLogger(__name__)

router = Router()

SOS_MENU_TEXT = "🆘 <b>Оберіть генератор для інструкції:</b>"
SOS_NO_INSTRUCTIONS = (
    "Інструкцію ще не додано. Адміністратор може додати її в адмін-панелі → ⚙️ Генератори."
)



def refuel_instructions_text() -> str:
    from bot.config import config
    from bot.services.antigel import SAFETY_MARGIN_C
    dose = config.ANTIGEL_ML_PER_LITER
    threshold = config.FUEL_CFPP_C + SAFETY_MARGIN_C  # same rule as the reminders
    return (
        "⛽ <b>Як заправляти генератор</b>\n\n"
        "1. Зупиніть генератор і дайте 5–10 хв охолонути. Не паліть і не заправляйте біля іскор.\n"
        "2. Візьміть чисту каністру й лійку з сіточкою. Витріть горловину бака від бруду й снігу.\n"
        "3. Взимку спершу влийте антигель (див. нижче), потім паливо — так вони перемішаються.\n"
        "4. Заливайте повільно і не під горло: лишіть ~5% бака (≈8 л зі 170 л).\n"
        "5. Щільно закрийте кришку, витріть розлите паливо.\n"
        "6. Запишіть заправку в боті: «⛽ Заправити».\n\n"
        "❄️ <b>Антигель (зимова присадка)</b>\n"
        f"• Додавайте, коли нічний прогноз <b>{threshold:+.0f} °C і нижче</b>. Присадка працює, тільки якщо влита "
        "до того, як паливо почне мутніти від холоду. Загуслому паливу вона вже не допоможе — тоді генератор "
        "треба прогріти.\n"
        f"• Дозування: <b>{dose:g} мл на 1 л</b> палива. Повний бак 170 л — {170 * dose:g} мл, "
        f"каністра 20 л — {20 * dose:g} мл. Якщо на етикетці вашої присадки інше — орієнтуйтеся на етикетку.\n"
        "• Після заправки запустіть генератор на кілька хвилин, щоб присадка розійшлася по системі.\n"
        "• Позначте в боті «✅ Присадку додано», коли бот нагадає."
    )


@router.message(CommandStart())
@router.message(Command("menu"))
@router.message(Command("help"))
async def cmd_start(message: types.Message, user_repo: UserRepository):
    from bot.config import config
    user = await user_repo.create_or_update(
        user_id=message.from_user.id,
        name=message.from_user.full_name
    )

    if user.role == UserRole.blocked:
        await message.answer("⛔ <b>Доступ заборонено</b>\nЗверніться до адміністратора для надання доступу.", parse_mode="HTML")
        return

    is_admin = message.from_user.id in config.ADMIN_IDS
    kb = get_main_keyboard(is_admin)

    await message.answer(
        f"👋 Вітаю, {user.name}!\n"
        f"Роль: {user.role.value}\n"
        f"Використовуйте кнопки нижче для керування генераторами.",
        reply_markup=kb,
        parse_mode="HTML"
    )

@router.message(F.text == "🆘 Інструкція (SOS)")
async def sos_handler(message: types.Message, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await message.answer(SOS_MENU_TEXT, reply_markup=get_sos_kb(gens), parse_mode="HTML")

@router.callback_query(F.data == "sos_menu")
async def sos_menu_callback(callback: types.CallbackQuery, generator_service: GeneratorService):
    gens = await generator_service.get_status()
    await callback.message.edit_text(SOS_MENU_TEXT, reply_markup=get_sos_kb(gens), parse_mode="HTML")
    await callback.answer()

@router.callback_query(F.data == "sos_refuel")
async def sos_refuel_instructions(callback: types.CallbackQuery):
    back = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="sos_menu")]])
    await callback.message.edit_text(refuel_instructions_text(), reply_markup=back, parse_mode="HTML")
    await callback.answer()

@router.callback_query(GenCb.filter(F.action == "sos"))
async def sos_generator(callback: types.CallbackQuery, callback_data: GenCb, generator_service: GeneratorService):
    gen = await generator_service.get_active(callback_data.id)
    if not gen:
        await callback.answer(STALE_MENU_TEXT, show_alert=True)
        return

    # instructions are stored as Telegram HTML (admin input via message.html_text)
    media = gen.instructions_media or []
    text = f"🔧 <b>{html.escape(gen.name)}</b>\n\n{gen.instructions or ('' if media else SOS_NO_INSTRUCTIONS)}"
    back = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="sos_menu")]])
    await callback.message.edit_text(text, reply_markup=back, parse_mode="HTML")
    await callback.answer()
    await send_instruction_media(callback.message, media)


async def send_instruction_media(message: types.Message, media: list[dict]) -> None:
    """Photos as one album, PDFs as another (Telegram can't mix them); a single file goes alone."""
    photos = [m["file_id"] for m in media if m["type"] == "photo"]
    documents = [m["file_id"] for m in media if m["type"] == "document"]
    try:
        if len(photos) == 1:
            await message.answer_photo(photos[0])
        elif photos:
            await message.answer_media_group([InputMediaPhoto(media=f) for f in photos])
        if len(documents) == 1:
            await message.answer_document(documents[0])
        elif documents:
            await message.answer_media_group([InputMediaDocument(media=f) for f in documents])
    except TelegramBadRequest:
        # e.g. a file_id from another bot token; the text part was already shown
        logger.warning("Failed to send SOS attachments", exc_info=True)
