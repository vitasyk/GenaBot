---
name: pytest-asyncio-bot
description: How to test GenaBot with pytest and pytest-asyncio — services, repositories, aiogram handlers with mocked Telegram objects, scheduler/time logic and the schedule parser. Use when writing or fixing tests, or before marking any bot change done.
---

# Testing GenaBot

## Setup (once)
- Dev deps: `pytest`, `pytest-asyncio`, `ruff` (keep them out of the runtime `requirements.txt`,
  e.g. `requirements-dev.txt`).
- `pytest.ini` (or `pyproject.toml`):
  ```ini
  [pytest]
  asyncio_mode = auto
  testpaths = tests
  ```
- Tests live in `tests/`, mirroring `bot/` (`tests/services/test_generator.py`, ...).
- `bot.config` reads settings at import time: set dummy env vars in `tests/conftest.py` before
  importing anything from `bot`.

## What to test, cheapest first
1. **Pure logic** (`schedule_parser`, midnight/shift time math, fuel calculations): plain unit
   tests, many cases, no I/O. Freeze "now" by passing it in as an argument rather than patching
   `datetime`.
2. **Services**: construct with fake repositories (`AsyncMock(spec=GeneratorRepository)`) and
   assert on calls and return values.
3. **Repositories**: real Postgres test DB (never Supabase prod). Fixture opens a connection,
   begins a transaction, binds an `AsyncSession` to it and rolls back after the test:
   ```python
   @pytest.fixture
   async def session(engine):
       async with engine.connect() as conn:
           trans = await conn.begin()
           s = AsyncSession(bind=conn, expire_on_commit=False)
           yield s
           await s.close()
           await trans.rollback()
   ```
   Schema via `alembic upgrade head` on the test DB in a session-scoped fixture.
   SQLite is not a substitute (native enums, timezone behaviour differ).
4. **Handlers**: call the handler function directly with mocks — no Telegram network:
   ```python
   from unittest.mock import AsyncMock, MagicMock

   cb = MagicMock()
   cb.data = "session_start:42"
   cb.answer = AsyncMock()
   cb.message.edit_text = AsyncMock()
   await start_session_handler(cb, session_service=fake_service)
   cb.answer.assert_awaited()
   ```
   For FSM use a real `FSMContext` over `MemoryStorage`
   (`FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))`).
5. **Google Sheets / weather / HOE site / Claude API**: never hit the network in tests; save a
   real response or image as a fixture file (`tests/fixtures/`) and mock the client
   (`client.messages.parse = AsyncMock(...)`).

## Rules
- A bug fix starts with a failing test that reproduces it (see `test-driven-development`).
- Each test is independent: no order dependence, no shared global state, no real `BOT_TOKEN`.
- Run `pytest -q` and `ruff check .` before saying a change is done; report failures verbatim.
