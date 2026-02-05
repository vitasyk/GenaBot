from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from bot.config import config

engine = create_async_engine(
    config.DATABASE_URL.get_secret_value(),
    echo=config.LOG_LEVEL == "DEBUG",
    pool_pre_ping=True,
    connect_args={"statement_cache_size": 0}
)

session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_session() -> AsyncSession:
    async with session_maker() as session:
        yield session
