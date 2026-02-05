import logging
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.repositories.session import SessionRepository
from bot.database.repositories.shift import ShiftRepository
from bot.database.repositories.user import UserRepository
from bot.services.google_sheets import GoogleSheetsService
from bot.services.schedule_parser import ScheduleParser
from bot.database.models import RefuelSession
from bot.services.notifier import NotifierService

class SessionService:
    def __init__(self, session: AsyncSession, bot=None):
        self.db_session = session
        self.repo = SessionRepository(session)
        self.shift_repo = ShiftRepository(session)
        self.user_repo = UserRepository(session)
        self.sheets_service = GoogleSheetsService()
        self.parser = ScheduleParser()
        self.notifier = NotifierService(bot) if bot else None

    async def check_power_outage(self) -> Optional[RefuelSession]:
        """
        Check outage timeline and create session for upcoming or current blocks.
        Handles continuity across midnight.
        """
        # 1. Fetch Timeline (Merged today + tomorrow)
        timeline = await self.parser.get_outage_timeline(queue="1.1")
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
                    msg = "⚡ <b>Електроенергія має з'явитися за графіком!</b>\n" \
                          "Поверніть генератор у режим чергування або зупиніть його."
                    
                    if active_session.worker1_id: await self.notifier.notify_user(active_session.worker1_id, msg)
                    if active_session.worker2_id: await self.notifier.notify_user(active_session.worker2_id, msg)
                    await self.notifier.notify_admins(f"📢 <b>Час відновлення!</b> Сесія {active_session.id} досягла дедлайну ({active_session.deadline.strftime('%H:%M')}).")
                    
                    # Update status to avoid re-notifying
                    await self.repo.update_status(active_session.id, SessionStatus.completed)
            
            # 2. Check if current block covers this session
            if active_session.start_time <= target_dt < active_session.deadline:
                return None
            
        # 4. T-30m Check for NEW sessions
        # Only create and notify 30 mins before start
        trigger_time = block_start - timedelta(minutes=30)
        if now < trigger_time:
            # Too early to assign/notify
            return None

        # 5. Get Workers for the START of the block
        w1_name, w2_name = "Unknown", "Unknown"
        worker1_id, worker2_id = None, None
        
        try:
            worker_tuples = self.sheets_service.get_workers_for_outage(
                outage_start_hour=block_start.hour,
                target_date=block_start.date()
            )
            
            if len(worker_tuples) > 0:
                w1_name, _ = worker_tuples[0]
                user1 = await self.user_repo.get_by_sheet_name(w1_name)
                if not user1: user1 = await self.user_repo.get_by_name(w1_name)
                if user1: worker1_id = user1.id
                
            if len(worker_tuples) > 1:
                w2_name, _ = worker_tuples[1]
                user2 = await self.user_repo.get_by_sheet_name(w2_name)
                if not user2: user2 = await self.user_repo.get_by_name(w2_name)
                if user2: worker2_id = user2.id
                
            logging.info(f"Block found: {block_start} to {deadline}. Assigned: {w1_name}, {w2_name}")
        except Exception as e:
            logging.error(f"Failed to get workers: {e}")

        # 5. Create Session
        # Logic: Session starts NOW if it's already an outage, 
        # or at block_start if it's upcoming. 
        # Actually safer to start "approx now" to trigger notifications.
        session_start = max(now, block_start - timedelta(minutes=30))
        
        session = await self.repo.create_session(
            start_time=session_start,
            deadline=deadline,
            worker1_id=worker1_id,
            worker2_id=worker2_id
        )
        
        # 6. Notify
        if self.notifier:
            worker_list_str = f"{w1_name}, {w2_name}"
            # Formatting dates for humans
            def fmt_dt(dt):
                if dt.date() == now.date(): return dt.strftime('%H:%M')
                return dt.strftime('%d.%m %H:%M')

            msg = f"🔔 <b>Відключення світла!</b>\n\n" \
                  f"⏰ Період: {fmt_dt(block_start)} - {fmt_dt(deadline)}\n" \
                  f"👷 На зміні: {worker_list_str}\n\n" \
                  f"Потрібно заправити генератор!"
            
            from bot.keyboards.session_kb import get_start_session_kb
            kb = get_start_session_kb(session.id)
            
            if worker1_id: await self.notifier.notify_user(worker1_id, msg, reply_markup=kb)
            if worker2_id: await self.notifier.notify_user(worker2_id, msg, reply_markup=kb)

            admin_msg = f"🚀 <b>Створено сесію заправки</b> (ID: {session.id})\n" \
                        f"⏰ Період: {fmt_dt(block_start)} - {fmt_dt(deadline)}\n" \
                        f"👷 Воркери: {worker_list_str}\n"
            
            if not worker1_id and not worker2_id:
                admin_msg += "❌ <b>Помилка:</b> Воркери не знайдени в базі!"
            
            await self.notifier.notify_admins(admin_msg)
            
        return session

    async def create_manual_session(self, hours: int = 2) -> RefuelSession:
        """Manually create a session starting now for X hours"""
        now = datetime.now()
        deadline = now + timedelta(hours=hours)
        
        # We don't auto-lookup workers for manual sessions for now, 
        # but we could. Let's just create it.
        session = await self.repo.create_session(
            start_time=now,
            deadline=deadline,
            worker1_id=None,
            worker2_id=None
        )
        
        if self.notifier:
            await self.notifier.notify_admins(
                f"📝 <b>Ручне створення сесії</b>\n"
                f"ID: {session.id}\n"
                f"Дедлайн: {deadline.strftime('%H:%M')}"
            )
            
        return session
