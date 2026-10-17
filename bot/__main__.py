import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand
from anthropic import AsyncAnthropic
from redis.asyncio import Redis

from bot.config import config
from bot.database.main import session_maker
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.logs import LogRepository
from bot.handlers import admin, common, generators, inventory, sessions, weather
from bot.middlewares.access import AccessMiddleware
from bot.middlewares.di import DbSessionMiddleware
from bot.scheduler import restore_scheduler_settings, start_scheduler
from bot.services.generator import GeneratorService
from bot.services.runtime_settings import load_flags
from bot.services.schedule_parser import ScheduleParser
from bot.services.schedule_recognizer import ScheduleRecognizer

POLLING_RESTART_DELAY_SECONDS = 5
ANTHROPIC_TIMEOUT_SECONDS = 120.0

async def main():
    logging.basicConfig(level=config.LOG_LEVEL)

    bot = Bot(token=config.BOT_TOKEN.get_secret_value())

    # keepalive + retries prevent connection drops (WinError 64)
    redis_client = Redis.from_url(
        config.REDIS_URL.get_secret_value(),
        socket_keepalive=True,
        socket_connect_timeout=10,
        retry_on_timeout=True,
        health_check_interval=30
    )
    anthropic_client = AsyncAnthropic(
        api_key=config.ANTHROPIC_API_KEY.get_secret_value(),
        timeout=ANTHROPIC_TIMEOUT_SECONDS,
    )
    schedule_parser = ScheduleParser(ScheduleRecognizer(anthropic_client, config.SCHEDULE_AI_MODEL), redis_client)

    # Extra kwargs become workflow_data: handlers receive `schedule_parser` and `redis` by name
    dp = Dispatcher(storage=RedisStorage(redis=redis_client), schedule_parser=schedule_parser, redis=redis_client)

    await bot.set_my_commands([
        BotCommand(command="start", description="🚀 Запуск бота"),
        BotCommand(command="menu", description="👋 Головне меню"),
        BotCommand(command="help", description="🆘 Допомога"),
    ])

    dp.update.middleware(DbSessionMiddleware(session_maker))
    access_middleware = AccessMiddleware()
    dp.message.outer_middleware(access_middleware)
    dp.callback_query.outer_middleware(access_middleware)

    await load_flags(redis_client)

    async with session_maker() as session:
        service = GeneratorService(GeneratorRepository(session), LogRepository(session))
        await service.rename_generators_init()
        await session.commit()

    dp.include_router(admin.router)  # first: admin-only texts like "Admin Panel"
    dp.include_router(common.router)
    dp.include_router(inventory.router)
    dp.include_router(sessions.router)
    dp.include_router(generators.router)
    dp.include_router(weather.router)

    start_scheduler(bot, redis_client, schedule_parser)
    await restore_scheduler_settings(redis_client)

    logging.info("Bot started and polling...")

    try:
        while True:
            try:
                await dp.start_polling(bot)
                break
            except asyncio.CancelledError:
                logging.info("Bot stopped by user")
                break
            except Exception:
                logging.exception(f"Polling error. Restarting in {POLLING_RESTART_DELAY_SECONDS} sec...")
                await asyncio.sleep(POLLING_RESTART_DELAY_SECONDS)
    finally:
        await bot.session.close()
        await anthropic_client.close()
        await redis_client.aclose()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Graceful shutdown, no traceback
