import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta

from bot.config import config
from bot.database.main import session_maker
from bot.database.repositories.inventory import InventoryRepository
from bot.database.repositories.generator import GeneratorRepository
from bot.database.models import GenStatus
from bot.services.weather import WeatherService
from aiogram import Bot

scheduler = AsyncIOScheduler()

async def check_rotation_needed(bot: Bot):
    async with session_maker() as session:
        gen_repo = GeneratorRepository(session)
        inv_repo = InventoryRepository(session)
        
        gens = await gen_repo.get_all()
        running_gen = next((g for g in gens if g.status == GenStatus.running), None)
        
        if not running_gen or not running_gen.current_run_start:
            return

        # Calculate duration
        now = datetime.utcnow()
        duration = now - running_gen.current_run_start
        hours_run = duration.total_seconds() / 3600
        
        # Thresholds
        WARN_HOURS = 4
        CRITICAL_HOURS = 6
        
        msg = ""
        if hours_run >= CRITICAL_HOURS:
            msg = f"⚠️ <b>УВАГА: ПОТРІБНА РОТАЦІЯ!</b>\nГенератор {running_gen.name} працює вже {hours_run:.1f} год.\nТерміново перемкніть на інший!"
        elif hours_run >= WARN_HOURS and hours_run < WARN_HOURS + 0.6: 
            # Check inventory for next gen
            stock = await inv_repo.get_stock()
            fuel_status = f"Запас на складі: {stock} каністр."
            if stock < 1:
                fuel_status += " ⚠️ МАЛО ПАЛИВА! Немає чим заправити наступний."
            
            # Predict remaining fuel in current gen
            fuel_left = running_gen.fuel_level
            burn_rate = running_gen.consumption_rate
            time_left = fuel_left / burn_rate if burn_rate > 0 else 0
            
            msg = (f"⚠️ <b>Рекомендовано ротацію</b>\n"
                   f"{running_gen.name} працює: {hours_run:.1f} год.\n"
                   f"У баку: {fuel_left:.1f}л (~{time_left:.1f} год).\n"
                   f"{fuel_status}\n"
                   f"Плануйте перемикання у найближчі 2 години.")

        if msg:
            from bot.services.notifier import NotifierService
            notifier = NotifierService(bot)
            await notifier.notify_all(msg)

async def check_maintenance_needed(bot: Bot):
    async with session_maker() as session:
        gen_repo = GeneratorRepository(session)
        gens = await gen_repo.get_all()
        
        from bot.services.notifier import NotifierService
        notifier = NotifierService(bot)
        
        for g in gens:
            total = g.total_hours_run or 0.0
            # Example: Alert every 100 hours
            # Or if hours since last maintenance > 100
            # For simplicity, let's just alert if total is near a multiple of 100 for now, 
            # but better logic: track 'hours_since_last_oil_change'.
            # We'll use 100h threshold.
            if total > 0 and (total % 100) < 0.5: # Simple trigger near the mark
                 await notifier.notify_all(f"🔧 <b>ТЕХНІЧНЕ ОБСЛУГОВУВАННЯ</b>\nГенератор {g.name} відпрацював {total:.1f} год.\nЧас перевірити масло!")

async def weather_check_job(bot: Bot):
    from bot.services.notifier import NotifierService
    from bot.services.weather import WeatherService
    notifier = NotifierService(bot)
    weather = WeatherService()
    
    # Send daily report
    report = await weather.get_daily_report()
    if report:
        await notifier.notify_all(report)
                
    
    # Also check for critical alerts using separate logic if needed, 
    # but daily report covers it for 8 AM. 
    # If we wanted continuous monitoring, we'd add another job.

async def check_power_outage_job(bot: Bot):
    from bot.services.session_service import SessionService
    async with session_maker() as session:
        service = SessionService(session, bot=bot)
        await service.check_power_outage()

async def warming_check_job(bot: Bot):
    from bot.services.generator import GeneratorService
    from bot.database.repositories.generator import GeneratorRepository
    from bot.database.repositories.logs import LogRepository
    from redis.asyncio import Redis
    from bot.config import config
    
    redis_client = Redis.from_url(config.REDIS_URL.get_secret_value())
    
    async with session_maker() as session:
        gen_repo = GeneratorRepository(session)
        log_repo = LogRepository(session)
        from bot.services.notifier import NotifierService
        notifier = NotifierService(bot)
        
        service = GeneratorService(gen_repo, log_repo, notifier, redis_client)
        await service.check_warming_notifications()
    
    await redis_client.close()

def start_scheduler(bot: Bot):
    # Check rotation every 30 mins
    scheduler.add_job(check_rotation_needed, IntervalTrigger(minutes=30), args=[bot])
    
    # Check maintenance every 12 hours
    scheduler.add_job(check_maintenance_needed, IntervalTrigger(hours=12), args=[bot])
    
    # Check warming every 1 hour
    scheduler.add_job(warming_check_job, IntervalTrigger(hours=1), args=[bot])
    
    # Check weather daily at 8:00 AM
    scheduler.add_job(weather_check_job, CronTrigger(hour=8, minute=0), args=[bot])
    
    # Check Power Outage (Dynamic Interval)
    # Default 1 min for near-real-time reactive notifications
    interval_minutes = 1
    
    try:
        # Try to read from Redis synchronously? 
        # RedisStorage is async. We can't await here easily in sync function.
        # However, scheduler is async, but setup is often sync.
        # Workaround: Just use default here, and let the Admin handler update it at runtime.
        # BUT user wanted persistence.
        # We can use `asyncio.create_task` to update it after startup?
        # Or just make start_scheduler async?
        pass
    except:
        pass

    # We use explicit ID so we can reschedule it later
    scheduler.add_job(
        check_power_outage_job, 
        IntervalTrigger(minutes=interval_minutes), 
        args=[bot],
        id="check_power_outage_job",
        replace_existing=True
    )
    
    scheduler.start()

async def restore_scheduler_settings(bot: Bot):
    """Called from main to restore dynamic settings"""
    from aiogram.fsm.storage.redis import RedisStorage
    from bot.config import config
    
    # We need access to the storage used by Dispatcher... 
    # Or just create a new client since it's Redis.
    storage = RedisStorage.from_url(config.REDIS_URL.get_secret_value())
    
    try:
        # storage.redis is a redis.asyncio.Redis instance
        interval = await storage.redis.get("config:schedule_interval")
        if interval:
            minutes = int(interval)
            scheduler.reschedule_job('check_power_outage_job', trigger='interval', minutes=minutes)
            logging.info(f"Restored schedule check interval: {minutes} min")
    except Exception as e:
        logging.error(f"Failed to restore scheduler settings: {e}")
    finally:
        await storage.close()
