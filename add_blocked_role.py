import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

async def add_blocked_role():
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        try:
            await conn.execute(text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'blocked';"))
            print("Successfully added 'blocked' to userrole enum.")
        except Exception as e:
            try:
                await conn.execute(text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'blocked';"))
                print("Successfully added 'blocked' to user_role enum (fallback).")
            except Exception as e2:
                print(f"Error: {e2}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(add_blocked_role())
