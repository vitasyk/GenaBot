
import asyncio
from bot.database.main import session_maker
from bot.database.repositories.schedule import ScheduleRepository
from bot.database.repositories.session import SessionRepository
from datetime import datetime

async def check():
    async with session_maker() as session:
        s_repo = ScheduleRepository(session)
        sess_repo = SessionRepository(session)
        
        today = datetime.now().date()
        entries = await s_repo.get_entries_for_date(today, "1.1")
        print(f"--- Schedule for {today} ---")
        for e in entries:
            print(f"ID: {e.id}, Date: {e.date}, Queue: {e.queue}, {e.start_hour}-{e.end_hour}")
            
        sessions = await sess_repo.get_history(limit=5)
        print(f"\n--- Recent Sessions ---")
        for s in sessions:
            print(f"ID: {s.id}, Start: {s.start_time}, Deadline: {s.deadline}, Status: {s.status}")

if __name__ == "__main__":
    asyncio.run(check())
