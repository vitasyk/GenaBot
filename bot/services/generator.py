from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.logs import LogRepository
from bot.database.models import Generator, GenStatus
from bot.generator_specs import DEFAULT_CONSUMPTION_RATE, DEFAULT_TANK_CAPACITY
from bot.services.weather import WeatherService
from bot.utils.clock import now_kyiv

class GeneratorService:
    def __init__(self, gen_repo: GeneratorRepository, log_repo: LogRepository):
        self.repo = gen_repo
        self.logs = log_repo
        self.weather = WeatherService()

    async def get_status(self) -> list[Generator]:
        """Active generators, the ones shown in start/stop/refuel menus."""
        return await self.repo.get_all()

    async def list_all(self) -> list[Generator]:
        return await self.repo.get_all(active_only=False)

    async def get_by_id(self, gen_id: int) -> Generator | None:
        return await self.repo.get_by_id(gen_id)

    async def get_active(self, gen_id: int) -> Generator | None:
        gen = await self.repo.get_by_id(gen_id)
        return gen if gen and gen.is_active else None

    async def add_generator(self, user_id: int, name: str) -> Generator | None:
        """Creates an active generator with default specs. None if the name is taken."""
        if await self.repo.get_by_name(name):
            return None
        gen = await self.repo.create(name, DEFAULT_TANK_CAPACITY, DEFAULT_CONSUMPTION_RATE)
        await self.logs.log_action(user_id, "ADD_GEN", f"Added {name}")
        return gen

    async def set_active(self, user_id: int, gen_id: int, active: bool) -> Generator | None:
        """Shows/hides a generator in the menus. A disabled generator is stopped first."""
        gen = await self.repo.get_by_id(gen_id)
        if not gen:
            return None
        if not active:
            if gen.status == GenStatus.running:
                await self._stop_and_calculate(gen, user_id)
            elif gen.status == GenStatus.standby:
                await self.repo.set_status(gen.name, GenStatus.stopped)
        gen.is_active = active
        await self.logs.log_action(user_id, "ENABLE_GEN" if active else "DISABLE_GEN", gen.name)
        return gen

    async def set_instructions(self, user_id: int, gen_id: int, text: str) -> Generator | None:
        gen = await self.repo.get_by_id(gen_id)
        if gen:
            gen.instructions = text
            await self.logs.log_action(user_id, "UPDATE_SOS", gen.name)
        return gen

    async def start_generator(self, user_id: int, name: str):
        # Safety rule: only one generator runs at a time (disabled ones included)
        all_gens = await self.repo.get_all(active_only=False)
        for g in all_gens:
            if g.status == GenStatus.running and g.name != name:
                await self._stop_and_calculate(g, user_id)

        await self.repo.set_status(name, GenStatus.running, now_kyiv())
        await self.logs.log_action(user_id, "START_GEN", f"Started {name}")

    async def set_standby(self, user_id: int, name: str):
        # Exclusive Standby: If we set X to Standby, Y must be Stopped (if it was standby)
        all_gens = await self.repo.get_all(active_only=False)

        target_gen = next((g for g in all_gens if g.name == name), None)
        if not target_gen:
            return

        if target_gen.status == GenStatus.running:
            await self._stop_and_calculate(target_gen, user_id)

        await self.repo.set_status(name, GenStatus.standby)

        for g in all_gens:
            if g.name != name and g.status == GenStatus.standby:
                await self.repo.set_status(g.name, GenStatus.stopped)

        await self.logs.log_action(user_id, "SET_STANDBY", f"Set {name} to Standby")

    async def stop_all(self, user_id: int):
        all_gens = await self.repo.get_all(active_only=False)
        for g in all_gens:
            if g.status == GenStatus.running:
                await self._stop_and_calculate(g, user_id)
            elif g.status == GenStatus.standby:
                await self.repo.set_status(g.name, GenStatus.stopped)
        await self.logs.log_action(user_id, "STOP_ALL", "Stopped all generators")

    async def _stop_and_calculate(self, gen: Generator, user_id: int):
        if not gen.current_run_start:
            await self.repo.set_status(gen.name, GenStatus.stopped)
            return

        now = max(now_kyiv(), gen.current_run_start)
        runtime_hours = (now - gen.current_run_start).total_seconds() / 3600.0

        # Weather factor (1.0 when the weather API is down)
        temp = await self.weather.get_current_temperature()
        factor = self.weather.get_consumption_factor(temp)
        consumed = runtime_hours * gen.consumption_rate * factor

        await self.repo.add_fuel(gen.name, -consumed)

        new_total = (gen.total_hours_run or 0.0) + runtime_hours
        await self.repo.update_total_hours(gen.name, new_total)

        await self.repo.set_status(gen.name, GenStatus.stopped)

        details = f"Stopped {gen.name}. Runtime: {runtime_hours:.2f}h. Consumed: {consumed:.2f}L."
        if factor > 1.0:
            details += f" (Weather factor: x{factor:.1f}, Temp: {temp:.1f}C)"

        await self.logs.log_action(user_id, "STOP_GEN", details)

    async def log_refuel(self, user_id: int, gen_name: str, liters: float):
        new_level = await self.repo.add_fuel(gen_name, liters)
        await self.logs.log_action(user_id, "REFUEL_GEN", f"Added {liters}L to {gen_name}. New Level: {new_level:.1f}L")

    async def correct_fuel(self, user_id: int, gen_name: str, liters: float):
        await self.repo.set_fuel_level(gen_name, liters)
        await self.logs.log_action(user_id, "CORRECT_FUEL", f"Manual correction for {gen_name}: {liters}L")

    async def update_generator_specs(self, user_id: int, name: str, capacity: float, rate: float):
        await self.repo.update_specs(name, capacity, rate)
        await self.logs.log_action(user_id, "UPDATE_SPECS", f"Updated {name}: Cap={capacity}L, Rate={rate}L/h")

    async def rename_generators_init(self):
        # One-time rename of the old names
        await self.repo.rename_generator("GEN-1", "GEN-1 (003)")
        await self.repo.rename_generator("GEN-003", "GEN-1 (003)")
        await self.repo.rename_generator("GEN-2", "GEN-2 (038)")
        await self.repo.rename_generator("GEN-038", "GEN-2 (038)")
