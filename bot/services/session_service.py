import logging
from datetime import datetime, timedelta, time
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories.session import SessionRepository
from bot.database.repositories.shift import ShiftRepository
from bot.database.repositories.user import UserRepository
from bot.database.repositories.schedule import ScheduleRepository
from bot.services.google_sheets import GoogleSheetsService
# from bot.services.schedule_parser import ScheduleParser  # DISABLED - using manual DB entries now
from bot.database.models import User, RefuelSession, SessionStatus
from bot.services.notifier import NotifierService

class SessionService:
    def __init__(self, session: AsyncSession, bot=None):
        self.db_session = session
        self.repo = SessionRepository(session)
        self.shift_repo = ShiftRepository(session)
        self.user_repo = UserRepository(session)
        self.schedule_repo = ScheduleRepository(session)
        self.sheets_service = GoogleSheetsService()
        # self.parser = ScheduleParser()  # DISABLED
        self.notifier = NotifierService(bot) if bot else None

    async def get_outage_timeline_from_db(self, queue: str = "1.1") -> List[datetime]:
        """
        Get timeline from manual database entries instead of parser.
        Returns a list of datetime objects (on the hour) when outages are scheduled.
        """
        from bot.config import config
        import zoneinfo
        tz = zoneinfo.ZoneInfo(config.TIMEZONE)
        today = datetime.now(tz).date()
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

    async def check_power_outage(self) -> Optional[RefuelSession]:
        """
        Check outage timeline and create session for any recently finished block.
        Ensures workers are notified in real-time when power returns according to schedule.
        """
        # 1. Fetch Timeline from DATABASE
        timeline = await self.get_outage_timeline_from_db(queue="1.1")
        if not timeline:
            return None
            
        from bot.config import config
        import zoneinfo
        tz = zoneinfo.ZoneInfo(config.TIMEZONE)
        now = datetime.now(tz).replace(tzinfo=None)
        
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
            # block_start = block[0]
            block_end = block[-1]
            deadline = block_end + timedelta(hours=1)
            
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

            # --- Condition B: Impending Deadline (Reminder for Active Session) ---
            # If an active session exists and its deadline is approaching/passed, notify once.
            active_session = await self.repo.get_active_session()
            if active_session and active_session.deadline == deadline:
                if now >= deadline and active_session.status in [SessionStatus.pending.value, SessionStatus.in_progress.value]:
                    msg = f"🔔 <b>Час спливає!</b> Сесія {active_session.id} досягла дедлайну о {active_session.deadline.strftime('%H:%M')}. Будь ласка, завершіть заправку."
                    
                    if active_session.worker1_id: await self.notifier.notify_user(active_session.worker1_id, msg)
                    if active_session.worker2_id: await self.notifier.notify_user(active_session.worker2_id, msg)
                    if active_session.worker3_id: await self.notifier.notify_user(active_session.worker3_id, msg)
                    await self.notifier.notify_admins(f"📢 <b>Час відновлення!</b> Сесія {active_session.id} досягла дедлайну ({active_session.deadline.strftime('%H:%M')}).")
                    
                    # Update status to avoid re-notifying
                    await self.repo.update_status(active_session.id, SessionStatus.completed)
        
        return None

    async def _create_outage_session(self, block_start: datetime, deadline: datetime) -> RefuelSession:
        """Internal helper to create session and notify workers/admins"""
        from bot.config import config
        import zoneinfo
        tz = zoneinfo.ZoneInfo(config.TIMEZONE)
        now = datetime.now(tz).replace(tzinfo=None)
        
        # Determine workers from Sheets for the period JUST BEFORE restoration
        try:
            lookup_dt = deadline - timedelta(minutes=1)
            worker_tuples = self.sheets_service.get_workers_for_outage(
                outage_start_hour=lookup_dt.hour,
                target_date=lookup_dt.date()
            )
            logging.info(f"Block detected: {block_start} to {deadline}. Lookup hour: {lookup_dt.hour}. Assigned: {[w[0] for w in worker_tuples]}")
        except Exception as e:
            logging.error(f"Failed to get workers for block: {e}")
            worker_tuples = []

        w1_id, w2_id, w3_id, additional_workers, all_worker_names = await self._get_workers_from_tuples(worker_tuples)

        # Create Session with 2-hour duration from NOW
        effective_deadline = now + timedelta(hours=2)
        
        session = await self.repo.create_session(
            start_time=deadline,  # Notified at power return
            deadline=effective_deadline,
            worker1_id=w1_id,
            worker2_id=w2_id,
            worker3_id=w3_id,
            additional_workers=additional_workers
        )
        
        
        # Notify
        if self.notifier:
            from bot.database.repositories.session_helpers import get_all_workers_for_session
            
            # Build worker tags for display
            worker_tag_list = []
            for idx, name in enumerate(all_worker_names):
                # Match name with ID
                worker_id = None
                if idx < len([w1_id, w2_id, w3_id] + additional_workers):
                    all_ids = [w1_id, w2_id, w3_id] + additional_workers
                    worker_id = all_ids[idx] if all_ids[idx] else None
                
                tag = self._get_worker_tag(worker_id, name)
                if "Unknown" not in tag:
                    worker_tag_list.append(tag)
            
            worker_tags = ", ".join(worker_tag_list) or "Unknown"

            def fmt_dt(dt):
                if dt.date() == now.date(): return dt.strftime('%H:%M')
                return dt.strftime('%d.%m %H:%M')

            msg = f"⚡ <b>Світло з'явилося!</b>\n\n" \
                  f"⏰ Період відключення: {fmt_dt(block_start)} - {fmt_dt(deadline)}\n" \
                  f"👷 На зміні були: {worker_tags}\n\n" \
                  f"Будь ласка, заправте генератор(и) та завершіть сесію."
            
            from bot.keyboards.session_kb import get_start_session_kb
            kb = get_start_session_kb(session.id)
            
            # Notify all assigned workers
            all_worker_ids = get_all_workers_for_session(session)
            for worker_id in all_worker_ids:
                await self.notifier.notify_user(worker_id, msg, reply_markup=kb)

            admin_msg = f"🚀 <b>Створено сесію заправки</b> (ID: {session.id})\n" \
                        f"⏰ Період: {fmt_dt(block_start)} - {fmt_dt(deadline)}\n" \
                        f"👷 Воркери ({len(all_worker_ids)}): {worker_tags}\n"
            
            if not all_worker_ids: admin_msg += "❌ <b>Помилка:</b> Воркерів не знайдено!"
            await self.notifier.notify_admins(admin_msg)
            
        return session

    async def _get_workers_from_tuples(self, worker_tuples):
        """Helper to lookup IDs for ALL worker name tuples (no limit)"""
        from bot.database.repositories.session_helpers import split_workers
        
        worker_ids = []
        worker_names = []
        
        for name, _phone in worker_tuples:
            user = await self._find_user_by_name_robust(name)
            if user:
                worker_ids.append(user.id)
                worker_names.append(name)
            else:
                # Keep track of unmatched names for logging
                worker_names.append(name)
                logging.warning(f"Could not find user ID for worker: {name}")
        
        # Split into first 3 + additional
        w1_id, w2_id, w3_id, additional = split_workers(worker_ids)
        
        # Return IDs, names for compatibility
        w1_n = worker_names[0] if len(worker_names) > 0 else "Unknown"
        w2_n = worker_names[1] if len(worker_names) > 1 else "Unknown"
        w3_n = worker_names[2] if len(worker_names) > 2 else "Unknown"
        
        return w1_id, w2_id, w3_id, additional, worker_names

    def _get_worker_tag(self, worker_id: int | None, name: str) -> str:
        """Helper to create HTML mention if ID is available, else just bold name"""
        if worker_id:
            return f"<a href='tg://user?id={worker_id}'>{name}</a>"
        return f"<b>{name}</b>"

    async def _get_workers_for_start_time(self, start_dt: datetime) -> tuple[int | None, int | None, int | None, List[int], List[str]]:
        """Helper to find ALL workers for a specific start time based on Sheets schedule"""
        try:
            # Use 1 minute before to avoid picking 'just-started' shifts at boundary hours
            lookup_dt = start_dt - timedelta(minutes=1)
            worker_tuples = self.sheets_service.get_workers_for_outage(
                outage_start_hour=lookup_dt.hour,
                target_date=lookup_dt.date()
            )
            
            logging.info(f"Sheets returned {len(worker_tuples)} workers for {start_dt}")
            
            # Use the same helper as _create_outage_session
            w1_id, w2_id, w3_id, additional_workers, all_worker_names = await self._get_workers_from_tuples(worker_tuples)
            
            return w1_id, w2_id, w3_id, additional_workers, all_worker_names
        except Exception as e:
            logging.error(f"Failed to get workers: {e}", exc_info=True)
            return None, None, None, [], []

    async def _find_user_by_name_robust(self, name: str) -> Optional[User]:
        """Attempt to find user by sheet_name or telegram name with some flexibility"""
        if not name or name == "Unknown":
            return None
            
        name = name.strip()
        
        # 1. Exact sheet_name
        user = await self.user_repo.get_by_sheet_name(name)
        if user: return user
        
        # 2. Exact telegram name
        user = await self.user_repo.get_by_name(name)
        if user: return user
        
        # 3. Clean names and try again (remove common prefixes like 'а64 ', 'а81 ')
        import re
        # Remove multiple prefixes like 'а64 ' or 'a81 '
        clean_name = re.sub(r'^[аa]\d+\s+', '', name).strip()
        # Sometimes there might be multiple or nested (rare but possible)
        clean_name = re.sub(r'^[аa]\d+\s+', '', clean_name).strip()
        
        if clean_name != name:
             # Try sheet_name with cleaned name
             user = await self.user_repo.get_by_sheet_name(clean_name)
             if user: return user
             # Try telegram name with cleaned name
             user = await self.user_repo.get_by_name(clean_name)
             if user: return user
             
        logging.warning(f"Could not find ID for worker: '{name}' (Cleaned: '{clean_name}')")
        return None

    async def create_manual_session(self, hours: int = 2) -> RefuelSession:
        """Manually create a session starting now for X hours"""
        from bot.config import config
        import zoneinfo
        tz = zoneinfo.ZoneInfo(config.TIMEZONE)
        now = datetime.now(tz).replace(tzinfo=None)
        deadline = now + timedelta(hours=hours)
        
        # Auto-lookup workers for manual session using current time
        worker1_id, worker2_id, worker3_id, additional_workers, all_worker_names = await self._get_workers_for_start_time(now)
        
        session = await self.repo.create_session(
            start_time=now,
            deadline=deadline,
            worker1_id=worker1_id,
            worker2_id=worker2_id,
            worker3_id=worker3_id,
            additional_workers=additional_workers
        )
        
        if self.notifier:
            from bot.database.repositories.session_helpers import get_all_workers_for_session
            
            # Build worker tags
            worker_tag_list = []
            all_worker_ids = get_all_workers_for_session(session)
            for idx, name in enumerate(all_worker_names):
                worker_id = all_worker_ids[idx] if idx < len(all_worker_ids) else None
                tag = self._get_worker_tag(worker_id, name)
                if "Unknown" not in tag:
                    worker_tag_list.append(tag)
            
            worker_tags_str = ", ".join(worker_tag_list) if worker_tag_list else "Unknown"

            msg = f"📝 <b>Ручне створення сесії</b>\n" \
                  f"ID: {session.id}\n" \
                  f"Дедлайн: {deadline.strftime('%H:%M')}\n" \
                  f"👷 Воркери ({len(all_worker_ids)}): {worker_tags_str}"
            
            await self.notifier.notify_admins(msg)
            
            # Optionally notify workers too (consistent with auto-session)
            worker_msg = f"🔔 <b>Ручний запуск сесії!</b>\n\n" \
                         f"⏰ Дедлайн: {deadline.strftime('%H:%M')}\n" \
                         f"👷 На зміні: {worker_tags_str}\n\n" \
                         f"Потрібно заправити генератор!"
            
            from bot.keyboards.session_kb import get_start_session_kb
            kb = get_start_session_kb(session.id)
            
            for worker_id in all_worker_ids:
                await self.notifier.notify_user(worker_id, worker_msg, reply_markup=kb)
            
        return session
