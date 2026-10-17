import asyncio
import html
import logging
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import config
from bot.database.models import RefuelSession, SessionStatus
from bot.database.repositories.session import SessionRepository
from bot.database.repositories.user import UserRepository
from bot.keyboards.session_kb import get_start_session_kb
from bot.services.google_sheets import GoogleSheetsService
from bot.services.notifier import NotifierService
from bot.services.schedule_parser import ScheduleParser
from bot.utils.clock import now_kyiv

OUTAGE_LOOKAHEAD = timedelta(minutes=60)
NOTIFY_BEFORE_OUTAGE = timedelta(minutes=30)
ONE_HOUR = timedelta(hours=1)


class SessionService:
    def __init__(self, session: AsyncSession, parser: ScheduleParser, bot: Bot | None = None):
        self.repo = SessionRepository(session)
        self.user_repo = UserRepository(session)
        self.sheets_service = GoogleSheetsService()
        self.parser = parser
        self.notifier = NotifierService(bot) if bot else None

    async def _find_user_id(self, sheet_name: str) -> int | None:
        user = await self.user_repo.get_by_sheet_name(sheet_name) or await self.user_repo.get_by_name(sheet_name)
        return user.id if user else None

    async def check_power_outage(self) -> Optional[RefuelSession]:
        """
        Check outage timeline and create session for upcoming or current blocks.
        Handles continuity across midnight.
        """
        timeline = await self.parser.get_outage_timeline(queue=config.QUEUE_NUMBER)
        if not timeline:
            return None

        now = now_kyiv()
        lookahead = now + OUTAGE_LOOKAHEAD

        # Outage happening now OR starting within the lookahead window
        target_dt = next((dt for dt in timeline if dt <= lookahead and dt + ONE_HOUR > now), None)
        if not target_dt:
            return None

        # The continuous block this target belongs to
        block_start = target_dt
        while block_start - ONE_HOUR in timeline:
            block_start -= ONE_HOUR

        block_end = target_dt
        while block_end + ONE_HOUR in timeline:
            block_end += ONE_HOUR

        deadline = block_end + ONE_HOUR

        active_session = await self.repo.get_active_session()

        if active_session:
            # Power restoration: the active session reached its deadline
            if now >= active_session.deadline:
                if self.notifier:
                    msg = "⚡ <b>Електроенергія має з'явитися за графіком!</b>\n" \
                          "Поверніть генератор у режим чергування або зупиніть його."
                    for worker_id in (active_session.worker1_id, active_session.worker2_id):
                        if worker_id:
                            await self.notifier.notify_user(worker_id, msg)
                    await self.notifier.notify_admins(
                        f"📢 <b>Час відновлення!</b> Сесія {active_session.id} досягла дедлайну "
                        f"({active_session.deadline.strftime('%H:%M')})."
                    )
                # Close it so the next check does not notify again
                await self.repo.update_status(active_session.id, SessionStatus.completed)

            # Current block is already covered by this session
            if active_session.start_time <= target_dt < active_session.deadline:
                return None

        # New sessions are created and announced only shortly before the block starts
        if now < block_start - NOTIFY_BEFORE_OUTAGE:
            return None

        worker_names: list[str] = []
        worker_ids: list[int | None] = []
        try:
            worker_tuples = await asyncio.to_thread(
                self.sheets_service.get_workers_for_outage,
                outage_start_hour=block_start.hour,
                target_date=block_start.date(),
            )
            for name, _phone in worker_tuples[:2]:
                worker_names.append(name)
                worker_ids.append(await self._find_user_id(name))
            logging.info(f"Block found: {block_start} to {deadline}. Assigned: {worker_names}")
        except Exception:
            logging.exception("Failed to get workers from Google Sheets")

        worker_ids += [None] * (2 - len(worker_ids))
        worker1_id, worker2_id = worker_ids

        # Start "approx now" so notifications go out immediately
        session = await self.repo.create_session(
            start_time=max(now, block_start - NOTIFY_BEFORE_OUTAGE),
            deadline=deadline,
            worker1_id=worker1_id,
            worker2_id=worker2_id,
        )

        if self.notifier:
            def fmt_dt(dt: datetime) -> str:
                return dt.strftime('%H:%M') if dt.date() == now.date() else dt.strftime('%d.%m %H:%M')

            worker_list_str = html.escape(", ".join(worker_names)) if worker_names else "невідомо"
            period = f"{fmt_dt(block_start)} - {fmt_dt(deadline)}"

            msg = f"🔔 <b>Відключення світла!</b>\n\n" \
                  f"⏰ Період: {period}\n" \
                  f"👷 На зміні: {worker_list_str}\n\n" \
                  f"Потрібно заправити генератор!"
            kb = get_start_session_kb(session.id)
            for worker_id in (worker1_id, worker2_id):
                if worker_id:
                    await self.notifier.notify_user(worker_id, msg, reply_markup=kb)

            admin_msg = f"🚀 <b>Створено сесію заправки</b> (ID: {session.id})\n" \
                        f"⏰ Період: {period}\n" \
                        f"👷 Воркери: {worker_list_str}\n"
            if not worker1_id and not worker2_id:
                admin_msg += "❌ <b>Помилка:</b> Воркери не знайдені в базі!"
            await self.notifier.notify_admins(admin_msg)

        return session

    async def create_manual_session(self, hours: int = 2) -> RefuelSession:
        """Manually create a session starting now for X hours"""
        now = now_kyiv()
        deadline = now + timedelta(hours=hours)

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
