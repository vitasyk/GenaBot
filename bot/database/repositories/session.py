from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import RefuelSession, SessionStatus
from bot.utils.clock import now_local

# A session can still be started/completed in these statuses (expired = deadline passed, not done yet)
OPEN_STATUSES = [SessionStatus.pending, SessionStatus.in_progress, SessionStatus.expired]

class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        
    async def create_session(self, 
                             start_time: datetime, 
                             deadline: datetime, 
                             worker1_id: Optional[int] = None, 
                             worker2_id: Optional[int] = None,
                             worker3_id: Optional[int] = None,
                             additional_workers: Optional[List[int]] = None) -> RefuelSession:
        new_session = RefuelSession(
            start_time=start_time,
            deadline=deadline,
            worker1_id=worker1_id,
            worker2_id=worker2_id,
            worker3_id=worker3_id,
            additional_workers=additional_workers or [],
            status=SessionStatus.pending
        )
        self.session.add(new_session)
        await self.session.commit()
        await self.session.refresh(new_session)
        return new_session
        
    async def get_overdue_sessions(self, now: datetime) -> List[RefuelSession]:
        """Pending/in-progress sessions whose deadline has passed (all of them, not only the latest)."""
        stmt = select(RefuelSession).where(
            RefuelSession.status.in_([SessionStatus.pending, SessionStatus.in_progress]),
            RefuelSession.deadline <= now,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_session_by_id(self, session_id: int) -> Optional[RefuelSession]:
        return await self.session.get(RefuelSession, session_id)
        
    async def exists_by_start_time(self, start_time: datetime) -> bool:
        """Check if a session with this exact start_time already exists"""
        stmt = select(RefuelSession).where(RefuelSession.start_time == start_time)
        result = await self.session.execute(stmt)
        return result.scalars().first() is not None
        
    async def update_status(self, session_id: int, status: SessionStatus,
                            only_from: Optional[List[SessionStatus]] = None) -> Optional[RefuelSession]:
        """Sets status. With only_from, changes the session only if its current status is in that
        list and returns None otherwise (another worker already started/finished it)."""
        stmt = update(RefuelSession).where(RefuelSession.id == session_id).values(status=status)
        if only_from is not None:
            stmt = stmt.where(RefuelSession.status.in_(only_from))
        result = await self.session.execute(stmt)
        await self.session.commit()
        if result.rowcount == 0:
            return None
        return await self.get_session_by_id(session_id)

    async def complete_session(self,
                               session_id: int,
                               completed_by: int,
                               gen_name: str,
                               liters: float,
                               cans: float,
                               notes: str = None) -> Optional[RefuelSession]:
        """Completes an open session. Returns None if it was already completed or cancelled,
        so a second worker can't record (and deduct) the same refuel twice."""
        stmt = update(RefuelSession).where(
            RefuelSession.id == session_id,
            RefuelSession.status.in_(OPEN_STATUSES),
        ).values(
            status=SessionStatus.completed,
            end_time=now_local(),
            completed_by=completed_by,
            gen_name=gen_name,
            liters=liters,
            cans=cans,
            notes=notes
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        if result.rowcount == 0:
            return None
        return await self.get_session_by_id(session_id)
        
    async def get_history(self, limit: int = 10) -> List[RefuelSession]:
        stmt = select(RefuelSession).order_by(RefuelSession.start_time.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_cancelled(self) -> int:
        """Delete all cancelled sessions. Returns count of deleted rows."""
        stmt = delete(RefuelSession).where(RefuelSession.status == SessionStatus.cancelled)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount

    async def delete_all(self) -> int:
        """Delete ALL sessions. Returns count of deleted rows."""
        stmt = delete(RefuelSession)
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.rowcount
