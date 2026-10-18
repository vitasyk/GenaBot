---
name: sqlalchemy-async-alembic
description: GenaBot conventions for SQLAlchemy 2.0 async (asyncpg, Supabase Postgres) models, repositories, transactions and Alembic migrations. Use for any work in bot/database, alembic/, models, enums, or one-off schema scripts.
---

# SQLAlchemy 2 async + Alembic in GenaBot

## Engine and sessions (`bot/database/main.py`)
- `create_async_engine(..., pool_pre_ping=True, connect_args={"statement_cache_size": 0})`.
  `statement_cache_size=0` is required behind the Supabase pooler (pgbouncer) — keep it, and
  pass the same `connect_args` to any other engine (Alembic `env.py`, scripts).
- Production DB is Supabase (`DATABASE_URL` in the server `.env`); the `db` service in
  `docker-compose.yml` is only for local testing. Supabase exposes `public` via its REST API,
  so every table needs RLS enabled (the bot connects as the table owner and bypasses it).
- `async_sessionmaker(engine, expire_on_commit=False)`: objects stay readable after commit.
- One session per Telegram update (middleware) or per scheduler job. Never share a session
  across concurrent tasks; never keep one in a global.

## Models (`bot/database/models.py`)
- 2.0 style: `class X(Base)` with `Mapped[...]` and `mapped_column(...)`.
- Timestamps: columns are naive `DateTime`. Today `generators`/`logs` hold UTC and
  `refuel_sessions`/`schedule_entries` hold Kyiv time; know which one a column holds before
  comparing. New columns: `DateTime(timezone=True)` and aware datetimes.
- Telegram IDs exceed 32 bits: every column holding a user id is `BigInteger`.
- Index every foreign key and every column used in `WHERE`/`ORDER BY` of hot queries.
- Enums: Postgres native enums need a migration for every new value
  (`ALTER TYPE ... ADD VALUE`, which can't run inside a transaction on old PG — use
  `op.execute` with `autocommit_block()`). Do it in Alembic, not in hand-run SQL files like
  `migrations/*.sql`.

## Repositories (`bot/database/repositories`)
- Subclass `BaseRepository`; take the `AsyncSession` in the constructor.
- `select()` + `await session.execute()` / `session.scalars()`; no legacy `session.query`.
- Repositories `flush()` when they need generated ids; **they don't commit** — the middleware
  or job owns the transaction.
- Relationships are not lazy-loadable in async: use `selectinload(...)`/`joinedload(...)` in the
  query, otherwise you get `MissingGreenlet`.
- Concurrent updates of the same row (two people pressing the same button): use
  `with_for_update()` or a conditional `UPDATE ... WHERE status = :expected RETURNING`, and treat
  "0 rows" as "already done".

## Migrations (Alembic)
- Schema changes only through Alembic: edit models → `alembic revision --autogenerate -m "..."`
  → **read the generated file** (autogenerate misses enum value changes, server defaults,
  renames that look like drop+add) → `alembic upgrade head` on a dev DB.
- No new ad-hoc `fix_*.py` / `migrate_db.py` scripts against production.
- Data migrations: in the revision with `op.execute(sa.text(...))`, idempotent, small batches.
- Every revision has a working `downgrade()` or an explicit comment why it can't.
- Back up before applying to production (Supabase dashboard backup or `pg_dump`).

## Raw SQL
Only in migrations or a measured hot path, always with bound parameters (`sa.text` + params),
never f-strings.

## Tests
See the `pytest-asyncio-bot` skill: repository tests run against a real Postgres test database
inside a transaction that is rolled back.
