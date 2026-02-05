import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from redis.asyncio import Redis
from dotenv import load_dotenv

load_dotenv()

async def verify_db():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("❌ DATABASE_URL not found in .env")
        return False
    
    print(f"🔄 Testing DB Connection...")
    try:
        engine = create_async_engine(db_url, echo=False)
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            print(f"✅ DB Connection Successful! Result: {result.scalar()}")
        await engine.dispose()
        return True
    except Exception as e:
        print(f"❌ DB Connection Failed: {e}")
        return False

async def verify_redis():
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("❌ REDIS_URL not found in .env")
        return False

    print(f"🔄 Testing Redis Connection...")
    try:
        r = Redis.from_url(redis_url)
        await r.ping()
        print("✅ Redis Connection Successful!")
        await r.close()
        return True
    except Exception as e:
        print(f"❌ Redis Connection Failed: {e}")
        return False

async def main():
    db_ok = await verify_db()
    redis_ok = await verify_redis()
    
    if db_ok and redis_ok:
        print("\n🚀 All systems operational!")
    else:
        print("\n⚠️ Some connections failed.")

if __name__ == "__main__":
    asyncio.run(main())
