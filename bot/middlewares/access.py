import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.database.models import UserRole
from bot.database.repositories.user import UserRepository

ACCESS_DENIED_TEXT = "⛔ Доступ заборонено. Зверніться до адміністратора."

# These commands register/refresh the user, so they must reach the handler.
OPEN_COMMANDS = frozenset({"/start", "/menu", "/help"})
ALLOWED_ROLES = frozenset({UserRole.admin, UserRole.worker})


def _is_open_command(event: TelegramObject) -> bool:
    if not isinstance(event, Message) or not event.text:
        return False
    command = event.text.split(maxsplit=1)[0].split("@", 1)[0].lower()
    return command in OPEN_COMMANDS


class AccessMiddleware(BaseMiddleware):
    """Outer middleware for messages and callbacks: only DB users with role admin/worker pass.

    Needs `user_repo` in data, so DbSessionMiddleware must run first (it is on dp.update).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if _is_open_command(event):
            return await handler(event, data)

        tg_user = data.get("event_from_user")
        user_repo: UserRepository = data["user_repo"]
        user = await user_repo.get_by_id(tg_user.id) if tg_user else None
        if user and user.role in ALLOWED_ROLES:
            return await handler(event, data)

        logging.warning("Access denied: user_id=%s role=%s", tg_user.id if tg_user else None, user.role if user else None)
        if isinstance(event, CallbackQuery):
            await event.answer(ACCESS_DENIED_TEXT, show_alert=True)
        elif isinstance(event, Message):
            await event.answer(ACCESS_DENIED_TEXT)
        return None
