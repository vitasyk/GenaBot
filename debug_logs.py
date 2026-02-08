import asyncio
from datetime import datetime, timedelta
from bot.database.repositories.logs import LogRepository
from bot.database.main import session_maker as async_session
from bot.database.models import LogEvent
from sqlalchemy import select

async def debug_logs():
    async with async_session() as session:
        log_repo = LogRepository(session)
        
        print("--- All Fuel Logs (Last 20) ---")
        stmt = select(LogEvent).order_by(LogEvent.timestamp.desc()).limit(20)
        res = await session.execute(stmt)
        for e in res.scalars():
            print(f"{e.timestamp} | {e.action} | {e.details}")
            
        print("\n--- Consumption Check Logic ---")
        days = 7
        since = datetime.utcnow() - timedelta(days=days)
        print(f"Checking since: {since}")
        
        refuel_events = await log_repo.get_actions_since("TAKE_FUEL", since)
        print(f"Found {len(refuel_events)} TAKE_FUEL events")
        
        total = 0
        for e in refuel_events:
            try:
                part = e.details.split("Taken: ")[1].split("L")[0]
                val = float(part)
                total += val
                print(f"  + {val}L from '{e.details}'")
            except Exception as ex:
                print(f"  ! Failed to parse '{e.details}': {ex}")
        
        print(f"Total consumed: {total}")

if __name__ == "__main__":
    asyncio.run(debug_logs())
