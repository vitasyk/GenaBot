import asyncio
import logging
from sqlalchemy import text
from bot.database.main import session_maker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def fix_columns():
    async with session_maker() as session:
        logger.info("Starting database schema update...")
        
        # List of columns to alter to BIGINT
        alterations = [
            ("users", "id"),
            ("logs", "user_id"),
            ("shifts", "worker_id"),
            ("schedule_entries", "created_by"),
            ("worker_shifts", "worker1_id"),
            ("worker_shifts", "worker2_id"),
            ("worker_shifts", "worker3_id"),
            ("refuel_sessions", "worker1_id"),
            ("refuel_sessions", "worker2_id"),
            ("refuel_sessions", "worker3_id"),
            ("refuel_sessions", "completed_by")
        ]
        
        for table, column in alterations:
            try:
                # We use ALTER TABLE ... ALTER COLUMN ... TYPE BIGINT
                # Using 'USING column::BIGINT' for safety
                query = text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE BIGINT USING {column}::BIGINT;")
                await session.execute(query)
                logger.info(f"✅ Altered {table}.{column} to BIGINT")
            except Exception as e:
                logger.error(f"❌ Failed to alter {table}.{column}: {e}")
                await session.rollback()
                # Continue with others if possible or abort? Let's try others.
                pass
        
        await session.commit()
        logger.info("Schema update complete! 🎉")

if __name__ == "__main__":
    asyncio.run(fix_columns())
