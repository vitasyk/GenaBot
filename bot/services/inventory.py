from datetime import datetime
from bot.database.repositories.inventory import InventoryRepository
from bot.database.repositories.logs import LogRepository
from bot.database.repositories.user import UserRepository
from bot.services.slack import SlackService
from bot.config import config
from aiogram import Bot

class InventoryService:
    def __init__(self, inventory_repo: InventoryRepository, log_repo: LogRepository, user_repo: UserRepository, bot: Bot, slack_service: SlackService):
        self.repo = inventory_repo
        self.logs = log_repo
        self.users = user_repo
        self.bot = bot
        self.slack = slack_service

    async def check_stock(self) -> int:
        """Returns stock in LITERS"""
        return await self.repo.get_stock()

    async def take_fuel(self, user_id: int, liters: int) -> int:
        new_amount = await self.repo.update_stock(-liters)
        await self.logs.log_action(user_id, "TAKE_FUEL", f"Taken: {liters}L. Remaining: {new_amount}L")
        
        # Check for critical alert (e.g. less than 2 cans = 40L)
        # 1. Telegram Alert
        if new_amount < 40:
             await self._alert_admins(f"⚠️ <b>CRITICAL FUEL ALERT!</b>\nRemaining: {new_amount}L ({new_amount/20.0:.1f} cans)")
        
        # 2. Slack Alert (Configurable)
        current_cans = new_amount / 20.0
        if current_cans < config.FUEL_THRESHOLD_CANS:
             await self.slack.send_message(
                 f"⛽ *Low Fuel Alert*\n"
                 f"Current stock: *{current_cans:.2f}* cans ({new_amount}L)\n"
                 f"Threshold: {config.FUEL_THRESHOLD_CANS} cans"
             )
             
        return new_amount

    async def take_can(self, user_id: int) -> int:
        """Legacy helper for 'Take 1 Can' (Other/Loss)"""
        return await self.take_fuel(user_id, 20)

    async def add_cans(self, user_id: int, cans: int) -> int:
        liters = cans * 20
        new_amount = await self.repo.update_stock(liters)
        await self.logs.log_action(user_id, "ADD_FUEL", f"Added: {cans} cans ({liters}L). Total: {new_amount}L")
        return new_amount

    async def update_last_refill_date(self, user_id: int, new_date: datetime) -> bool:
        """Update the timestamp of the very last ADD_FUEL event"""
        last_event = await self.logs.get_last_action("ADD_FUEL")
        if not last_event:
            return False
            
        # Update timestamp (keeping original time part if we want, or just setting to new_date at noon/current)
        # To be simple and robust, let's just use the date part and keep time as is or set to current.
        # User usually wants to say "it was yesterday".
        
        # Merge date from new_date and time from current last_event
        from datetime import datetime
        updated_ts = datetime.combine(new_date.date(), last_event.timestamp.time())
        
        last_event.timestamp = updated_ts
        await self.repo.session.commit()
        
        await self.logs.log_action(user_id, "CORRECT_REFILL_DATE", f"Updated last refill to {updated_ts.strftime('%d.%m.%Y %H:%M')}")
        return True

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
            "total_weekly_consumption": total_consumed,
            "avg_daily_consumption": avg_daily,
            "avg_hourly_consumption": avg_hourly,
            "hours_left": hours_left
        }

    async def get_current_week_usage(self) -> float:
        """
        Calculates total fuel consumption for the current week (Monday 00:00 to now).
        """
        from datetime import datetime, timedelta
        
        now = datetime.utcnow()
        # Find last Monday
        days_since_monday = now.weekday() # Mon=0, Sun=6
        last_monday = now - timedelta(days=days_since_monday)
        last_monday_midnight = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        
        refuel_events = await self.logs.get_actions_since("TAKE_FUEL", last_monday_midnight)
        
        total_consumed = 0.0
        for event in refuel_events:
            try:
                # "Taken: 20L. Remaining: ..."
                part = event.details.split("Taken: ")[1].split("L")[0]
                total_consumed += float(part)
            except:
                pass
        
        return total_consumed

    async def get_consumption_history(self, limit: int = 5) -> list[dict]:
        """
        Returns last N consumption events.
        """
        from bot.database.models import LogEvent
        from sqlalchemy import select, desc
        
        # We need to access repo session directly or through logs repo if it exposes query
        # LogRepository usually has basic methods. let's check logs repo or use session directly
        # Assuming we can use self.logs.session
        
        stmt = (
            select(LogEvent)
            .filter_by(action="TAKE_FUEL")
            .order_by(desc(LogEvent.timestamp))
            .limit(limit)
        )
        
        result = await self.logs.session.execute(stmt)
        events = result.scalars().all()
        
        history = []
        for e in events:
            # Get user name if possible
            user = await self.users.get_by_id(e.user_id)
            user_name = user.name if user else f"ID {e.user_id}"
            
            # Parse amount
            amount = "?"
            try:
                amount = e.details.split("Taken: ")[1].split("L")[0]
            except:
                pass
                
            history.append({
                "date": e.timestamp,
                "user": user_name,
                "amount": amount
            })
            
        return history
