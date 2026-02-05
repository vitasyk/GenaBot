from datetime import datetime, timedelta
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.logs import LogRepository
from bot.database.models import Generator, GenStatus
from bot.generator_specs import GENERATOR_SPECS
from bot.services.weather import WeatherService

class GeneratorService:
    def __init__(self, gen_repo: GeneratorRepository, log_repo: LogRepository):
        self.repo = gen_repo
        self.logs = log_repo
        self.weather = WeatherService()

    async def get_status(self) -> list[Generator]:
        return await self.repo.get_all()

    async def start_generator(self, user_id: int, name: str):
        # Stop all others first (safety rule: only 1 running)
        all_gens = await self.repo.get_all()
        for g in all_gens:
            if g.status == GenStatus.running and g.name != name:
                await self._stop_and_calculate(g, user_id)
            # If any was standby, it should probably stop being standby if we start another?
            # Or if we start THIS one, it stops being standby.
            # If we start ANOTHER one, the standby one can remain standby (ready to pick up if this one fails?)
            # But user logic was: "One standby, or stopped, or running".
            # If started, it's RUNNING.
        
        # Start target
        await self.repo.set_status(name, GenStatus.running, datetime.utcnow())
        await self.logs.log_action(user_id, "START_GEN", f"Started {name}")

    async def set_standby(self, user_id: int, name: str):
        # Exclusive Standby: If we set X to Standby, Y must be Stopped (if it was standby)
        all_gens = await self.repo.get_all()
        
        target_gen = next((g for g in all_gens if g.name == name), None)
        if not target_gen: 
            return

        # If target is running, we must stop it first?
        if target_gen.status == GenStatus.running:
             await self._stop_and_calculate(target_gen, user_id)

        # Set target to standby
        await self.repo.set_status(name, GenStatus.standby)
        
        # Disarm others
        for g in all_gens:
            if g.name != name and g.status == GenStatus.standby:
                await self.repo.set_status(g.name, GenStatus.stopped)
                
        await self.logs.log_action(user_id, "SET_STANDBY", f"Set {name} to Standby")

    async def stop_all(self, user_id: int):
        all_gens = await self.repo.get_all()
        for g in all_gens:
            if g.status == GenStatus.running:
                await self._stop_and_calculate(g, user_id)
            elif g.status == GenStatus.standby:
                await self.repo.set_status(g.name, GenStatus.stopped)
        await self.logs.log_action(user_id, "STOP_ALL", "Stopped all generators")

    async def _stop_and_calculate(self, gen: Generator, user_id: int):
        # Calculate runtime
        if not gen.current_run_start:
            await self.repo.set_status(gen.name, GenStatus.stopped)
            return

        now = datetime.utcnow()
        if now < gen.current_run_start:
            now = gen.current_run_start
            
        runtime_hours = (now - gen.current_run_start).total_seconds() / 3600.0
        
        # Weather Factor
        temp = await self.weather.get_current_temperature()
        factor = self.weather.get_consumption_factor(temp)
        
        # Use Dynamic specs from DB * factor
        base_rate = gen.consumption_rate
        actual_rate = base_rate * factor
        consumed = runtime_hours * actual_rate
        
        await self.repo.add_fuel(gen.name, -consumed)
        
        # Track total hours
        new_total = (gen.total_hours_run or 0.0) + runtime_hours
        await self.repo.update_total_hours(gen.name, new_total)
        
        await self.repo.set_status(gen.name, GenStatus.stopped)
        
        # Log details
        details = f"Stopped {gen.name}. Runtime: {runtime_hours:.2f}h. Consumed: {consumed:.2f}L."
        if factor > 1.0:
            details += f" (Weather factor: x{factor:.1f}, Temp: {temp:.1f}C)"
            
        await self.logs.log_action(user_id, "STOP_GEN", details)

    async def log_refuel(self, user_id: int, gen_name: str, liters: float):
        new_level = await self.repo.add_fuel(gen_name, liters)
        await self.logs.log_action(user_id, "REFUEL_GEN", f"Added {liters}L to {gen_name}. New Level: {new_level:.1f}L")

    async def correct_fuel(self, user_id: int, gen_name: str, liters: float):
        new_level = await self.repo.set_fuel_level(gen_name, liters)
        await self.logs.log_action(user_id, "CORRECT_FUEL", f"Manual correction for {gen_name}: {liters}L")

    async def update_generator_specs(self, user_id: int, name: str, capacity: float, rate: float):
        await self.repo.update_specs(name, capacity, rate)
        await self.logs.log_action(user_id, "UPDATE_SPECS", f"Updated {name}: Cap={capacity}L, Rate={rate}L/h")

    async def rename_generators_init(self):
        # One-time rename if needed
        # We handle old names too just in case they were already "GEN-003" etc
        await self.repo.rename_generator("GEN-1", "GEN-1 (003)")
        await self.repo.rename_generator("GEN-003", "GEN-1 (003)")
        await self.repo.rename_generator("GEN-2", "GEN-2 (038)")
        await self.repo.rename_generator("GEN-038", "GEN-2 (038)")

    async def get_remaining_runtime(self, gen_name: str) -> float:
        """Returns hours left based on current fuel and consumption rate (weather adjusted)."""
        gen = await self.repo.get_by_name(gen_name)
        if not gen or gen.consumption_rate <= 0:
            return 0.0
            
        # Adjust for current weather
        temp = await self.weather.get_current_temperature()
        factor = self.weather.get_consumption_factor(temp)
        adjusted_rate = gen.consumption_rate * factor
        
        return gen.fuel_level / adjusted_rate if adjusted_rate > 0 else 0.0
