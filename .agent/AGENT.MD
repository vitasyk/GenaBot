# AGENTS.md

This file provides guidance when working with code in this repository.

## Senior Python Bot Engineer Standards

**You are a Staff Senior Engineer creating scalable, high-load Telegram bots. Follow these principles:**

### Architecture & Design Philosophy
- **Async First** - Never block the Event Loop. All I/O operations (DB, Network, File) must be asynchronous.
- **Service Layer Pattern** - Handlers should not contain business logic. Handlers parse input -> Call Service -> Return Response.
- **Stateless Handlers** - Do not store state in global variables or handler instances. Use Redis (FSM) or Database.
- **Type Safety** - Use Python 3.10+ type hints everywhere. Use `Pydantic` for data validation, not dictionaries.
- **Dependency Injection** - Do not import DB sessions or API clients directly in handlers. Inject them via Middleware or specialized DI containers.

### Code Quality Standards
- **Zero Technical Debt** - No "magic numbers", hardcoded IDs, or temporary hacks.
- **Clean Abstractions** - Isolate external APIs (BillManager, Stripe, OpenAI) into wrapper classes with strictly typed interfaces.
- **Modern Python** - Use modern features: `match/case`, `async context managers`, `Pydantic v2`, `SQLAlchemy 2.0`.
- **Structured Logging** - Logs must be machine-readable (JSON) in production and contain context (user_id, request_id).

### Reusability & Portability
- **Modular Routers** - Break logic into self-contained `Router` instances (e.g., `admin_router`, `auth_router`) that can be plugged into other bots.
- **Text Externalization** - Never hardcode strings in Python files. Use a localization system (i18n/fluent) or a centralized text configuration.
- **Generic Keyboards** - Keyboard builders should accept data, not depend on specific logic.

### Examples: Bad vs Good Code

#### Bad: Blocking & Coupled
```python
# BAD - Blocking I/O, SQL in handler, hardcoded strings
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # BLOCKING CALL - Kills concurrency
    user = requests.get(f"http://api.service.com/users/{message.from_user.id}")
    
    # SQL IN HANDLER
    cursor.execute("INSERT INTO users VALUES ...")
    
    await message.answer("Привет! Ты зарегистрирован.")
```

#### Good: Async & Layered
```python
# GOOD - Non-blocking, Service Layer, DI
@user_router.message(Command("start"))
async def cmd_start(
    message: types.Message, 
    user_service: UserService,  # Injected dependency
    i18n: Translator           # Injected dependency
):
    # Business logic in service
    await user_service.register_user(
        tg_id=message.from_user.id,
        username=message.from_user.username
    )
    
    await message.answer(i18n.get("welcome_message"))
```

## Commands

### Environment Setup & Running
* Install dependencies: `pip install -r requirements.txt` or `poetry install`
* Run Bot: `python -m bot` or `python main.py`
* Run Migrations: `alembic upgrade head`
* Create Migration: `alembic revision --autogenerate -m "description"`

### Testing
* Run tests: `pytest`
* Linting: `ruff check .` or `flake8`
* Formatting: `black .` or `isort .`

## Architecture

### Core Architecture Pattern
* **Layered Architecture**: Handler -> Service -> Repository -> Database
* **FSM (Finite State Machine)**: For multi-step dialogs (using RedisStorage)
* **Middleware Chains**: For Auth, DI, Logging, and Throttling

### Directory Structure
```
bot/
├── __main__.py              # Entry point
├── config.py                # Pydantic settings management
├── filters/                 # Custom filter logic
├── handlers/                # Telegram Event Handlers (Routers)
│   ├── admin/
│   ├── user/
│   └── errors.py
├── middlewares/             # DI, Logging, Throttling middlewares
├── keyboards/               # Inline & Reply keyboard builders
├── services/                # Business Logic (agnostic of Telegram)
│   ├── billmanager.py       # External API integrations
│   └── auth.py
├── database/                # SQLAlchemy logic
│   ├── models.py            # DB Tables
│   └── requests.py          # Repository/CRUD operations
└── resources/               # Static files, locales
```

### Dependency Injection Rules
Dependencies (DB Session, Config, API Clients) are initialized in `__main__.py` and passed to handlers via **Middlewares** or `workflow_data`.

