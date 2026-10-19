from sqlalchemy import select

from bot.config import config
from bot.database.models import User, UserRole
from bot.database.repositories.base import BaseRepository


def resolve_role(user_id: int) -> UserRole:
    """Role the current config grants (authoritative over the role stored in DB).

    Read on every call: RESTRICT_ACCESS can be changed at runtime by admins.
    """
    if user_id in config.ADMIN_IDS:
        return UserRole.admin
    if not config.RESTRICT_ACCESS or user_id in config.ALLOWED_IDS:
        return UserRole.worker
    return UserRole.blocked


class UserRepository(BaseRepository[User]):
    def __init__(self, session):
        super().__init__(session, User)

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def create_or_update(self, user_id: int, name: str, role: UserRole = UserRole.worker) -> User:
        target_role = resolve_role(user_id)
        user = await self.get_by_id(user_id)
        if not user:
            user = User(id=user_id, name=name, role=target_role)
            self.session.add(user)
        else:
            user.name = name
            user.role = target_role # Force update to match current config

        return user
    
    async def get_all(self, include_blocked: bool = False) -> list[User]:
        stmt = select(User)
        if not include_blocked:
            stmt = stmt.where(User.role != UserRole.blocked)
        stmt = stmt.order_by(User.name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> User | None:
        """Find user by telegram name (exact match)"""
        stmt = select(User).where(User.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_sheet_name(self, name: str) -> User | None:
        """Find user by spreadsheet name mapping"""
        stmt = select(User).where(User.sheet_name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_sheet_name(self, user_id: int, sheet_name: str | None) -> User | None:
        user = await self.get_by_id(user_id)
        if user:
            user.sheet_name = sheet_name
            await self.session.flush()
        return user
