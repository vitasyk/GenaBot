from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.database.models import UserRole

# Commands that register the user (handlers/common.py), so they must pass for unknown users
OPEN_COMMANDS = {"/start", "/menu", "/help"}
ACCESS_DENIED_TEXT = "⛔ Доступ заборонено. Зверніться до адміністратора."


class AccessMiddleware(BaseMiddleware):
    """Drops events from blocked or unregistered users. Needs user_repo from DbSessionMiddleware."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.text:
            command = event.text.split()[0].split("@")[0]
            if command in OPEN_COMMANDS:
                return await handler(event, data)

        user = await data["user_repo"].get_by_id(event.from_user.id)
        if user is not None and user.role != UserRole.blocked:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer(ACCESS_DENIED_TEXT, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(ACCESS_DENIED_TEXT)
        return None
