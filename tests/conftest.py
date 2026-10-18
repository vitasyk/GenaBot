import os

# bot.config reads settings at import time; tests must not need a real .env
_TEST_ENV = {
    "BOT_TOKEN": "123456:TEST",
    "ADMIN_IDS": "[1]",
    "ALLOWED_IDS": "[2]",
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "REDIS_URL": "redis://localhost:6379/0",
    "SECRET_KEY": "test",
    "WEATHER_API_KEY": "test",
    "CITY_LAT": "49.42",
    "CITY_LON": "26.98",
    "ANTHROPIC_API_KEY": "test",
    "SCHEDULE_SPREADSHEET_ID": "test-sheet",
}
for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)

import pytest  # noqa: E402


class FakeRedis:
    """In-memory stand-in for the few redis.asyncio calls the bot makes."""

    def __init__(self):
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def set(self, key: str, value, ex=None, nx: bool = False) -> bool | None:
        if nx and key in self.data:
            return None
        self.data[key] = value if isinstance(value, bytes) else str(value).encode()
        return True

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()
