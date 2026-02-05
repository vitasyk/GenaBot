from datetime import datetime
from sqlalchemy import select
from bot.database.repositories.base import BaseRepository
from bot.database.models import Generator, GenStatus

class GeneratorRepository(BaseRepository[Generator]):
    def __init__(self, session):
        super().__init__(session, Generator)

    async def get_all(self) -> list[Generator]:
        stmt = select(Generator).order_by(Generator.name)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> Generator | None:
        stmt = select(Generator).where(Generator.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_status(self, name: str, status: GenStatus, start_time: datetime | None = None) -> Generator:
        gen = await self.get_by_name(name)
        if gen:
            gen.status = status
            if start_time is not None:
                gen.current_run_start = start_time
            elif status == GenStatus.stopped:
                gen.current_run_start = None
        return gen

    async def add_fuel(self, name: str, liters: int) -> int:
        gen = await self.get_by_name(name)
        if gen:
            gen.fuel_level += liters
            return gen.fuel_level
        return 0

    async def set_fuel_level(self, name: str, liters: float) -> float:
        gen = await self.get_by_name(name)
        if gen:
            gen.fuel_level = liters
            return gen.fuel_level
        return 0.0
    
    async def get_consumption(self, name: str) -> float:
        gen = await self.get_by_name(name)
        return gen.consumption_rate if gen else 0.0

    async def update_specs(self, name: str, tank_capacity: float, consumption_rate: float) -> Generator | None:
        gen = await self.get_by_name(name)
        if gen:
            gen.tank_capacity = tank_capacity
            gen.consumption_rate = consumption_rate
        return gen

    async def rename_generator(self, old_name: str, new_name: str) -> bool:
        gen = await self.get_by_name(old_name)
        if gen:
            gen.name = new_name
            return True
        return False

    async def update_total_hours(self, name: str, hours: float) -> bool:
        gen = await self.get_by_name(name)
        if gen:
            gen.total_hours_run = hours
            return True
        return False

