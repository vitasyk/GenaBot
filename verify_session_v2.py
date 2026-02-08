import asyncio
from datetime import datetime, timedelta, time
from bot.services.session_service import SessionService
from bot.database.main import session_maker
from bot.database.models import User, RefuelSession, SessionStatus
from bot.database.repositories.user import UserRepository
from bot.database.repositories.session import SessionRepository
from sqlalchemy import select, delete

async def verify_session_logic():
    print("--- Verifying Session Creation Logic ---")
    async with session_maker() as session:
        user_repo = UserRepository(session)
        service = SessionService(session)
        
        # 1. Test Name Matching
        print("\n1. Testing Name Matching...")
        test_cases = [
            ("а64 Герасімчук Дмитро", True),
            ("а81 Чубіна Діана", True),
            ("а89 Дмитро Акрибай", False), # Not in DB based on check_users.py
        ]
        
        for name, expected in test_cases:
            user = await service._find_user_by_name_robust(name)
            found = user is not None
            status = "PASS" if found == expected else "FAIL"
            print(f"  - Name: '{name}' | Found: {found} | Expected: {expected} | {status}")

        # 2. Test Session Creation Timing
        print("\n2. Testing Session Creation Timing...")
        # Simulate a block from 5:00 to 11:00 today
        now = datetime.now()
        block_start = datetime.combine(now.date(), time(5, 0))
        deadline = datetime.combine(now.date(), time(11, 0))
        
        # Create a session manually via the underlying logic
        # Note: We can't easily mock Sheets API here without more setup, 
        # but we can check if it tries to use the correct hour.
        
        # Modify _create_outage_session briefly to return the hour used for lookup
        # Actually, let's just inspect the created session's deadline
        try:
            # Cleanup old sessions for this deadline
            await session.execute(delete(RefuelSession).where(RefuelSession.start_time == deadline))
            await session.commit()
            
            s_obj = await service._create_outage_session(block_start, deadline)
            
            print(f"  - Created Session ID: {s_obj.id}")
            print(f"  - Start Time (Power Return Time): {s_obj.start_time}")
            print(f"  - Deadline (Should be +2h from now): {s_obj.deadline}")
            
            # Duration check
            duration = s_obj.deadline - now
            if timedelta(minutes=115) < duration < timedelta(minutes=125):
                print("  - [PASS] Session duration is approx 2 hours from now.")
            else:
                print(f"  - [FAIL] Session duration is unexpected: {duration}")
                
            # Cleanup
            await session.delete(s_obj)
            await session.commit()
            
        except Exception as e:
            print(f"  - [ERROR] Session creation failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify_session_logic())
