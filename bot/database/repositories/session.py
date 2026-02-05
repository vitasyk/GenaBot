from datetime import datetime
from typing import Optional, List
from sqlalchemy import select, update, delete, and_
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import RefuelSession, SessionStatus

class SessionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
        
    async def create_session(self, 
                             start_time: datetime, 
                             deadline: datetime, 
                             worker1_id: Optional[int] = None, 
                             worker2_id: Optional[int] = None) -> RefuelSession:
        new_session = RefuelSession(
            start_time=start_time,
            deadline=deadline,
            worker1_id=worker1_id,
            worker2_id=worker2_id,
            status=SessionStatus.pending
        )
        self.session.add(new_session)
        await self.session.commit()
        await self.session.refresh(new_session)
        return new_session
        
    async def get_active_session(self) -> Optional[RefuelSession]:
        """Get current session (pending or in_progress)"""
        stmt = select(RefuelSession).where(
            RefuelSession.status.in_([SessionStatus.pending, SessionStatus.in_progress])
        ).order_by(RefuelSession.start_time.desc()).limit(1)
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
        
    async def get_session_by_id(self, session_id: int) -> Optional[RefuelSession]:
        return await self.session.get(RefuelSession, session_id)
        
    async def update_status(self, session_id: int, status: SessionStatus) -> Optional[RefuelSession]:
        stmt = update(RefuelSession).where(RefuelSession.id == session_id).values(status=status)
        await self.session.execute(stmt)
        await self.session.commit()
        return await self.get_session_by_id(session_id)
        
    async def complete_session(self, 
                               session_id: int, 
                               completed_by: int,
                               gen_name: str, 
                               liters: float, 
                               cans: float, 
                               notes: str = None) -> Optional[RefuelSession]:
        stmt = update(RefuelSession).where(RefuelSession.id == session_id).values(
            status=SessionStatus.completed,
            end_time=datetime.utcnow(),
            completed_by=completed_by,
            gen_name=gen_name,
            liters=liters,
            cans=cans,
            notes=notes
        )
        await self.session.execute(stmt)
        await self.session.commit()
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
