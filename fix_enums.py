
import asyncio
from sqlalchemy import text
from bot.database.main import session_maker

async def fix_enums():
    async with session_maker() as session:
        print("Checking/Fixing enums...")
        
        # 1. Add missing values to genstatus
        try:
            await session.execute(text("ALTER TYPE genstatus ADD VALUE IF NOT EXISTS 'standby'"))
            await session.commit()
            print("Enum 'genstatus': ensured 'standby' exists.")
        except Exception as e:
            print(f"Note on genstatus: {e}")
            await session.rollback()

        # 2. Add missing values to userrole
        try:
            await session.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'blocked'"))
            await session.commit()
            print("Enum 'userrole': ensured 'blocked' exists.")
        except Exception as e:
            print(f"Note on userrole: {e}")
            await session.rollback()
            
        print("Done.")

if __name__ == "__main__":
    asyncio.run(fix_enums())