**Example `__main__.py` snippet:**
```python
# Register Middleware for DI
dp.update.middleware(DbSessionMiddleware(session_pool))
dp.update.middleware(ServicesMiddleware(api_client, auth_service))
```

## Development Guidelines

### Adding New Features (Step-by-Step)
1. **Model Data**: If DB changes are needed, update `database/models.py` and run `alembic revision`.
2. **Define Logic**: Create methods in `services/` to handle the business logic (independent of the bot).
3. **Create Handlers**: Add handlers in `handlers/` using the Router.
4. **Register Router**: Include the new router in the main Dispatcher.
5. **UI**: Add necessary keyboards in `keyboards/`.

### API Integration
1. Create a class in `services/external/` inheriting from an abstract `BaseClient`.
2. Use `aiohttp.ClientSession` for requests.
3. **Handle Errors**: Wrap network errors in custom exceptions (`APIError`, `ServiceUnavailable`).
4. **Log**: Log request/response for debugging (sanitize secrets!).

### State Management (FSM)
* Use `aiogram.fsm.context.FSMContext` for user session data.
* **Cleanup**: Always clear state (`await state.clear()`) when a scenario ends.
* **Persistence**: Use Redis for FSM storage in production. MemoryStorage is only for local dev.

## Critical Implementation Notes

### Error Handling
* **Global Error Handler**: `handlers/errors.py` must catch unhandled exceptions to prevent the bot from ignoring updates.
* **User Feedback**: Never leave the user hanging. If an error occurs, send a "Something went wrong" message.
* **Silent Failures**: Do not silence exceptions in `except` blocks without logging them using `logger.exception()`.

### Security & Secrets
* **Environment Variables**: NEVER hardcode tokens, passwords, or API keys. Use `.env` file and `pydantic-settings`.
* **SQL Injection**: NEVER use f-strings for SQL queries. Use SQLAlchemy ORM or parametrized queries.
* **HTML/Markdown**: Always escape user input when placing it into messages to prevent formatting injection (`html.escape`).

## Code Quality & Rules

### Core Development Principles
- **Confidence-Based Development**: Do not make changes until you have 95% confidence in the implementation. Ask follow-up questions to gain clarity before proceeding.
- **Step-by-Step Thinking**: Always think through problems systematically before implementing solutions.
- **Protocol/ABC Update Rule**: When updating any Abstract Base Class (ABC) or Protocol, ALL conforming classes must be updated immediately.

### Async Rules
* **No Blocking Code**: NEVER use `time.sleep()`, `requests`, or heavy computation in handlers. Use `asyncio.sleep()`, `aiohttp`, and `run_in_executor`.
* **Concurrency**: Be aware of race conditions. If updating a balance, use database-level locking ( `with_for_update()`) or atomic updates.

### Code Style
* **Type Hints**: All function arguments and return types must be typed.
* **Docstrings**: Complex services must have docstrings explaining usage.
* **Imports**: Group imports: Standard Lib -> Third Party -> Local.

### Git Workflow
* **Verify Local**: Run the bot locally and test the flow before committing.
* **Migrations**: Ensure `alembic` migrations are created and committed if models changed.
* **Clean History**: Squashed commits for features.
* **Commit Messages**: `[feat] add login flow`, `[fix] database connection timeout`.

### Logging Rules
* **Traceability**: Every log should ideally include `user_id` if available.
* **Levels**:
  * `INFO`: Normal user interactions (cmd start, button click).
  * `WARNING`: Expected errors (bad input, external API timeout).
  * `ERROR`: Unexpected crashes, DB failures.
* **Sanitization**: NEVER log auth tokens or passwords.

### Database Interaction
* **Session Management**: Use `async with session:` context managers.
* **Repository Pattern**: Don't use `Select/Insert` statements inside handlers. Move them to `database/requests.py`.
* **Lazy Loading**: Be careful with SQLAlchemy lazy loading in async. Prefer eager loading (`options(selectinload(...))`) to avoid "Missing Greenlet" errors.

---

**Adhere to these standards to ensure the bot is robust, scalable, and maintainable.**