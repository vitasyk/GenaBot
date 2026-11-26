import html

from aiogram import Router, types
from redis.asyncio import Redis

from bot.keyboards.session_kb import OutageAnswerCb
from bot.services.session_service import record_outage_answer

router = Router()


@router.callback_query(OutageAnswerCb.filter())
async def outage_answer(callback: types.CallbackQuery, callback_data: OutageAnswerCb, redis: Redis) -> None:
    """Yes/No on the outage warning. 'Power is on' cancels the refuel session for that block."""
    await record_outage_answer(redis, callback_data.block, callback_data.power)
    who = html.escape(callback.from_user.full_name)
    if callback_data.power:
        note, kb = "👌 Зрозуміло, світло є. Сесію заправки для цього відключення не буде створено.", None
    else:
        note = "🔌 Світла немає — запустіть генератор."
        # Keep only the "generator started" buttons; the yes/no row is last
        kb = types.InlineKeyboardMarkup(inline_keyboard=callback.message.reply_markup.inline_keyboard[:-1])
    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n{note}\nВідповів: {who}", reply_markup=kb, parse_mode="HTML"
    )
    await callback.answer()
