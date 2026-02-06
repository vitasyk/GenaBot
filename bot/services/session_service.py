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
        today = datetime.now().date()
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
        Check outage timeline and create session for upcoming or current blocks.
        Handles continuity across midnight.
        """
        # 1. Fetch Timeline from DATABASE (not parser)
        timeline = await self.get_outage_timeline_from_db(queue="1.1")
        if not timeline:
            return None
            
        now = datetime.now()
        # Look ahead window: 60 minutes
        lookahead = now + timedelta(minutes=60)
        
        # Determine if we are near or in an outage
        target_dt = None
        for dt in timeline:
            # If outage is happening now OR starts within 60 mins
            if dt <= lookahead and dt + timedelta(hours=1) > now:
                target_dt = dt
                break
        
        if not target_dt:
            return None
            
        # 2. Identify the continuous block this target belongs to
        # Find start of block
        block_start = target_dt
        while block_start - timedelta(hours=1) in timeline:
            block_start -= timedelta(hours=1)
            
        # Find end of block
        block_end = target_dt
        while block_end + timedelta(hours=1) in timeline:
            block_end += timedelta(hours=1)
            
        deadline = block_end + timedelta(hours=1)
        
        # 3. Check if session for this block already exists
        active_session = await self.repo.get_active_session()
        
        # Power Restoration Monitoring:
        if active_session:
            # If we have an active session, check if power is back
            # 1. Check if deadline passed
            if now >= active_session.deadline:
                # Notify and mark as expired/awaiting completion if still in_progress
                if active_session.status in [SessionStatus.pending.value, SessionStatus.in_progress.value]:
                    msg = f"🔔 <b>Час спливає!</b> Сесія {active_session.id} досягає дедлайну о {active_session.deadline.strftime('%H:%M')}. Будь ласка, завершіть заправку."
                    
                    if active_session.worker1_id: await self.notifier.notify_user(active_session.worker1_id, msg)
                    if active_session.worker2_id: await self.notifier.notify_user(active_session.worker2_id, msg)
                    if active_session.worker3_id: await self.notifier.notify_user(active_session.worker3_id, msg)
                    await self.notifier.notify_admins(f"📢 <b>Час відновлення!</b> Сесія {active_session.id} досягла дедлайну ({active_session.deadline.strftime('%H:%M')}).")
                    
                    # Update status to avoid re-notifying
                    await self.repo.update_status(active_session.id, SessionStatus.completed)
            
            # 2. Check if current block covers this session
            if active_session.start_time <= target_dt < active_session.deadline:
                return None
            
        # 4. Trigger Check: Notification should happen when light appeared (at deadline)
        # We trigger when 'now' is close to or past the deadline, but within a reasonable window
        # to ensure we don't miss it between ticks.
        if now < deadline:
            # Power is still out (or outage hasn't started), wait for restoration.
            return None
            
        # If we are more than 2 hours past the deadline, it might be too late to auto-create
        # (unless we have a very long interval between checks, but default is 15-30m)
        if now > deadline + timedelta(hours=2):
            return None

        try:
            worker_tuples = self.sheets_service.get_workers_for_outage(
                outage_start_hour=block_start.hour,
                target_date=block_start.date()
            )
            logging.info(f"Block found: {block_start} to {deadline}. Assigned names from Sheets: {[w[0] for w in worker_tuples]}")
        except Exception as e:
            logging.error(f"Failed to get workers: {e}")
            worker_tuples = []

        w1_name, w2_name, w3_name = "Unknown", "Unknown", "Unknown"
        worker1_id, worker2_id, worker3_id = None, None, None
        
        # Find worker IDs using robust lookup
        if len(worker_tuples) > 0:
            w1_name = worker_tuples[0][0]
            u1 = await self._find_user_by_name_robust(w1_name)
            if u1: worker1_id = u1.id
            
        if len(worker_tuples) > 1:
            w2_name = worker_tuples[1][0]
            u2 = await self._find_user_by_name_robust(u2_name)
            if u2: worker2_id = u2.id
            
        if len(worker_tuples) > 2:
            w3_name = worker_tuples[2][0]
            u3 = await self._find_user_by_name_robust(w3_name)
            if u3: worker3_id = u3.id

        # 5. Create Session
        # Session start_time is set to deadline (when power returns)
        # This ensures workers are notified during power-ON period
        # when they can actually refuel generators
        session = await self.repo.create_session(
            start_time=deadline,  # Workers notified when power returns
            deadline=deadline,
            worker1_id=worker1_id,
            worker2_id=worker2_id,
            worker3_id=worker3_id
        )
        
        # 6. Notify
        if self.notifier:
            # Create clickable tags
            t1 = self._get_worker_tag(worker1_id, w1_name)
            t2 = self._get_worker_tag(worker2_id, w2_name)
            t3 = self._get_worker_tag(worker3_id, w3_name)
            
            worker_tags_str = ", ".join([t for t in [t1, t2, t3] if "Unknown" not in t])
            if not worker_tags_str: worker_tags_str = "Unknown"

            # Formatting dates for humans
            def fmt_dt(dt):
                if dt.date() == now.date(): return dt.strftime('%H:%M')
                return dt.strftime('%d.%m %H:%M')

            msg = f"⚡ <b>Світло з'явилося!</b>\n\n" \
                  f"⏰ Період відключення: {fmt_dt(block_start)} - {fmt_dt(deadline)}\n" \
                  f"👷 На зміні були: {worker_tags_str}\n\n" \
                  f"Будь ласка, заправте генератор(и) та завершіть сесію."
            
            from bot.keyboards.session_kb import get_start_session_kb
            kb = get_start_session_kb(session.id)
            
            if worker1_id: await self.notifier.notify_user(worker1_id, msg, reply_markup=kb)
            if worker2_id: await self.notifier.notify_user(worker2_id, msg, reply_markup=kb)
            if worker3_id: await self.notifier.notify_user(worker3_id, msg, reply_markup=kb)

            admin_msg = f"🚀 <b>Створено сесію заправки</b> (ID: {session.id})\n" \
                        f"⏰ Період: {fmt_dt(block_start)} - {fmt_dt(deadline)}\n" \
                        f"👷 Воркери: {worker_tags_str}\n"
            
            if not worker1_id and not worker2_id and not worker3_id:
                admin_msg += "❌ <b>Помилка:</b> Воркерів не знайдено в базі!"
            
            await self.notifier.notify_admins(admin_msg)
            
        return session

    def _get_worker_tag(self, worker_id: int | None, name: str) -> str:
        """Helper to create HTML mention if ID is available, else just bold name"""
        if worker_id:
            return f"<a href='tg://user?id={worker_id}'>{name}</a>"
        return f"<b>{name}</b>"

    async def _get_workers_for_start_time(self, start_dt: datetime) -> tuple[int | None, int | None, int | None, str, str, str]:
        """Helper to find workers for a specific start time based on Sheets schedule"""
        w1_name, w2_name, w3_name = "Unknown", "Unknown", "Unknown"
        worker1_id, worker2_id, worker3_id = None, None, None
        
        try:
            worker_tuples = self.sheets_service.get_workers_for_outage(
                outage_start_hour=start_dt.hour,
                target_date=start_dt.date()
            )
            
            logging.info(f"Sheets returned {len(worker_tuples)} workers for {start_dt}")
            
            if len(worker_tuples) > 0:
                w1_name = worker_tuples[0][0]
                user1 = await self._find_user_by_name_robust(w1_name)
                if user1: worker1_id = user1.id
                
            if len(worker_tuples) > 1:
                w2_name = worker_tuples[1][0]
                user2 = await self._find_user_by_name_robust(w2_name)
                if user2: worker2_id = user2.id

            if len(worker_tuples) > 2:
                w3_name = worker_tuples[2][0]
                user3 = await self._find_user_by_name_robust(w3_name)
                if user3: worker3_id = user3.id
                
            logging.info(f"Workers lookup results: {w1_name}({worker1_id}), {w2_name}({worker2_id}), {w3_name}({worker3_id})")
        except Exception as e:
            logging.error(f"Failed to get workers: {e}", exc_info=True)
            
        return worker1_id, worker2_id, worker3_id, w1_name, w2_name, w3_name

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
        
        # 3. Clean names and try again (remove common prefixes like 'а64 ')
        import re
        clean_name = re.sub(r'^[аa]\d+\s+', '', name).strip()
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
        now = datetime.now()
        deadline = now + timedelta(hours=hours)
        
        # Auto-lookup workers for manual session using current time
        worker1_id, worker2_id, worker3_id, w1_name, w2_name, w3_name = await self._get_workers_for_start_time(now)
        
        session = await self.repo.create_session(
            start_time=now,
            deadline=deadline,
            worker1_id=worker1_id,
            worker2_id=worker2_id,
            worker3_id=worker3_id
        )
        
        if self.notifier:
            t1 = self._get_worker_tag(worker1_id, w1_name)
            t2 = self._get_worker_tag(worker2_id, w2_name)
            t3 = self._get_worker_tag(worker3_id, w3_name)
            
            worker_tags_str = ", ".join([t for t in [t1, t2, t3] if "Unknown" not in t])
            if not worker_tags_str: worker_tags_str = "Unknown"

            msg = f"📝 <b>Ручне створення сесії</b>\n" \
                  f"ID: {session.id}\n" \
                  f"Дедлайн: {deadline.strftime('%H:%M')}\n" \
                  f"👷 Воркери: {worker_tags_str}"
            
            await self.notifier.notify_admins(msg)
            
            # Optionally notify workers too (consistent with auto-session)
            worker_msg = f"🔔 <b>Ручний запуск сесії!</b>\n\n" \
                         f"⏰ Дедлайн: {deadline.strftime('%H:%M')}\n" \
                         f"👷 На зміні: {worker_tags_str}\n\n" \
                         f"Потрібно заправити генератор!"
            
            from bot.keyboards.session_kb import get_start_session_kb
            kb = get_start_session_kb(session.id)
            
            if worker1_id: await self.notifier.notify_user(worker1_id, worker_msg, reply_markup=kb)
            if worker2_id: await self.notifier.notify_user(worker2_id, worker_msg, reply_markup=kb)
            if worker3_id: await self.notifier.notify_user(worker3_id, worker_msg, reply_markup=kb)
            
        return session
