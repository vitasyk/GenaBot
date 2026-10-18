---
name: aiogram3-bot
description: GenaBot conventions for aiogram 3 Telegram bot code — routers, handlers, FSM on Redis, middleware DI, callback data, keyboards, message edits, error handling and APScheduler jobs. Use for any work in bot/handlers, bot/keyboards, bot/middlewares, bot/states.py, bot/scheduler.py or bot/__main__.py.
---

# aiogram 3 in GenaBot

Read `.agent/AGENT.MD` first; this skill is how its rules look in this codebase.

## Layers
Handler → Service (`bot/services`) → Repository (`bot/database/repositories`) → DB.
- A handler parses the update, calls a service, sends the answer. No SQL, no business rules.
- Dependencies come from `DbSessionMiddleware` (`bot/middlewares/di.py`) as handler arguments
  (`inventory_service: InventoryService`, `user_repo: UserRepository`, ...). It opens one session
  per update and commits/rolls back around the handler.
- Do **not** open `session_maker()` inside a handler (old code in `handlers/sessions.py` still does;
  when you touch such a handler, move it to an injected service). A new service is wired in `di.py`.
- Jobs outside an update (scheduler, startup) open their own `async with session_maker() as s:`
  and commit explicitly.

## Routers
- One `router = Router()` per feature module in `bot/handlers/`, included in `bot/__main__.py`.
  Order matters: the first matching handler wins (admin router goes first).
- Access control as a filter or router-level middleware (`ADMIN_IDS`, `ALLOWED_IDS`,
  `RESTRICT_ACCESS` from `bot/config.py`), never an `if` copied into each handler.

## Callback data
Prefer typed factories over `F.data.startswith("x:")` + `split(":")`:
```python
from aiogram.filters.callback_data import CallbackData

class SessionCb(CallbackData, prefix="session"):
    action: str
    id: int

# keyboard: callback_data=SessionCb(action="start", id=s.id).pack()
@router.callback_query(SessionCb.filter(F.action == "start"))
async def start(cb: CallbackQuery, callback_data: SessionCb, ...): ...
```
Packed data must stay ≤ 64 bytes. Keep existing string prefixes working when you migrate
(old buttons in chats still send them).

## FSM
- States in `bot/states.py` (`StatesGroup`). Storage is `RedisStorage`, so state survives restarts.
- Store only small, serializable values with `state.update_data`; IDs, not ORM objects.
- Every multi-step flow needs a way out (`/cancel` or a Cancel button → `await state.clear()`).

## Messages and callbacks
- Always `await callback.answer()` (even empty), or Telegram shows a spinner for ~15 s.
- `edit_text` with unchanged text/markup raises `TelegramBadRequest: message is not modified`;
  catch exactly that case and ignore it, re-raise the rest:
  ```python
  from aiogram.exceptions import TelegramBadRequest
  try:
      await cb.message.edit_text(text, reply_markup=kb)
  except TelegramBadRequest as e:
      if "message is not modified" not in str(e):
          raise
  ```
- Messages older than 48 h can't be edited and some can't be deleted: send a new one instead.
- `parse_mode` HTML: escape user-provided text with `html.escape` (names, comments).
- Text lives in the localization layer (fluent), not in Python strings. When you touch a handler
  with inline Ukrainian text, move its strings out.

## Keyboards
`bot/keyboards/*`: builders take data (lists, ids) and return markup; no DB or service calls.
Use `InlineKeyboardBuilder` / `ReplyKeyboardBuilder` and `.adjust(n)` for rows.

## Errors and logging
- One global `@router.errors()` / `dp.errors` handler (`ErrorEvent`) logs the exception with
  `user_id` and update type; don't wrap every handler in try/except.
- Never swallow exceptions silently. Network calls (weather, Google Sheets, `requests`) must not
  block the event loop: use an async client or `await asyncio.to_thread(...)`.
- Log with context, not f-string-only messages; no tokens or `DATABASE_URL` in logs.

## Scheduler (APScheduler 3, `bot/scheduler.py`)
- `AsyncIOScheduler` on the bot's loop; job functions are `async` and get `bot` as an argument.
- Use stable job `id`s with `replace_existing=True` so a restart doesn't duplicate jobs.
- Times: the bot runs in Docker, where the container clock is **UTC**, so a bare
  `datetime.now()` is not Kyiv time. Use `ZoneInfo(config.TIMEZONE)` explicitly and never mix
  naive UTC (`generators.current_run_start`, `logs.timestamp`) with naive Kyiv values
  (`refuel_sessions`, `schedule_entries`) in one comparison. Blocks that cross midnight are
  the classic bug here; cover them with a test.
- A failing job must log and not kill the scheduler; long work → `asyncio.to_thread`.

## Polling
`dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())`. Send long
broadcasts with small delays (Telegram limit ~30 msg/s globally, 1 msg/s per chat) and handle
`TelegramRetryAfter` by sleeping `e.retry_after`.

## Domain flow (how the bot works today)
- Outage schedule: admins enter hours in "📉 Графік" (`handlers/schedule.py` →
  `schedule_entries`). `SessionService.check_power_outage` (job, every minute) reads today and
  tomorrow and creates a refuel session when power **returns** (end of a block).
- A session is sent to every worker on shift (Google Sheets roster, `services/google_sheets.py`);
  any of them can start/complete it, so completion must be idempotent.
- Completing a session deducts fuel from stock and adds it to the chosen generators.

## Before done
`ruff check .`, `pytest`, then run the bot locally in Docker (`docker compose up --build`)
against a test bot token and click through the changed flow (including Cancel and a
double-click on the same button). Deploy to the server only after that.
