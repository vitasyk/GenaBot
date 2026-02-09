from bot.database.repositories.base import BaseRepository
from bot.database.models import LogEvent

class LogRepository(BaseRepository[LogEvent]):
    def __init__(self, session):
        super().__init__(session, LogEvent)

    async def log_action(self, user_id: int, action: str, details: str | None = None):
        event = LogEvent(user_id=user_id, action=action, details=details)
        self.session.add(event)

    async def get_last_action(self, action: str) -> LogEvent | None:
        from sqlalchemy import select, desc
        stmt = select(LogEvent).where(LogEvent.action == action).order_by(desc(LogEvent.timestamp)).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_actions_since(self, action: str, since_date) -> list[LogEvent]:
        from sqlalchemy import select
        stmt = select(LogEvent).where(LogEvent.action == action, LogEvent.timestamp >= since_date)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def clear_all(self):
        from sqlalchemy import delete
        await self.session.execute(delete(LogEvent))

    async def get_recent_logs(self, limit: int = 25) -> list[LogEvent]:
        from sqlalchemy import select, desc
        stmt = select(LogEvent).order_by(desc(LogEvent.timestamp)).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
