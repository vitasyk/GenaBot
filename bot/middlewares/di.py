from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.database.repositories.user import UserRepository
from bot.database.repositories.inventory import InventoryRepository
from bot.database.repositories.logs import LogRepository
from bot.database.repositories.generator import GeneratorRepository
from bot.services.inventory import InventoryService
from bot.services.generator import GeneratorService
from bot.services.weather import WeatherService

class DbSessionMiddleware(BaseMiddleware):
    def __init__(self, session_pool: async_sessionmaker):
        super().__init__()
        self.session_pool = session_pool

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with self.session_pool() as session:
            # Repositories
            user_repo = UserRepository(session)
            inventory_repo = InventoryRepository(session)
            log_repo = LogRepository(session)
            gen_repo = GeneratorRepository(session)
            
            # Services
            # Note: We need 'bot' instance for alerts in InventoryService
            bot = data["bot"]
            
            data["user_repo"] = user_repo
            data["log_repo"] = log_repo
            data["inventory_service"] = InventoryService(inventory_repo, log_repo, user_repo, bot)
            data["generator_service"] = GeneratorService(gen_repo, log_repo)
            data["weather_service"] = WeatherService()
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
