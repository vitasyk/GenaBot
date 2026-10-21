import html
import json
import logging
import zoneinfo
from collections.abc import Sequence

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from redis.asyncio import Redis

from bot.config import config
from bot.database.main import session_maker
from bot.database.models import Generator, GenStatus
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.inventory import InventoryRepository
from bot.services.inventory import LITERS_PER_CAN
from bot.services.maintenance import format_status, maintenance_status
from bot.services.notifier import NotifierService
from bot.services.weather import WeatherService
from bot.utils.clock import now_local, utcnow

logger = logging.getLogger(__name__)

# Initialize scheduler with configured timezone
scheduler = AsyncIOScheduler(timezone=zoneinfo.ZoneInfo(config.TIMEZONE))

DEFAULT_OUTAGE_CHECK_MINUTES = 1
MAINTENANCE_NOTIFIED_KEY = "maintenance:notified:{gen_id}"
# Continuous run hours: recommend switching / demand switching to another generator
ROTATION_WARN_HOURS = 4
ROTATION_CRITICAL_HOURS = 6
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
        now = utcnow()
        duration = now - running_gen.current_run_start
        hours_run = duration.total_seconds() / 3600

        msg = ""
        if hours_run >= ROTATION_CRITICAL_HOURS:
            msg = f"⚠️ <b>УВАГА: ПОТРІБНА РОТАЦІЯ!</b>\nГенератор {running_gen.name} працює вже {hours_run:.1f} год.\nТерміново перемкніть на інший!"
        elif hours_run >= ROTATION_WARN_HOURS and hours_run < ROTATION_WARN_HOURS + 0.6:
            # Check inventory for next gen
            stock_liters = await inv_repo.get_stock()
            stock_cans = stock_liters / LITERS_PER_CAN
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
    """Alert once when maintenance gets close ("soon") and once when it is due.

    Redis stores "<last service time>:<level>" per generator, so a newly recorded service starts over.
    Generators without a recorded service are skipped.
    """
    today = now_local().date()
    for g in gens:
        st = maintenance_status(g, today)
        if st is None:
            continue
        key = MAINTENANCE_NOTIFIED_KEY.format(gen_id=g.id)
        value = f"{g.last_maintenance.isoformat()}:{st.level}"
        stored = await redis.get(key)
        if st.level == "ok" or (stored is not None and stored.decode() == value):
            continue
        await redis.set(key, value)
        title = "🛑 <b>ПОТРІБНЕ ТЕХОБСЛУГОВУВАННЯ</b>" if st.level == "due" else "⚠️ <b>Техобслуговування скоро</b>"
        await notifier.notify_all(f"{title}\nГенератор {html.escape(g.name)}\n{format_status(st)}")


async def check_maintenance_needed(bot: Bot, redis: Redis):
    async with session_maker() as session:
        gens = await GeneratorRepository(session).get_all()

    await notify_maintenance_due(gens, redis, NotifierService(bot))

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

async def antigel_reminder_job(bot: Bot, redis: Redis):
    """Morning reminder while it's still warm enough for the additive to work."""
    from bot.services.antigel import AntigelService, format_advice
    async with session_maker() as session:
        gens = await GeneratorRepository(session).get_all(active_only=True)
    antigel = AntigelService(WeatherService(), redis)
    for g in gens:
        advice = await antigel.advise_for(g)
        if advice.needed:
            await NotifierService(bot).notify_all(format_advice(g.name, advice))

async def check_power_outage_job(bot: Bot, redis: Redis):
    from bot.services.session_service import SessionService
    async with session_maker() as session:
        service = SessionService(session, bot=bot, redis=redis)
        await service.check_power_outage()

async def warming_check_job(bot: Bot, redis: Redis):
    from bot.database.repositories.generator import GeneratorRepository
    from bot.database.repositories.logs import LogRepository
    from bot.services.generator import GeneratorService

    async with session_maker() as session:
        gen_repo = GeneratorRepository(session)
        log_repo = LogRepository(session)
        from bot.services.notifier import NotifierService
        notifier = NotifierService(bot)

        service = GeneratorService(gen_repo, log_repo, notifier, redis)
        await service.check_warming_notifications()

def start_scheduler(bot: Bot, redis: Redis):
    """Jobs share the bot's Redis client instead of opening a connection per run."""
    # Check rotation every 30 mins
    scheduler.add_job(check_rotation_needed, IntervalTrigger(minutes=30), args=[bot])

    # Check maintenance every 12 hours
    scheduler.add_job(check_maintenance_needed, IntervalTrigger(hours=12), args=[bot, redis])

    # Check warming every 1 hour
    scheduler.add_job(warming_check_job, IntervalTrigger(hours=1), args=[bot, redis])

    # Check weather daily at 8:00 AM
    scheduler.add_job(weather_check_job, CronTrigger(hour=8, minute=0), args=[bot])
    scheduler.add_job(antigel_reminder_job, CronTrigger(hour=8, minute=5), args=[bot, redis])

    # Check Power Outage: 1 min by default; the admin-set interval is restored from Redis
    # by restore_scheduler_settings. Explicit ID so it can be rescheduled.
    scheduler.add_job(
        check_power_outage_job,
        IntervalTrigger(minutes=DEFAULT_OUTAGE_CHECK_MINUTES),
        args=[bot, redis],
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
                raise TypeError("expected a boolean")
            setattr(config, name, type(default)(value))
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid saved setting %s=%r", name, raw, exc_info=True)


async def restore_scheduler_settings(redis: Redis) -> None:
    """Called from main at startup: restores the check interval and runtime settings."""
    try:
        interval = await redis.get("config:schedule_interval")
        if interval:
            minutes = int(interval)
            scheduler.reschedule_job('check_power_outage_job', trigger='interval', minutes=minutes)
            logger.info("Restored schedule check interval: %s min", minutes)
        await restore_runtime_settings(redis)
    except Exception:
        logger.exception("Failed to restore scheduler settings")
