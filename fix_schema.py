import asyncio
import logging
from bot.config import config
from bot.database.main import session_maker
from sqlalchemy import text

async def fix_schema():
    logging.basicConfig(level=logging.INFO)
    logging.info("Starting schema fix...")
    
    async with session_maker() as session:
        # Add sheet_name to users if not exists
        logging.info("Adding sheet_name column to users...")
        await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS sheet_name VARCHAR;"))

        # Add tank_capacity if not exists
        await session.execute(text("ALTER TABLE generators ADD COLUMN IF NOT EXISTS tank_capacity FLOAT DEFAULT 40.0;"))
        
        # Add consumption_rate if not exists, or alter type
        logging.info("Updating consumption_rate column...")
        await session.execute(text("ALTER TABLE generators ADD COLUMN IF NOT EXISTS consumption_rate FLOAT DEFAULT 2.0;"))
        # Verify type - simpler to just try alter, postgres handles casting if compatible or we just leave it if it works
        # But we want Float.
        await session.execute(text("ALTER TABLE generators ALTER COLUMN consumption_rate TYPE FLOAT USING consumption_rate::double precision;"))

        # Add fuel_level if not exists, or alter type
        logging.info("Updating fuel_level column...")
        await session.execute(text("ALTER TABLE generators ADD COLUMN IF NOT EXISTS fuel_level FLOAT DEFAULT 0.0;"))
        await session.execute(text("ALTER TABLE generators ALTER COLUMN fuel_level TYPE FLOAT USING fuel_level::double precision;"))

        # Add tracking fields
        logging.info("Adding tracking fields...")
        await session.execute(text("ALTER TABLE generators ADD COLUMN IF NOT EXISTS total_hours_run FLOAT DEFAULT 0.0;"))
        await session.execute(text("ALTER TABLE generators ADD COLUMN IF NOT EXISTS last_maintenance TIMESTAMP;"))
        
        # Add worker_shifts table
        logging.info("Creating worker_shifts table...")
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS worker_shifts (
                id SERIAL PRIMARY KEY,
                date DATE NOT NULL,
                shift_number INTEGER NOT NULL,
                worker1_id INTEGER REFERENCES users(id),
                worker2_id INTEGER REFERENCES users(id),
                start_time VARCHAR NOT NULL,
                end_time VARCHAR NOT NULL,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """))

        # Add refuel_sessions table
        logging.info("Dropping and Re-creating refuel_sessions table to fix status type...")
        await session.execute(text("DROP TABLE IF EXISTS refuel_sessions CASCADE;"))
        await session.execute(text("""
            CREATE TABLE refuel_sessions (
                id SERIAL PRIMARY KEY,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                deadline TIMESTAMP NOT NULL,
                status VARCHAR DEFAULT 'pending',
                worker1_id INTEGER REFERENCES users(id),
                worker2_id INTEGER REFERENCES users(id),
                gen_name VARCHAR,
                liters FLOAT,
                cans FLOAT,
                notes VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_by INTEGER REFERENCES users(id)
            );
        """))
        
        await session.commit()
        logging.info("Schema fix completed!")

if __name__ == "__main__":
    asyncio.run(fix_schema())
