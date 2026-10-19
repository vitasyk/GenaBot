import asyncio
import html
import logging
import re
from datetime import datetime, time, timedelta

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import config
from bot.database.models import GenStatus, RefuelSession, SessionStatus, User
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.schedule import ScheduleRepository
from bot.database.repositories.session import SessionRepository
from bot.database.repositories.session_helpers import (
    get_all_workers_for_session,
    split_workers,
)
from bot.database.repositories.user import UserRepository
from bot.keyboards.inline_kb import get_start_generator_kb
from bot.keyboards.session_kb import get_start_session_kb
from bot.services.antigel import AntigelService, format_advice
from bot.services.google_sheets import GoogleSheetsService
from bot.services.notifier import NotifierService
from bot.services.weather import WeatherService
from bot.utils.clock import now_local

# Outage warning goes out this long after the scheduled start, so power that is cut a bit late still counts
OUTAGE_WARNING_DELAY = timedelta(minutes=5)
# A bot restart later than this into the outage doesn't send a stale warning
OUTAGE_WARNING_WINDOW = timedelta(hours=1)
OUTAGE_WARNED_KEY = "outage:warned:{start}"

class SessionService:
    def __init__(self, session: AsyncSession, bot=None, redis: Redis | None = None):
        self.repo = SessionRepository(session)
        self.user_repo = UserRepository(session)
        self.schedule_repo = ScheduleRepository(session)
        self.gen_repo = GeneratorRepository(session)
        self.sheets_service = GoogleSheetsService()
        self.notifier = NotifierService(bot) if bot else None
        # Remembers which outage warnings were sent; without it (admin force check) no warnings are sent
        self.redis = redis
        self.antigel = AntigelService(WeatherService(), redis)

    async def _get_workers_from_sheets(self, lookup_dt: datetime) -> list[tuple[str, str]]:
        # gspread is blocking: keep it off the event loop
        return await asyncio.to_thread(
            self.sheets_service.get_workers_for_outage,
            outage_start_hour=lookup_dt.hour,
            target_date=lookup_dt.date(),
        )

    async def get_outage_timeline_from_db(self, queue: str) -> list[datetime]:
        """
        Get timeline from manual database entries instead of parser.
        Returns a list of datetime objects (on the hour) when outages are scheduled.
        """
        today = now_local().date()
        tomorrow = today + timedelta(days=1)
        
        # Get entries for today and tomorrow
        entries_today = await self.schedule_repo.get_entries_for_date(today, queue)
        entries_tomorrow = await self.schedule_repo.get_entries_for_date(tomorrow, queue)
        
        timeline = []
        for entry in entries_today + entries_tomorrow:
            # Each entry has start_hour and end_hour (exclusive)
            for hour in range(entry.start_hour, entry.end_hour):
                dt = datetime.combine(entry.date, time(hour, 0))
                timeline.append(dt)
        
        return sorted(list(set(timeline)))  # Remove duplicates and sort

    async def check_power_outage(self) -> RefuelSession | None:
        """
        Check outage timeline and create session for any recently finished block.
        Ensures workers are notified in real-time when power returns according to schedule.
        """
        now = now_local()
        await self._expire_overdue_session(now)

        # 1. Fetch Timeline from DATABASE
        timeline = await self.get_outage_timeline_from_db(queue=config.QUEUE_NUMBER)
        if not timeline:
            return None

        # 2. Group timeline into continuous blocks
        blocks = []
        if timeline:
            current_block = [timeline[0]]
            for i in range(1, len(timeline)):
                if timeline[i] == timeline[i-1] + timedelta(hours=1):
                    current_block.append(timeline[i])
                else:
                    blocks.append(current_block)
                    current_block = [timeline[i]]
            blocks.append(current_block)

        # 3. Analyze each block for "Power Return" events
        for block in blocks:
            block_end = block[-1]
            deadline = block_end + timedelta(hours=1)

            # --- Condition B: Outage started -> ask to mark the generator as running ---
            warn_at = block[0] + OUTAGE_WARNING_DELAY
            if warn_at <= now < min(warn_at + OUTAGE_WARNING_WINDOW, deadline):
                await self._warn_outage_started(block[0], deadline)

            # --- Condition A: Outage Transition (Power Return) ---
            # Trigger if we are at or past the deadline, but within a 'catch-up' window (e.g. 60 mins)
            # This is the PRIMARY trigger for refueling sessions.
            if now >= deadline and now < deadline + timedelta(hours=1):
                # Check if session already exists for this block
                # We use deadline (power return time) as the storage key for start_time
                if await self.repo.exists_by_start_time(deadline):
                    continue
                
                # Create session for this finished block
                # deadline is the time power returned
                return await self._create_outage_session(block[0], deadline)

        return None

    async def _warn_outage_started(self, block_start: datetime, power_back: datetime) -> None:
        """Once per outage: tell workers on shift the power should be off and ask them to mark the
        generator as started. Skipped when a generator is already running."""
        if not self.notifier or not self.redis:
            return
        gens = await self.gen_repo.get_all(active_only=True)
        if not gens or any(g.status == GenStatus.running for g in gens):
            return
        key = OUTAGE_WARNED_KEY.format(start=block_start.isoformat())
        if not await self.redis.set(key, 1, ex=int(timedelta(days=2).total_seconds()), nx=True):
            return

        worker_ids, worker_tags = await self._resolve_workers(block_start + OUTAGE_WARNING_DELAY)
        msg = (f"⚠️ <b>Можливе відключення електрики</b>\n\n"
               f"За графіком (черга {html.escape(config.QUEUE_NUMBER)}) світло мало зникнути о "
               f"{block_start.strftime('%H:%M')} (до {power_back.strftime('%H:%M')}).\n"
               f"Якщо генератор увімкнувся, позначте це кнопкою нижче.")
        kb = get_start_generator_kb(gens)
        for worker_id in worker_ids:
            await self.notifier.notify_user(worker_id, msg, reply_markup=kb)
        await self.notifier.notify_admins(
            f"{msg}\n\n👷 Надіслано черговим ({len(worker_ids)}): {', '.join(worker_tags) or 'невідомо'}"
        )

    async def _expire_overdue_session(self, now: datetime) -> None:
        """Reminds once when an open session passes its deadline. The session moves to 'expired'
        (no longer pending, so no repeat), and workers can still complete it."""
        for overdue in await self.repo.get_overdue_sessions(now):
            await self.repo.update_status(overdue.id, SessionStatus.expired)
            if not self.notifier:
                continue
            deadline_str = overdue.deadline.strftime('%H:%M')
            msg = (f"🔔 <b>Час спливає!</b> Сесія {overdue.id} досягла дедлайну о {deadline_str}. "
                   f"Будь ласка, завершіть заправку.")
            for worker_id in get_all_workers_for_session(overdue):
                await self.notifier.notify_user(worker_id, msg)
            await self.notifier.notify_admins(
                f"📢 <b>Дедлайн сесії!</b> Сесія {overdue.id} не завершена до {deadline_str}."
            )

    async def _create_outage_session(self, block_start: datetime, deadline: datetime) -> RefuelSession:
        """Internal helper to create session and notify workers/admins"""
        now = now_local()

        # Workers on shift JUST BEFORE restoration
        lookup_dt = deadline - timedelta(minutes=1)
        worker_ids, worker_tags = await self._resolve_workers(lookup_dt)
        w1_id, w2_id, w3_id, additional_workers = split_workers(worker_ids)

        session = await self.repo.create_session(
            start_time=deadline,  # Notified at power return
            deadline=now + timedelta(hours=2),
            worker1_id=w1_id,
            worker2_id=w2_id,
            worker3_id=w3_id,
            additional_workers=additional_workers
        )

        if self.notifier:
            def fmt_dt(dt: datetime) -> str:
                return dt.strftime('%H:%M') if dt.date() == now.date() else dt.strftime('%d.%m %H:%M')

            tags_str = ", ".join(worker_tags) or "невідомо"
            msg = f"⚡ <b>Світло з'явилося!</b>\n\n" \
                  f"⏰ Період відключення: {fmt_dt(block_start)} - {fmt_dt(deadline)}\n" \
                  f"👷 На зміні були: {tags_str}\n\n" \
                  f"Будь ласка, заправте генератор(и) та завершіть сесію."
            msg += await self._antigel_hints()
            await self._notify_workers(session, msg)

            admin_msg = f"🚀 <b>Створено сесію заправки</b> (ID: {session.id})\n" \
                        f"⏰ Період: {fmt_dt(block_start)} - {fmt_dt(deadline)}\n" \
                        f"👷 Воркери ({len(worker_ids)}): {tags_str}\n"
            if not worker_ids:
                admin_msg += "❌ <b>Помилка:</b> Воркерів не знайдено!"
            await self.notifier.notify_admins(admin_msg)

        return session

    async def _antigel_hints(self) -> str:
        """Anti-gel reminders for the refuel that is about to happen ("" when none is needed)."""
        hints = []
        for gen in await self.gen_repo.get_all(active_only=True):
            advice = await self.antigel.advise_for(gen)
            if advice.needed:
                hints.append(format_advice(gen.name, advice, extra_hint=True))
        return "".join(f"\n\n{h}" for h in hints)

    async def _notify_workers(self, session: RefuelSession, msg: str) -> None:
        kb = get_start_session_kb(session.id)
        for worker_id in get_all_workers_for_session(session):
            await self.notifier.notify_user(worker_id, msg, reply_markup=kb)

    async def _resolve_workers(self, lookup_dt: datetime) -> tuple[list[int], list[str]]:
        """Workers on shift at lookup_dt: (ids of those registered in the bot, display tags for all)."""
        try:
            worker_tuples = await self._get_workers_from_sheets(lookup_dt)
        except Exception:
            logging.exception(f"Failed to get workers from Google Sheets for {lookup_dt}")
            return [], []
        logging.info(f"Sheets returned workers for {lookup_dt}: {[w[0] for w in worker_tuples]}")

        worker_ids, worker_tags = [], []
        for name, _phone in worker_tuples:
            user = await self._find_user_by_name_robust(name)
            if user:
                worker_ids.append(user.id)
            worker_tags.append(self._get_worker_tag(user.id if user else None, name))
        return list(dict.fromkeys(worker_ids)), worker_tags

    def _get_worker_tag(self, worker_id: int | None, name: str) -> str:
        """Helper to create HTML mention if ID is available, else just bold name"""
        name = html.escape(name)
        if worker_id:
            return f"<a href='tg://user?id={worker_id}'>{name}</a>"
        return f"<b>{name}</b>"

    async def _find_user_by_name_robust(self, name: str) -> User | None:
        """Attempt to find user by sheet_name or telegram name with some flexibility"""
        if not name:
            return None

        name = name.strip()
        # Sheet names may carry prefixes like 'а64 ' or 'a81 ' (sometimes twice)
        clean_name = re.sub(r'^[аa]\d+\s+', '', re.sub(r'^[аa]\d+\s+', '', name)).strip()

        for candidate in dict.fromkeys([name, clean_name]):
            user = await self.user_repo.get_by_sheet_name(candidate) or await self.user_repo.get_by_name(candidate)
            if user:
                return user

        logging.warning(f"Could not find ID for worker: '{name}' (Cleaned: '{clean_name}')")
        return None

    async def create_manual_session(self, hours: int = 2) -> RefuelSession:
        """Manually create a session starting now for X hours"""
        now = now_local()
        deadline = now + timedelta(hours=hours)

        # Use 1 minute before to avoid picking 'just-started' shifts at boundary hours
        worker_ids, worker_tags = await self._resolve_workers(now - timedelta(minutes=1))
        w1_id, w2_id, w3_id, additional_workers = split_workers(worker_ids)

        session = await self.repo.create_session(
            start_time=now,
            deadline=deadline,
            worker1_id=w1_id,
            worker2_id=w2_id,
            worker3_id=w3_id,
            additional_workers=additional_workers
        )

        if self.notifier:
            tags_str = ", ".join(worker_tags) or "невідомо"
            await self.notifier.notify_admins(
                f"📝 <b>Ручне створення сесії</b>\n"
                f"ID: {session.id}\n"
                f"Дедлайн: {deadline.strftime('%H:%M')}\n"
                f"👷 Воркери ({len(worker_ids)}): {tags_str}"
            )
            await self._notify_workers(
                session,
                f"🔔 <b>Ручний запуск сесії!</b>\n\n"
                f"⏰ Дедлайн: {deadline.strftime('%H:%M')}\n"
                f"👷 На зміні: {tags_str}\n\n"
                f"Потрібно заправити генератор!"
            )

        return session
