from bot.database.repositories.inventory import InventoryRepository
from bot.database.repositories.logs import LogRepository
from bot.database.repositories.user import UserRepository
from bot.config import config
from aiogram import Bot

class InventoryService:
    def __init__(self, inventory_repo: InventoryRepository, log_repo: LogRepository, user_repo: UserRepository, bot: Bot):
        self.repo = inventory_repo
        self.logs = log_repo
        self.users = user_repo
        self.bot = bot

    async def check_stock(self) -> int:
        """Returns stock in LITERS"""
        return await self.repo.get_stock()

    async def take_fuel(self, user_id: int, liters: int) -> int:
        new_amount = await self.repo.update_stock(-liters)
        await self.logs.log_action(user_id, "TAKE_FUEL", f"Taken: {liters}L. Remaining: {new_amount}L")
        
        # Check for critical alert (e.g. less than 2 cans = 40L)
        if new_amount < 40:
             await self._alert_admins(f"⚠️ <b>CRITICAL FUEL ALERT!</b>\nRemaining: {new_amount}L ({new_amount/20:.1f} cans)")
             
        return new_amount

    async def take_can(self, user_id: int) -> int:
        """Legacy helper for 'Take 1 Can' (Other/Loss)"""
        return await self.take_fuel(user_id, 20)

    async def add_cans(self, user_id: int, cans: int) -> int:
        liters = cans * 20
        new_amount = await self.repo.update_stock(liters)
        await self.logs.log_action(user_id, "ADD_FUEL", f"Added: {cans} cans ({liters}L). Total: {new_amount}L")
        return new_amount

    async def _alert_admins(self, text: str):
        from bot.services.notifier import NotifierService
        notifier = NotifierService(self.bot)
        await notifier.notify_all(text)

    async def get_detailed_stats(self):
        from datetime import datetime, timedelta
        
        # 1. Current Stock
        stock_liters = await self.repo.get_stock()
        stock_cans = stock_liters / 20.0
        
        # 2. Last Refill
        last_refillevent = await self.logs.get_last_action("ADD_FUEL")
        last_refill_date = last_refillevent.timestamp if last_refillevent else None
        
        # 3. Consumption in last 7 days
        days = 7
        since = datetime.utcnow() - timedelta(days=days)
        refuel_events = await self.logs.get_actions_since("TAKE_FUEL", since)
        
        total_consumed = 0
        for event in refuel_events:
            # Parse detail string "Taken: 20L..."
            # Simpler: We should have stored liters in a separate column or structured detail
            # But regex or split works for now. 
            try:
                # "Taken: 20L. Remaining: ..."
                part = event.details.split("Taken: ")[1].split("L")[0]
                total_consumed += float(part)
            except:
                pass
                
        avg_daily = total_consumed / days if days > 0 else 0
        avg_hourly = avg_daily / 24.0
        hours_left = (stock_liters / avg_hourly) if avg_hourly > 0.001 else 999
        
        return {
            "stock_liters": stock_liters,
            "stock_cans": stock_cans,
            "last_refill_date": last_refill_date,
            "avg_daily_consumption": avg_daily,
            "avg_hourly_consumption": avg_hourly,
            "hours_left": hours_left
        }
