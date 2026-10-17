from datetime import datetime

from sqlalchemy import select

from bot.database.repositories.base import BaseRepository
from bot.database.models import Generator, GenStatus

class GeneratorRepository(BaseRepository[Generator]):
    def __init__(self, session):
        super().__init__(session, Generator)

    async def get_all(self, active_only: bool = True) -> list[Generator]:
        stmt = select(Generator).order_by(Generator.name).execution_options(populate_existing=True)
        if active_only:
            stmt = stmt.where(Generator.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, gen_id: int) -> Generator | None:
        return await self.session.get(Generator, gen_id)

    async def create(self, name: str, tank_capacity: float, consumption_rate: float) -> Generator:
        gen = Generator(
            name=name,
            status=GenStatus.stopped,
            fuel_level=0.0,
            tank_capacity=tank_capacity,
            consumption_rate=consumption_rate,
            total_hours_run=0.0,
            is_active=True,
        )
        self.session.add(gen)
        await self.session.flush()
        return gen

    async def get_by_name(self, name: str, for_update: bool = False) -> Generator | None:
        stmt = select(Generator).where(Generator.name == name)
        if for_update:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_status(self, name: str, status: GenStatus, start_time: datetime | None = None) -> Generator | None:
        gen = await self.get_by_name(name)
        if gen:
            gen.status = status
            if start_time is not None:
                gen.current_run_start = start_time
            elif status == GenStatus.stopped:
                gen.current_run_start = None
        return gen

    async def add_fuel(self, name: str, liters: float) -> float:
        """Adds (or with negative liters removes) fuel under a row lock."""
        gen = await self.get_by_name(name, for_update=True)
        if gen:
            gen.fuel_level += liters
            return gen.fuel_level
        return 0.0

    async def set_fuel_level(self, name: str, liters: float) -> float:
        gen = await self.get_by_name(name)
        if gen:
            gen.fuel_level = liters
            return gen.fuel_level
        return 0.0

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
