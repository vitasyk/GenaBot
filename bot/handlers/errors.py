import logging

from aiogram import Router
from aiogram.types import ErrorEvent

logger = logging.getLogger(__name__)
router = Router()

ERROR_TEXT = "⚠️ Щось пішло не так. Спробуйте ще раз або зверніться до адміністратора."


@router.error()
async def on_error(event: ErrorEvent) -> bool:
    """Global handler for exceptions raised in any handler: log it and tell the user."""
    update = event.update
    message, callback = update.message, update.callback_query
    source = message or callback
    user_id = source.from_user.id if source and source.from_user else None
    logger.exception("Unhandled error in update %s (user_id=%s): %r", update.update_id, user_id,
                     event.exception, exc_info=event.exception)
    try:
        if callback:
            await callback.answer(ERROR_TEXT, show_alert=True)
        elif message:
            await message.answer(ERROR_TEXT)
    except Exception:
        logger.exception("Failed to send error notice to user_id=%s", user_id)
    return True
