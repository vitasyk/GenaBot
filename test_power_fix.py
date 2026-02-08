
import asyncio
import logging
from datetime import datetime, time, timedelta
from sqlalchemy import select
from bot.database.main import session_maker
from bot.database.repositories.schedule import ScheduleRepository
from bot.database.repositories.session import SessionRepository
from bot.services.session_service import SessionService
from bot.database.models import ScheduleEntry, SessionStatus

async def test_fix():
    logging.basicConfig(level=logging.INFO)
    async with session_maker() as db_session:
        s_repo = ScheduleRepository(db_session)
        sess_repo = SessionRepository(db_session)
        service = SessionService(db_session)
        
        today = datetime.now().date()
        
        # 1. Clean up existing test data for today
        from bot.database.models import RefuelSession
        stmt = select(RefuelSession).where(RefuelSession.start_time >= datetime.combine(today, time.min))
        res = await db_session.execute(stmt)
        for s in res.scalars():
             await db_session.delete(s)
        
        # 2. Add a mock schedule block that JUST ended (e.g. 1 hour ago)
        now = datetime.now()
        outage_start_hour = (now - timedelta(hours=2)).hour
        outage_end_hour = (now - timedelta(hours=1)).hour
        
        # Avoid day wrap for simplicity in test
        if outage_start_hour > outage_end_hour: 
            outage_start_hour, outage_end_hour = 10, 12
            # Adjust 'now' in logic if needed, but let's just use fixed hours if current hour is too low
            
        print(f"Creating mock outage: {outage_start_hour:02d}:00 - {outage_end_hour:02d}:00")
        entry = ScheduleEntry(date=today, start_hour=outage_start_hour, end_hour=outage_end_hour, queue="1.1")
        db_session.add(entry)
        await db_session.commit()
        
        # 3. Define the deadline (power return)
        deadline = datetime.combine(today, time(outage_end_hour, 0))
        print(f"Expected Deadline (Power Return): {deadline}")
        print(f"Current Time: {now}")
        
        # 4. Run detection
        print("\n--- Running check_power_outage ---")
        session = await service.check_power_outage()
        
        if session:
            print(f"✅ Success! Session created: ID={session.id}, Deadline={session.deadline}")
        else:
            print("❌ Failure: No session created.")
            
        # 5. Run again to verify no duplicates
        print("\n--- Running check_power_outage again (Duplicate check) ---")
        session2 = await service.check_power_outage()
        if session2:
            print(f"❌ Failure: Duplicate session created! ID={session2.id}")
        else:
            print("✅ Success: No duplicate session created.")

if __name__ == "__main__":
    asyncio.run(test_fix())
