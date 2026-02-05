import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

async def add_standby_value():
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        try:
            # PostgreSQL command to add value to ENUM type
            # We wrap in a block to catch if it already exists (though ADD VALUE IF NOT EXISTS is supported in newer PG)
            await conn.execute(text("ALTER TYPE genstatus ADD VALUE IF NOT EXISTS 'standby';"))
            print("Successfully added 'standby' to genstatus enum.")
        except Exception as e:
            # Fallback for older PG or if type name is different (init.sql used 'gen_status' or auto-generated name?)
            # Let's check init.sql content if possible, but usually SQLAlchemy uses lowercase of Enum name or column type.
            # In init.sql it was: CREATE TYPE gen_status AS ENUM ('stopped', 'running');
            try:
                await conn.execute(text("ALTER TYPE gen_status ADD VALUE IF NOT EXISTS 'standby';"))
                print("Successfully added 'standby' to gen_status enum (fallback name).")
            except Exception as e2:
                print(f"Error adding value: {e2}")
                print(f"Original error: {e}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(add_standby_value())
