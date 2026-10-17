from aiogram.types import CallbackQuery, Message

from bot.database.models import UserRole
from bot.database.repositories.user import UserRepository


async def is_admin(event: Message | CallbackQuery, user_repo: UserRepository) -> bool:
    user = await user_repo.get_by_id(event.from_user.id)
    return user is not None and user.role == UserRole.admin
