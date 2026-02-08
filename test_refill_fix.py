
import asyncio
from datetime import datetime, timedelta
from bot.database.main import session_maker
from bot.database.repositories.logs import LogRepository
from bot.database.repositories.inventory import InventoryRepository
from bot.database.repositories.user import UserRepository
from bot.services.inventory import InventoryService

async def test_refill_correction():
    async with session_maker() as session:
        log_repo = LogRepository(session)
        inv_repo = InventoryRepository(session)
        user_repo = UserRepository(session)
        
        # We need a bot instance for InventoryService, though it might not be used in this specific method
        # Let's mock it if possible or just pass None if it's only for alerts
        service = InventoryService(inv_repo, log_repo, user_repo, None, None)
        
        # 0. Clean up logs to ensure isolation
        await log_repo.clear_all()
        await session.commit()
        
        # 1. Fetch a valid user ID to avoid FK violation
        from sqlalchemy import select
        from bot.database.models import User
        user_res = await session.execute(select(User).limit(1))
        user = user_res.scalar_one_or_none()
        if not user:
            print("❌ No users found in DB, creating a dummy one...")
            user = User(id=1, name="Test User")
            session.add(user)
            await session.commit()
        
        user_id = user.id
        print(f"Using User ID: {user_id}")

        # 2. Ensure we have an ADD_FUEL event
        print("--- Adding a test refill ---")
        await service.add_cans(user_id, 5) 
        await session.commit()
        
        stats = await service.get_detailed_stats()
        original_date = stats["last_refill_date"]
        print(f"Original refill date: {original_date}")
        
        # 2. Correct to yesterday
        yesterday = datetime.now() - timedelta(days=1)
        print(f"Correcting to: {yesterday.date()}")
        
        success = await service.update_last_refill_date(user_id, yesterday)
        await session.commit()
        
        if success:
            stats_new = await service.get_detailed_stats()
            new_date = stats_new["last_refill_date"]
            print(f"New refill date: {new_date}")
            
            if new_date.date() == yesterday.date():
                print("✅ Success! Date corrected correctly.")
            else:
                print("❌ Failure: Date mismatch.")
        else:
            print("❌ Failure: update_last_refill_date returned False.")

if __name__ == "__main__":
    asyncio.run(test_refill_correction())
