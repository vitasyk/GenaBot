from sqlalchemy import select
from bot.database.repositories.base import BaseRepository
from bot.database.models import User, UserRole

class UserRepository(BaseRepository[User]):
    def __init__(self, session):
        super().__init__(session, User)

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def create_or_update(self, user_id: int, name: str, role: UserRole = UserRole.worker) -> User:
        # Check against config
        from bot.config import config
        if user_id in config.ADMIN_IDS:
            role = UserRole.admin
        
        # Access Control Logic
        elif config.RESTRICT_ACCESS:
            if user_id in config.ALLOWED_IDS:
                role = UserRole.worker
            else:
                role = UserRole.blocked
        else:
             # Public access enabled
             role = UserRole.worker
            
        user = await self.get_by_id(user_id)
        if not user:
            user = User(id=user_id, name=name, role=role)
            self.session.add(user)
        else:
            user.name = name
            # Update role dynamically
            if user_id in config.ADMIN_IDS:
                user.role = UserRole.admin
            elif config.RESTRICT_ACCESS:
                # Demote if not allowed anymore and not admin
                if user_id not in config.ALLOWED_IDS and user.role != UserRole.admin:
                    user.role = UserRole.blocked
                # Promote to worker if added to allowed and was blocked
                elif user_id in config.ALLOWED_IDS and user.role == UserRole.blocked:
                    user.role = UserRole.worker
            else:
                # If public, unblock blocked users
                if user.role == UserRole.blocked:
                    user.role = UserRole.worker

        return user
    
    async def get_admins(self) -> list[User]:
        stmt = select(User).where(User.role == UserRole.admin)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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
