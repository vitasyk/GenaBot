"""Schedule repository for managing manual schedule entries"""
from datetime import date, datetime
from typing import List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import ScheduleEntry
from bot.database.repositories.base import BaseRepository


class ScheduleRepository(BaseRepository[ScheduleEntry]):
    def __init__(self, session: AsyncSession):
        super().__init__(session, ScheduleEntry)
    
    async def create_entry(
        self, 
        entry_date: date, 
        queue: str, 
        start_hour: int, 
        end_hour: int,
        user_id: Optional[int] = None
    ) -> ScheduleEntry:
        """Create a new schedule entry"""
        import logging
        logging.warning(f"DB: Creating schedule entry: {entry_date} {start_hour}-{end_hour} (queue {queue}) by user {user_id}")
        
        entry = ScheduleEntry(
            date=entry_date,
            queue=queue,
            start_hour=start_hour,
            end_hour=end_hour,
            created_by=user_id
        )
        self.session.add(entry)
        await self.session.flush()
        return entry
    
    async def get_entries_for_date(self, entry_date: date, queue: str = "1.1") -> List[ScheduleEntry]:
        """Get all schedule entries for a specific date and queue"""
        stmt = select(ScheduleEntry).where(
            ScheduleEntry.date == entry_date,
            ScheduleEntry.queue == queue
        ).order_by(ScheduleEntry.start_hour)
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def delete_entry(self, entry_id: int) -> bool:
        """Delete a specific entry by ID"""
        stmt = delete(ScheduleEntry).where(ScheduleEntry.id == entry_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0
    
    async def clear_all_for_date(self, entry_date: date, queue: str = "1.1") -> int:
        """Clear all entries for a specific date and queue. Returns number of deleted entries."""
        import logging
        logging.warning(f"DB: Clearing schedule for {entry_date} (queue {queue})")
        
        stmt = delete(ScheduleEntry).where(
            ScheduleEntry.date == entry_date,
            ScheduleEntry.queue == queue
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount
    
    async def get_all_for_date_range(
        self, 
        start_date: date, 
        end_date: date, 
        queue: str = "1.1"
    ) -> List[ScheduleEntry]:
        """Get all entries within a date range"""
        stmt = select(ScheduleEntry).where(
            ScheduleEntry.date >= start_date,
            ScheduleEntry.date <= end_date,
            ScheduleEntry.queue == queue
        ).order_by(ScheduleEntry.date, ScheduleEntry.start_hour)
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
