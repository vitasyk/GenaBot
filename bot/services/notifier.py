import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from bot.config import config


class NotifierService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def _send(self, user_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        try:
            await self.bot.send_message(user_id, text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception:
            # Blocked bot, wrong ID in .env or broken HTML: log it, keep notifying the others
            logging.warning(f"Failed to notify user_id={user_id}", exc_info=True)

    async def notify_all(self, text: str) -> None:
        """Sends message to Admins and optionally to Workers."""
        recipients = set(config.ADMIN_IDS)
        if config.NOTIFY_WORKERS:
            recipients.update(config.ALLOWED_IDS)
        for user_id in recipients:
            await self._send(user_id, text)

    async def notify_admins(self, text: str) -> None:
        """Sends message only to Admins."""
        for admin_id in config.ADMIN_IDS:
            await self._send(admin_id, text)

    async def notify_user(self, user_id: int, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        """Sends message to specific user."""
        await self._send(user_id, text, reply_markup)
