import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from bot.config import config


async def main():
    logging.basicConfig(level=logging.INFO)
    
    bot = Bot(token=config.BOT_TOKEN.get_secret_value())
    
    redis_url = config.REDIS_URL.get_secret_value()
    # Adding socket_keepalive and retry options to prevent connection drops (WinError 64)
    from redis.asyncio import Redis
    redis_client = Redis.from_url(
        redis_url,
        socket_keepalive=True,
        socket_connect_timeout=10,
        retry_on_timeout=True,
        health_check_interval=30
    )
    storage = RedisStorage(redis=redis_client)
    dp = Dispatcher(storage=storage)
    
    # Setup Bot Commands
    from aiogram.types import BotCommand
    commands = [
        BotCommand(command="start", description="🚀 Запуск бота"),
        BotCommand(command="menu", description="👋 Головне меню"),
        BotCommand(command="help", description="🆘 Допомога"),
    ]
    await bot.set_my_commands(commands)
    
    # Register middlewares
    from bot.database.main import session_maker
    from bot.middlewares.access import AccessMiddleware
    from bot.middlewares.di import DbSessionMiddleware
    from bot.services.notifier import NotifierService
    notifier = NotifierService(bot)
    
    dp.update.middleware(DbSessionMiddleware(session_maker, redis_client, notifier))
    # Runs after DbSessionMiddleware (needs user_repo): blocks blocked/unknown users
    dp.message.outer_middleware(AccessMiddleware())
    dp.callback_query.outer_middleware(AccessMiddleware())
    
    # Register routers
    from bot.handlers import (
        admin,
        common,
        errors,
        generators,
        inventory,
        schedule,
        sessions,
        weather,
    )
    
    dp.include_router(admin.router) # Priority for admin commands like "Admin Panel"
    dp.include_router(schedule.router) # Schedule management
    dp.include_router(common.router)
    dp.include_router(inventory.router)
    dp.include_router(sessions.router)
    dp.include_router(generators.router)
    dp.include_router(weather.router)
    dp.include_router(errors.router)  # global error handler: catches exceptions from every router
    
    # Start Scheduler
    from bot.scheduler import restore_scheduler_settings, scheduler, start_scheduler
    start_scheduler(bot, redis_client)
    try:
        await restore_scheduler_settings(redis_client)
        logging.info("Bot started and polling...")
        # aiogram retries network errors inside start_polling itself
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await redis_client.aclose()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Graceful shutdown, no traceback

