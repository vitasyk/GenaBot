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
    from bot.middlewares.di import DbSessionMiddleware
    
    from bot.services.notifier import NotifierService
    notifier = NotifierService(bot)
    
    dp.update.middleware(DbSessionMiddleware(session_maker, redis_client, notifier))
    
    # Run DB Init/Renaming
    from bot.services.generator import GeneratorService
    from bot.database.repositories.generator import GeneratorRepository
    from bot.database.repositories.logs import LogRepository


    async with session_maker() as session:
        gen_repo = GeneratorRepository(session)
        log_repo = LogRepository(session)
        service = GeneratorService(gen_repo, log_repo, notifier, redis_client)
        await service.rename_generators_init()
        await session.commit()    
    # Register routers
    from bot.handlers import common, inventory, generators, weather, admin, sessions, schedule
    
    dp.include_router(admin.router) # Priority for admin commands like "Admin Panel"
    dp.include_router(schedule.router) # Schedule management
    dp.include_router(common.router)
    dp.include_router(inventory.router)
    dp.include_router(sessions.router)
    dp.include_router(generators.router)
    dp.include_router(weather.router)
    
    # Start Scheduler
    from bot.scheduler import start_scheduler, restore_scheduler_settings
    start_scheduler(bot)
    await restore_scheduler_settings(bot)
    
    logging.info("Bot started and polling...")
    
    while True:
        try:
            await dp.start_polling(bot)
        except asyncio.CancelledError:
            logging.info("Bot stopped by user")
            break
        except Exception as e:
            logging.error(f"Polling error: {e}. Restarting in 5 sec...")
            await asyncio.sleep(5)
    
    await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass  # Graceful shutdown, no traceback

