from sqlalchemy.ext.asyncio import AsyncSession
from typing import Generic, TypeVar, Type

T = TypeVar("T")

class BaseRepository(Generic[T]):
    def __init__(self, session: AsyncSession, model: Type[T]):
        self.session = session
        self.model = model
