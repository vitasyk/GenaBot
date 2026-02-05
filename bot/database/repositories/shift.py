from sqlalchemy import select
from bot.database.repositories.base import BaseRepository
from bot.database.models import WorkerShift
from datetime import date

class ShiftRepository(BaseRepository[WorkerShift]):
    def __init__(self, session):
        super().__init__(session, WorkerShift)
    
    async def save_shift(self, shift_date: date, shift_num: int, w1_id: int, w2_id: int, 
                        start: str, end: str) -> WorkerShift:
        """Save or update a shift"""
        # Check if shift already exists
        stmt = select(WorkerShift).where(
            WorkerShift.date == shift_date,
            WorkerShift.shift_number == shift_num
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing
            existing.worker1_id = w1_id
            existing.worker2_id = w2_id
            existing.start_time = start
            existing.end_time = end
            return existing
        else:
            # Create new
            shift = WorkerShift(
                date=shift_date,
                shift_number=shift_num,
                worker1_id=w1_id,
                worker2_id=w2_id,
                start_time=start,
                end_time=end
            )
            self.session.add(shift)
            await self.session.flush()
            return shift
    
    async def get_shift_for_date(self, target_date: date) -> WorkerShift | None:
        """Get shift for a specific date"""
        stmt = select(WorkerShift).where(WorkerShift.date == target_date)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
