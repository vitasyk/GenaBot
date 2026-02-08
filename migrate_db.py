import asyncio
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, insert, text
from bot.database.models import Base, User, Inventory, Generator, LogEvent, Shift, ScheduleEntry, WorkerShift, RefuelSession
from bot.config import config

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# List of models in dependency order (parents first)
MODELS = [
    User,
    Inventory,
    Generator,
    LogEvent,
    Shift,
    ScheduleEntry,
    WorkerShift,
    RefuelSession
]

async def migrate_table(source_session: AsyncSession, target_session: AsyncSession, model):
    table_name = model.__tablename__
    logger.info(f"Migrating table: {table_name}...")
    
    # 1. Fetch all records from source
    result = await source_session.execute(select(model))
    records = result.scalars().all()
    
    if not records:
        logger.info(f"No records found for {table_name}. Skipping.")
        return

    # 2. Convert to dictionaries for insertion
    data = []
    for record in records:
        row = {c.name: getattr(record, c.name) for c in model.__table__.columns}
        data.append(row)

    # 3. Insert into target
    # We use bulk insert or simple insert
    # Using 'insert(model).values(data)' for efficiency
    try:
        await target_session.execute(insert(model).values(data))
        await target_session.commit()
        logger.info(f"Successfully migrated {len(data)} records for {table_name}.")
    except Exception as e:
        await target_session.rollback()
        logger.error(f"Failed to migrate {table_name}: {e}")
        raise

async def reset_sequences(target_session: AsyncSession):
    """Resets PostgreSQL sequences after manual ID insertion"""
    logger.info("Resetting PostgreSQL sequences...")
    tables_with_serial = ['inventory', 'generators', 'logs', 'shifts', 'schedule_entries', 'worker_shifts', 'refuel_sessions']
    for table in tables_with_serial:
        try:
            # PostgreSQL command to sync identity/sequence
            await target_session.execute(text(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE(MAX(id), 1)) FROM {table}"))
        except Exception as e:
            logger.warning(f"Could not reset sequence for {table}: {e}")
    await target_session.commit()

async def main():
    # SOURCE: Current Supabase (from .env or argument)
    source_url = config.DATABASE_URL.get_secret_value()
    # TARGET: Local Docker Postgres (passed as argument or default to internal docker service name)
    import sys
    target_url = sys.argv[1] if len(sys.argv) > 1 else "postgresql+asyncpg://postgres:postgres@db:5432/genabot"

    logger.info(f"Source: {source_url.split('@')[1]}") # Log host only for security
    logger.info(f"Target: {target_url.split('@')[1]}")

    source_engine = create_async_engine(source_url)
    target_engine = create_async_engine(target_url)

    SourceSession = sessionmaker(source_engine, class_=AsyncSession, expire_on_commit=False)
    TargetSession = sessionmaker(target_engine, class_=AsyncSession, expire_on_commit=False)

    async with SourceSession() as source_session:
        async with TargetSession() as target_session:
            # 1. Clean up target tables if they aren't empty? 
            # CAUTION: This script assumes the target tables are empty (new deployment)
            
            # 2. Migrate in order
            for model in MODELS:
                await migrate_table(source_session, target_session, model)
            
            # 3. Sync sequences
            await reset_sequences(target_session)

    logger.info("Migration complete! 🎉")

if __name__ == "__main__":
    asyncio.run(main())
