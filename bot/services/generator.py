from datetime import datetime, timedelta
import logging
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.logs import LogRepository
from bot.database.models import Generator, GenStatus
from bot.generator_specs import GENERATOR_SPECS
from bot.services.weather import WeatherService
from bot.services.notifier import NotifierService
from redis.asyncio import Redis

class GeneratorService:
    def __init__(self, gen_repo: GeneratorRepository, log_repo: LogRepository, notifier: NotifierService, redis: Redis):
        self.repo = gen_repo
        self.logs = log_repo
        self.weather = WeatherService()
        self.notifier = notifier
        self.redis = redis
        self.NOTIFY_KEY = "settings:notify_gen_start"

    async def get_status(self) -> list[Generator]:
        return await self.repo.get_all()

    async def get_notify_start_status(self) -> bool:
        """Check if global start notifications are enabled"""
        val = await self.redis.get(self.NOTIFY_KEY)
        return val != b"0" # Default is True (not 0)

    async def toggle_notify_start(self) -> bool:
        """Toggle notification setting. Returns new state."""
        current = await self.get_notify_start_status()
        new_state = not current
        await self.redis.set(self.NOTIFY_KEY, "1" if new_state else "0")
        return new_state

    async def start_generator(self, user_id: int, name: str):
        # Stop all others first (safety rule: only 1 running)
        all_gens = await self.repo.get_all()
        for g in all_gens:
            if g.status == GenStatus.running and g.name != name:
                await self._stop_and_calculate(g, user_id)
        
        # Start target
        await self.repo.set_status(name, GenStatus.running, datetime.utcnow())
        await self.logs.log_action(user_id, "START_GEN", f"Started {name}")

        # Global Notification
        if await self.get_notify_start_status():
            msg = f"🟢 <b>УВАГА! Запущено генератор {name}</b>\n" \
                  f"⚡ Живлення відновлено від генератора."
            await self.notifier.notify_all(msg)

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

        # Global Notification for Standby
        if await self.get_notify_start_status():
            msg = f"🟡 <b>Генератор {name} переведено в ЧЕРГУВАННЯ</b>\n" \
                  f"🏁 Роботу завершено, очікуємо наступного запуску."
            await self.notifier.notify_all(msg)

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
        # 1. Update fuel level
        new_level = await self.repo.add_fuel(gen_name, liters)
        
        # 2. Update Anti-Gel counter
        gen = await self.repo.get_by_name(gen_name)
        if gen:
            gen.fuel_since_antigel += liters
            
        await self.logs.log_action(user_id, "REFUEL_GEN", f"Added {liters}L to {gen_name}. New Level: {new_level:.1f}L (Accumulated since Anti-Gel: {gen.fuel_since_antigel:.1f}L)")

    async def reset_antigel(self, user_id: int, gen_name: str):
        await self.repo.reset_antigel_counter(gen_name)
        await self.logs.log_action(user_id, "ANTIGEL_ADDED", f"Recorded Anti-Gel addition for {gen_name}")

    async def correct_fuel(self, user_id: int, gen_name: str, liters: float):
        new_level = await self.repo.set_fuel_level(gen_name, liters)
        await self.logs.log_action(user_id, "CORRECT_FUEL", f"Manual correction for {gen_name}: {liters}L")

    async def update_generator_specs(self, user_id: int, name: str, capacity: float, rate: float):
        await self.repo.update_specs(name, capacity, rate)
        await self.logs.log_action(user_id, "UPDATE_SPECS", f"Updated {name}: Cap={capacity}L, Rate={rate}L/h")

    async def rename_generators_init(self):
        # Migration to standardized names: GEN-1 (003) and GEN-2 (036) WILSON
        await self.repo.rename_generator("GEN-1", "GEN-1 (003)")
        await self.repo.rename_generator("GEN-003", "GEN-1 (003)")
        
        await self.repo.rename_generator("GEN-2", "GEN-2 (036) WILSON") 
        await self.repo.rename_generator("GEN-038", "GEN-2 (036) WILSON")
        await self.repo.rename_generator("GEN-2 (038)", "GEN-2 (036) WILSON")

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

    async def get_warming_recommendation(self, gen_name: str) -> str | None:
        """Calculate if generator needs warming based on downtime and temperature."""
        gen = await self.repo.get_by_name(gen_name)
        if not gen or gen.status != GenStatus.stopped:
            return None
        
        if not gen.last_stop_at:
            return None
            
        downtime_hours = (datetime.utcnow() - gen.last_stop_at).total_seconds() / 3600.0
        temp = await self.weather.get_current_temperature()
        
        # Logic:
        # -15 and below -> 6h
        # -10 to -14 -> 10h
        
        threshold = None
        if temp <= -15:
            threshold = 6.0
        elif temp <= -10:
            threshold = 10.0
            
        if threshold and downtime_hours >= threshold:
            return f"⚠️ <b>Потрібен прогрів: 5-7 хв</b> (Генератор не працював {downtime_hours:.1f} год)"
        
        return None

    async def check_warming_notifications(self):
        """Proactive check for generators that need warming (run by background job)"""
        gens = await self.repo.get_all()
        for g in gens:
            rec = await self.get_warming_recommendation(g.name)
            if rec:
                # Notify admins/workers about the need to warm up
                msg = f"❄️ <b>Нагадування про прогрів!</b>\n\n" \
                      f"Генератор <b>{g.name}</b> замерзає.\n" \
                      f"{rec}\n\n" \
                      f"Будь ласка, запустіть його на кілька хвилин."
                
                # Use Redis to ensure we don't spam.
                # Threshold is already calculated in get_warming_recommendation indirectly, 
                # but we can deduce it from the temperature again for expiry duration.
                temp = await self.weather.get_current_temperature()
                threshold_h = 10.0 if temp > -15 else 6.0
                
                notify_key = f"notify:warming:{g.name}"
                if not await self.redis.get(notify_key):
                    await self.notifier.notify_all(msg)
                    # Set expiry to match the threshold so we don't notify again until the next cycle
                    await self.redis.set(notify_key, "1", ex=int(threshold_h * 3600))
                    logging.info(f"Sent warming notification for {g.name} (Threshold: {threshold_h}h)")
