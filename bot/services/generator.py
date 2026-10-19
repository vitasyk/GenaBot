import html
import logging

from redis.asyncio import Redis

from bot.database.models import Generator, GenStatus
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.logs import LogRepository
from bot.services.antigel import AntigelService
from bot.services.notifier import NotifierService
from bot.services.weather import WeatherService
from bot.utils.clock import utcnow

logger = logging.getLogger(__name__)


class GeneratorService:
    def __init__(self, gen_repo: GeneratorRepository, log_repo: LogRepository, notifier: NotifierService, redis: Redis):
        self.repo = gen_repo
        self.logs = log_repo
        self.weather = WeatherService()
        self.antigel = AntigelService(self.weather, redis)
        self.notifier = notifier
        self.redis = redis
        self.NOTIFY_KEY = "settings:notify_gen_start"

    async def get_status(self) -> list[Generator]:
        """Active generators: the ones shown in every menu."""
        return await self.repo.get_all(active_only=True)

    async def get_all(self) -> list[Generator]:
        """All generators, including disabled ones (admin list)."""
        return await self.repo.get_all()

    async def get_by_id(self, gen_id: int) -> Generator | None:
        return await self.repo.get_by_id(gen_id)

    async def get_active(self, gen_id: int) -> Generator | None:
        """Generator by id, or None if it is missing or disabled."""
        gen = await self.repo.get_by_id(gen_id)
        return gen if gen and gen.is_active else None

    async def add_generator(self, user_id: int, name: str) -> Generator | None:
        """Create an active generator with default specs. None if the name is taken."""
        if await self.repo.get_by_name(name):
            return None
        gen = await self.repo.create(name)
        await self.logs.log_action(user_id, "ADD_GEN", f"Added generator {name}")
        return gen

    async def set_active(self, user_id: int, gen_id: int, active: bool) -> Generator | None:
        """Enable/disable a generator. A running or standby one is stopped first,
        so its runtime and fuel are accounted."""
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
            await self.logs.log_action(user_id, "UPDATE_SOS", f"Updated SOS instructions for {gen.name}")
        return gen

    async def add_instruction_media(self, user_id: int, gen_id: int, kind: str, file_id: str) -> Generator | None:
        """Attach a photo/document (Telegram file_id) to the SOS instructions."""
        gen = await self.repo.get_by_id(gen_id)
        if gen:
            # Assign a new list: in-place changes of a JSON column are not tracked by SQLAlchemy
            gen.instructions_media = [*(gen.instructions_media or []), {"type": kind, "file_id": file_id}]
            await self.logs.log_action(user_id, "UPDATE_SOS", f"Attached {kind} to SOS of {gen.name}")
        return gen

    async def clear_instruction_media(self, user_id: int, gen_id: int) -> Generator | None:
        gen = await self.repo.get_by_id(gen_id)
        if gen:
            gen.instructions_media = None
            await self.logs.log_action(user_id, "UPDATE_SOS", f"Removed SOS attachments of {gen.name}")
        return gen

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
        reports = []
        for g in all_gens:
            if g.status == GenStatus.running and g.name != name:
                reports.append(await self._stop_and_calculate(g, user_id))

        # Start target
        await self.repo.set_status(name, GenStatus.running, utcnow())
        await self.logs.log_action(user_id, "START_GEN", f"Started {name}")

        # Global Notification
        if await self.get_notify_start_status():
            msg = f"🟢 <b>УВАГА! Запущено генератор {html.escape(name)}</b>\n" \
                  f"⚡ Живлення відновлено від генератора."
            await self.notifier.notify_all("\n\n".join([r for r in reports if r] + [msg]))

    async def set_standby(self, user_id: int, name: str) -> str:
        """Returns the message shown to the user: the run report (if it was running) + standby line."""
        # Exclusive Standby: If we set X to Standby, Y must be Stopped (if it was standby)
        all_gens = await self.repo.get_all()

        target_gen = next((g for g in all_gens if g.name == name), None)
        if not target_gen:
            return ""

        report = None
        if target_gen.status == GenStatus.running:
            report = await self._stop_and_calculate(target_gen, user_id)

        # Set target to standby
        await self.repo.set_status(name, GenStatus.standby)
        
        # Disarm others
        for g in all_gens:
            if g.name != name and g.status == GenStatus.standby:
                await self.repo.set_status(g.name, GenStatus.stopped)
                
        await self.logs.log_action(user_id, "SET_STANDBY", f"Set {name} to Standby")

        msg = f"🟡 <b>Генератор {html.escape(name)} переведено в ЧЕРГУВАННЯ</b>\n" \
              f"🏁 Роботу завершено, очікуємо наступного запуску."
        if report:
            msg = f"{report}\n\n{msg}"
        # Global Notification for Standby
        if await self.get_notify_start_status():
            await self.notifier.notify_all(msg)
        return msg

    async def stop_all(self, user_id: int) -> str:
        """Returns the run reports of the generators that were running ("" if none was)."""
        all_gens = await self.repo.get_all()
        reports = []
        for g in all_gens:
            if g.status == GenStatus.running:
                reports.append(await self._stop_and_calculate(g, user_id))
            elif g.status == GenStatus.standby:
                await self.repo.set_status(g.name, GenStatus.stopped)
        await self.logs.log_action(user_id, "STOP_ALL", "Stopped all generators")

        text = "\n\n".join(r for r in reports if r)
        if text and await self.get_notify_start_status():
            await self.notifier.notify_all(text)
        return text

    async def _stop_and_calculate(self, gen: Generator, user_id: int) -> str | None:
        """Stops a running generator, accounts runtime and fuel. Returns the run report (HTML)."""
        if not gen.current_run_start:
            await self.repo.set_status(gen.name, GenStatus.stopped)
            return None

        now = utcnow()
        now = max(now, gen.current_run_start)
            
        runtime_hours = (now - gen.current_run_start).total_seconds() / 3600.0
        
        # Weather Factor
        temp = await self.weather.get_current_temperature()
        factor = self.weather.get_consumption_factor(temp)
        
        # Use Dynamic specs from DB * factor
        base_rate = gen.consumption_rate
        actual_rate = base_rate * factor
        consumed = runtime_hours * actual_rate
        
        level_before = gen.fuel_level or 0.0
        fuel_left = await self.repo.add_fuel(gen.name, -consumed)
        # The mix burns evenly: untreated litres shrink in proportion, the additive share stays
        if level_before > 0 and gen.fuel_since_antigel:
            gen.fuel_since_antigel *= max(fuel_left, 0.0) / level_before

        # Track total hours
        new_total = (gen.total_hours_run or 0.0) + runtime_hours
        await self.repo.update_total_hours(gen.name, new_total)
        
        await self.repo.set_status(gen.name, GenStatus.stopped)
        
        # Log details
        details = f"Stopped {gen.name}. Runtime: {runtime_hours:.2f}h. Consumed: {consumed:.2f}L."
        if factor > 1.0:
            temp_log = f"{temp:.1f}C" if temp is not None else "unknown"
            details += f" (Weather factor: x{factor:.1f}, Temp: {temp_log})"

        await self.logs.log_action(user_id, "STOP_GEN", details)

        hours, minutes = divmod(int(runtime_hours * 60), 60)
        duration = f"{hours} год {minutes} хв" if hours else f"{minutes} хв"
        temp_text = f"мороз {temp:.0f}°C" if temp is not None else "температура н/д"
        frost = f" ({temp_text}: +{(factor - 1) * 100:.0f}%)" if factor > 1.0 else ""
        return (f"🛑 <b>{html.escape(gen.name)} зупинено</b>\n"
                f"⏱ Працював: {duration}\n"
                f"⛽ Витрачено: ≈{consumed:.1f} л{frost}\n"
                f"🛢 У баку: ≈{max(fuel_left, 0.0):.1f} л")

    async def log_refuel(self, user_id: int, gen_name: str, liters: float):
        # 1. Update fuel level (row is locked inside add_fuel)
        new_level = await self.repo.add_fuel(gen_name, liters)
        
        # 2. Update Anti-Gel counter
        gen = await self.repo.get_by_name(gen_name)
        if not gen:
            raise ValueError(f"Generator {gen_name!r} not found")
        gen.fuel_since_antigel += liters
            
        await self.logs.log_action(user_id, "REFUEL_GEN", f"Added {liters}L to {gen_name}. New Level: {new_level:.1f}L (Accumulated since Anti-Gel: {gen.fuel_since_antigel:.1f}L)")

    async def reset_antigel(self, user_id: int, gen_name: str):
        await self.repo.reset_antigel_counter(gen_name)
        await self.logs.log_action(user_id, "ANTIGEL_ADDED", f"Recorded Anti-Gel addition for {gen_name}")

    async def correct_fuel(self, user_id: int, gen_name: str, liters: float):
        await self.repo.set_fuel_level(gen_name, liters)
        gen = await self.repo.get_by_name(gen_name)
        if gen and gen.fuel_since_antigel and gen.fuel_since_antigel > liters:
            gen.fuel_since_antigel = max(liters, 0.0)  # can't have more untreated fuel than fuel
        await self.logs.log_action(user_id, "CORRECT_FUEL", f"Manual correction for {gen_name}: {liters}L")

    async def update_generator_specs(self, user_id: int, name: str, capacity: float, rate: float):
        await self.repo.update_specs(name, capacity, rate)
        await self.logs.log_action(user_id, "UPDATE_SPECS", f"Updated {name}: Cap={capacity}L, Rate={rate}L/h")

    async def get_warming_recommendation(self, gen_name: str) -> str | None:
        """Calculate if generator needs warming based on downtime and temperature."""
        gen = await self.repo.get_by_name(gen_name)
        if not gen or gen.status != GenStatus.stopped:
            return None
        
        if not gen.last_stop_at:
            return None
            
        downtime_hours = (utcnow() - gen.last_stop_at).total_seconds() / 3600.0
        temp = await self.weather.get_current_temperature()
        if temp is None:
            return None

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
        gens = await self.repo.get_all(active_only=True)
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
                threshold_h = 6.0 if temp is not None and temp <= -15 else 10.0
                
                notify_key = f"notify:warming:{g.name}"
                if not await self.redis.get(notify_key):
                    await self.notifier.notify_all(msg)
                    # Set expiry to match the threshold so we don't notify again until the next cycle
                    await self.redis.set(notify_key, "1", ex=int(threshold_h * 3600))
                    logger.info(f"Sent warming notification for {g.name} (Threshold: {threshold_h}h)")
