"""Admin panel handlers, split by feature. Sub-router order keeps the original handler order."""
from aiogram import Router

from bot.handlers.admin import generators, panel, sessions, slack, users

router = Router()
router.include_routers(sessions.router, users.router, panel.router, slack.router, generators.router)
