import html
import json
import logging
from collections.abc import Sequence

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
from redis.asyncio import Redis

from bot.config import config
from bot.database.main import session_maker
from bot.database.repositories.inventory import InventoryRepository
from bot.database.repositories.generator import GeneratorRepository
from bot.database.models import Generator, GenStatus
from bot.services.notifier import NotifierService
from bot.services.weather import WeatherService
from aiogram import Bot
import zoneinfo

# Initialize scheduler with configured timezone
scheduler = AsyncIOScheduler(timezone=zoneinfo.ZoneInfo(config.TIMEZONE))

DEFAULT_OUTAGE_CHECK_MINUTES = 1
MAINTENANCE_INTERVAL_HOURS = 100
MAINTENANCE_MARK_KEY = "maintenance:last_mark:{gen_id}"
# config attribute -> Redis key for values admins change at runtime
RUNTIME_SETTING_KEYS = {
    "RESTRICT_ACCESS": "config:restrict_access",
    "NOTIFY_WORKERS": "config:notify_workers",
    "FUEL_THRESHOLD_CANS": "config:fuel_threshold_cans",
    "QUEUE_NUMBER": "config:queue_number",
}

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
            stock_liters = await inv_repo.get_stock()
            stock_cans = stock_liters / 20.0
            fuel_status = f"Запас на складі: {stock_cans:.1f} каністр ({stock_liters}л)."
            if stock_cans < 1:
                fuel_status += " ⚠️ МАЛО ПАЛИВА! Немає чим заправити наступний."
            
            # Predict remaining fuel in current gen
            # 1. Get weather factor
            weather = WeatherService()
            temp = await weather.get_current_temperature()
            factor = weather.get_consumption_factor(temp)
            
            # 2. Calculate consumed fuel during this run
            # running_gen.consumption_rate is L/h
            base_rate = running_gen.consumption_rate
            actual_rate = base_rate * factor
            consumed = hours_run * actual_rate
            
            # 3. Calculate current level
            # fuel_level is the level at start or last refuel/correction?
            # Usually fuel_level is updated ONLY when stopped or refueled. 
            # So start_level = running_gen.fuel_level
            start_level = running_gen.fuel_level
            current_level = start_level - consumed
            if current_level < 0: current_level = 0.0
            
            time_left = current_level / actual_rate if actual_rate > 0 else 0
            
            msg = (f"⚠️ <b>Рекомендовано ротацію</b>\n"
                   f"{running_gen.name} працює: {hours_run:.1f} год.\n"
                   f"У баку: {current_level:.1f}л (~{time_left:.1f} год).\n"
                   f"{fuel_status}\n"
                   f"Плануйте перемикання у найближчі 2 години.")

        if msg:
            from bot.services.notifier import NotifierService
            notifier = NotifierService(bot)
            await notifier.notify_all(msg)

async def notify_maintenance_due(gens: Sequence[Generator], redis: Redis, notifier: NotifierService) -> None:
    """Alert once each time a generator's total hours cross a new MAINTENANCE_INTERVAL_HOURS mark.

    The last notified mark per generator lives in Redis. With no stored mark (first run)
    the current one is stored silently, so old marks don't trigger alerts.
    """
    for g in gens:
        total = g.total_hours_run or 0.0
        mark = int(total // MAINTENANCE_INTERVAL_HOURS)
        key = MAINTENANCE_MARK_KEY.format(gen_id=g.id)
        stored = await redis.get(key)
        last_mark = int(stored) if stored is not None else None
        if last_mark == mark:
            continue
        await redis.set(key, mark)
        if last_mark is not None and mark > last_mark:
            await notifier.notify_all(
                f"🔧 <b>ТЕХНІЧНЕ ОБСЛУГОВУВАННЯ</b>\nГенератор {html.escape(g.name)} "
                f"відпрацював {total:.1f} год.\nЧас перевірити масло!"
            )


async def check_maintenance_needed(bot: Bot):
    async with session_maker() as session:
        gens = await GeneratorRepository(session).get_all()

    redis = Redis.from_url(config.REDIS_URL.get_secret_value())
    try:
        await notify_maintenance_due(gens, redis, NotifierService(bot))
    finally:
        await redis.close()

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

async def antigel_reminder_job(bot: Bot):
    """Morning reminder while it's still warm enough for the additive to work."""
    from bot.services.antigel import AntigelService, format_advice
    redis = Redis.from_url(config.REDIS_URL.get_secret_value())
    try:
        async with session_maker() as session:
            gens = await GeneratorRepository(session).get_all(active_only=True)
        antigel = AntigelService(WeatherService(), redis)
        for g in gens:
            advice = await antigel.advise_for(g)
            if advice.needed:
                await NotifierService(bot).notify_all(format_advice(g.name, advice))
    finally:
        await redis.close()

async def check_power_outage_job(bot: Bot):
    from bot.services.session_service import SessionService
    redis = Redis.from_url(config.REDIS_URL.get_secret_value())
    try:
        async with session_maker() as session:
            service = SessionService(session, bot=bot, redis=redis)
            await service.check_power_outage()
    finally:
        await redis.close()

async def warming_check_job(bot: Bot):
    from bot.services.generator import GeneratorService
    from bot.database.repositories.generator import GeneratorRepository
    from bot.database.repositories.logs import LogRepository

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
    scheduler.add_job(antigel_reminder_job, CronTrigger(hour=8, minute=5), args=[bot])
    
    # Check Power Outage: 1 min by default; the admin-set interval is restored from Redis
    # by restore_scheduler_settings. Explicit ID so it can be rescheduled.
    scheduler.add_job(
        check_power_outage_job,
        IntervalTrigger(minutes=DEFAULT_OUTAGE_CHECK_MINUTES),
        args=[bot],
        id="check_power_outage_job",
        replace_existing=True
    )

    scheduler.start()


async def save_runtime_setting(redis: Redis, name: str, value: bool | float | str) -> None:
    """Persist an admin-changed config value so it survives a restart."""
    await redis.set(RUNTIME_SETTING_KEYS[name], json.dumps(value))


async def restore_runtime_settings(redis: Redis) -> None:
    """Apply admin-changed config values saved in Redis over the .env defaults."""
    for name, key in RUNTIME_SETTING_KEYS.items():
        raw = await redis.get(key)
        if raw is None:
            continue
        default = getattr(config, name)
        try:
            value = json.loads(raw)
            if isinstance(default, bool) and not isinstance(value, bool):
                raise ValueError("expected a boolean")
            setattr(config, name, type(default)(value))
        except (ValueError, TypeError):
            logging.warning("Ignoring invalid saved setting %s=%r", name, raw, exc_info=True)


async def restore_scheduler_settings(redis: Redis) -> None:
    """Called from main at startup: restores the check interval and runtime settings."""
    try:
        interval = await redis.get("config:schedule_interval")
        if interval:
            minutes = int(interval)
            scheduler.reschedule_job('check_power_outage_job', trigger='interval', minutes=minutes)
            logging.info("Restored schedule check interval: %s min", minutes)
        await restore_runtime_settings(redis)
    except Exception:
        logging.exception("Failed to restore scheduler settings")
