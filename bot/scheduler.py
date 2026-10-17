import html
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from redis.asyncio import Redis

from bot.database.main import session_maker
from bot.database.models import GenStatus
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.inventory import InventoryRepository
from bot.generator_specs import LITERS_PER_CAN
from bot.services.notifier import NotifierService
from bot.services.runtime_settings import SCHEDULE_INTERVAL_KEY
from bot.services.schedule_parser import ScheduleParser
from bot.services.weather import WeatherService
from bot.utils.clock import KYIV_TZ, now_kyiv

scheduler = AsyncIOScheduler(timezone=KYIV_TZ)

CHECK_POWER_OUTAGE_JOB_ID = "check_power_outage_job"
DEFAULT_OUTAGE_CHECK_MINUTES = 15

ROTATION_CHECK_MINUTES = 30
ROTATION_WARN_HOURS = 4
ROTATION_CRITICAL_HOURS = 6
# Slightly longer than one check interval, so the warning goes out once
ROTATION_WARN_WINDOW_HOURS = 0.6

MAINTENANCE_CHECK_HOURS = 12
MAINTENANCE_INTERVAL_HOURS = 100
# Last notified multiple of MAINTENANCE_INTERVAL_HOURS per generator
MAINTENANCE_NOTIFIED_KEY = "maintenance:notified:{gen_id}"

WEATHER_REPORT_HOUR = 8

async def check_rotation_needed(bot: Bot):
    async with session_maker() as session:
        gens = await GeneratorRepository(session).get_all(active_only=False)
        running_gen = next((g for g in gens if g.status == GenStatus.running), None)
        if not running_gen or not running_gen.current_run_start:
            return

        hours_run = (now_kyiv() - running_gen.current_run_start).total_seconds() / 3600
        name = html.escape(running_gen.name)

        msg = ""
        if hours_run >= ROTATION_CRITICAL_HOURS:
            msg = f"🔴 <b>УВАГА: ПОТРІБНА РОТАЦІЯ!</b>\nГенератор {name} працює вже {hours_run:.1f} год.\nТерміново перемкніть на інший!"
        elif ROTATION_WARN_HOURS <= hours_run < ROTATION_WARN_HOURS + ROTATION_WARN_WINDOW_HOURS:
            stock_liters = await InventoryRepository(session).get_stock()
            fuel_status = f"Запас на складі: {stock_liters / LITERS_PER_CAN:.1f} каністр ({stock_liters} л)."
            if stock_liters < LITERS_PER_CAN:
                fuel_status += " ⚠️ МАЛО ПАЛИВА! Немає чим заправити наступний."

            fuel_left = running_gen.fuel_level
            burn_rate = running_gen.consumption_rate
            time_left = fuel_left / burn_rate if burn_rate > 0 else 0

            msg = (f"⚠️ <b>Рекомендовано ротацію</b>\n"
                   f"{name} працює: {hours_run:.1f} год.\n"
                   f"У баку: {fuel_left:.1f}л (~{time_left:.1f} год).\n"
                   f"{fuel_status}\n"
                   f"Плануйте перемикання у найближчі 2 години.")

    if msg:
        await NotifierService(bot).notify_all(msg)

async def check_maintenance_needed(bot: Bot, redis: Redis):
    """Notifies once each time a generator crosses another MAINTENANCE_INTERVAL_HOURS of runtime."""
    async with session_maker() as session:
        gens = await GeneratorRepository(session).get_all(active_only=False)

    notifier = NotifierService(bot)
    for g in gens:
        total = g.total_hours_run or 0.0
        reached = int(total // MAINTENANCE_INTERVAL_HOURS)
        key = MAINTENANCE_NOTIFIED_KEY.format(gen_id=g.id)
        notified = await redis.get(key)

        if notified is None:
            # First run for this generator: remember the current mark, alert from the next one
            await redis.set(key, reached)
            continue
        if reached > int(notified):
            await notifier.notify_all(
                f"🔧 <b>ТЕХНІЧНЕ ОБСЛУГОВУВАННЯ</b>\nГенератор {html.escape(g.name)} відпрацював {total:.1f} год.\n"
                f"Час перевірити масло!"
            )
            await redis.set(key, reached)

async def weather_check_job(bot: Bot):
    report = await WeatherService().get_daily_report()
    if report:
        await NotifierService(bot).notify_all(report)

async def check_power_outage_job(bot: Bot, parser: ScheduleParser):
    from bot.services.session_service import SessionService
    async with session_maker() as session:
        await SessionService(session, parser, bot=bot).check_power_outage()

def start_scheduler(bot: Bot, redis: Redis, parser: ScheduleParser):
    scheduler.add_job(check_rotation_needed, IntervalTrigger(minutes=ROTATION_CHECK_MINUTES), args=[bot])
    scheduler.add_job(check_maintenance_needed, IntervalTrigger(hours=MAINTENANCE_CHECK_HOURS), args=[bot, redis])
    scheduler.add_job(weather_check_job, CronTrigger(hour=WEATHER_REPORT_HOUR, minute=0), args=[bot])
    # Explicit ID so the admin panel can reschedule it
    scheduler.add_job(
        check_power_outage_job,
        IntervalTrigger(minutes=DEFAULT_OUTAGE_CHECK_MINUTES),
        args=[bot, parser],
        id=CHECK_POWER_OUTAGE_JOB_ID,
        replace_existing=True
    )
    scheduler.start()

async def restore_scheduler_settings(redis: Redis):
    """Applies the outage check interval saved from the admin panel."""
    try:
        interval = await redis.get(SCHEDULE_INTERVAL_KEY)
        if interval:
            minutes = int(interval)
            scheduler.reschedule_job(CHECK_POWER_OUTAGE_JOB_ID, trigger='interval', minutes=minutes)
            logging.info(f"Restored schedule check interval: {minutes} min")
    except Exception:
        logging.exception("Failed to restore scheduler settings")
