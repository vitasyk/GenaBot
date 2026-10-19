"""Schedule management handlers, split by feature. Sub-router order keeps the original handler order."""
from aiogram import Router

from bot.handlers.schedule import manual, menu, queue, recognition

router = Router()
router.include_routers(menu.router, recognition.router, queue.router, manual.router)
