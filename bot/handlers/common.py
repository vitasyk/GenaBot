from aiogram import Router, F, types
from aiogram.filters import CommandStart, Command
from bot.database.repositories.user import UserRepository
from bot.keyboards.main_kb import get_main_keyboard
from bot.database.models import UserRole
from aiogram.utils.keyboard import InlineKeyboardBuilder, InlineKeyboardButton

router = Router()

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
async def sos_handler(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="GEN-1 (036)", callback_data="sos_gen_1"))
    builder.row(InlineKeyboardButton(text="GEN-2 (003) WILSON", callback_data="sos_gen_2"))
    
    await message.answer(
        "🆘 <b>Оберіть генератор для інструкції:</b>", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )

@router.callback_query(F.data == "sos_menu")
async def sos_menu_callback(callback: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="GEN-1 (036)", callback_data="sos_gen_1"))
    builder.row(InlineKeyboardButton(text="GEN-2 (003) WILSON", callback_data="sos_gen_2"))
    
    await callback.message.edit_text(
        "🆘 <b>Оберіть генератор для інструкції:</b>", 
        reply_markup=builder.as_markup(), 
        parse_mode="HTML"
    )

@router.callback_query(F.data == "sos_gen_1")
async def sos_gen_1(callback: types.CallbackQuery):
    text = (
        "🔧 <b>GEN-1 (036)</b>\n\n"
        "1. Перевірте паливо (бак зліва)\n"
        "2. Переключіть тумблер \"CHOKE\" у положення ON\n"
        "3. Потягніть стартер 3-5 разів різко\n"
        "4. Після запуску переведіть CHOKE у OFF\n"
        "5. Прогрійте 2-3 хвилини\n\n"
        "<i>(Тут буде фото та детальний опис)</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="sos_menu"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "sos_gen_2")
async def sos_gen_2(callback: types.CallbackQuery):
    text = (
        "🔧 <b>GEN-2 (003) WILSON</b>\n\n"
        "1. Переконайтесь що вимикач НЕ на ON\n"
        "2. Натисніть кнопку PRIME 5 разів\n"
        "3. Переключіть вимикач на ON\n"
        "4. Натисніть кнопку START (тримайте 3-5 сек)\n"
        "5. Дочекайтесь стабільних обертів\n\n"
        "<i>(Тут буде фото та детальний опис)</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="sos_menu"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.message(F.text == "📊 Адмін-панель")
async def admin_panel_handler(message: types.Message, user_repo: UserRepository):
    from bot.config import config
    if message.from_user.id not in config.ADMIN_IDS:
        return

    text = "📊 <b>Адмін-панель</b>\n\n"
    text += f"🔐 <b>Режим доступу:</b> {'🔒 Обмежений (Whitelist)' if config.RESTRICT_ACCESS else '🌍 Публічний'}\n"
    text += f"📢 <b>Сповіщення:</b> {'👥 Всім працівникам' if config.NOTIFY_WORKERS else '👮 Тільки адмінам'}\n"
    text += f"👥 <b>Білий список:</b> {len(config.ALLOWED_IDS)} ID\n"
    text += f"👑 <b>Адміни:</b> {len(config.ADMIN_IDS)} ID\n"
    
    await message.answer(text, reply_markup=_get_admin_panel_kb(), parse_mode="HTML")
