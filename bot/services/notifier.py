from aiogram import Bot
from bot.config import config

class NotifierService:
    def __init__(self, bot: Bot):
        self.bot = bot

    async def notify_all(self, text: str):
        """Sends message to Admins and optionally to Workers."""
        recipients = set(config.ADMIN_IDS)
        
        if config.NOTIFY_WORKERS:
            recipients.update(config.ALLOWED_IDS)
            
        for user_id in recipients:
            try:
                await self.bot.send_message(user_id, text, parse_mode="HTML")
            except Exception:
                pass # Blocked or invalid ID

    async def notify_admins(self, text: str):
        """Sends message only to Admins."""
        for admin_id in config.ADMIN_IDS:
            try:
                await self.bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass

    async def notify_user(self, user_id: int, text: str, reply_markup=None):
        """Sends message to specific user."""
        try:
            await self.bot.send_message(user_id, text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            pass # Blocked or invalid ID
