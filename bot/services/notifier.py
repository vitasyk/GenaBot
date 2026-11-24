import logging

from aiogram import Bot

from bot.config import config

logger = logging.getLogger(__name__)


class NotifierService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def notify_all(self, text: str) -> int:
        """Sends message to Admins and optionally to Workers. Returns how many were delivered."""
        recipients = set(config.ADMIN_IDS)

        if config.NOTIFY_WORKERS:
            recipients.update(config.ALLOWED_IDS)

        return sum([await self.notify_user(user_id, text) for user_id in recipients])

    async def notify_admins(self, text: str):
        """Sends message only to Admins."""
        for admin_id in config.ADMIN_IDS:
            await self.notify_user(admin_id, text)

    async def notify_user(self, user_id: int, text: str, reply_markup=None) -> bool:
        """Sends message to specific user; a failed send (blocked bot, bad ID) is logged, not raised."""
        try:
            await self.bot.send_message(user_id, text, parse_mode="HTML", reply_markup=reply_markup)
            return True
        except Exception:
            logger.warning("Failed to send notification to user_id=%s", user_id, exc_info=True)
            return False
