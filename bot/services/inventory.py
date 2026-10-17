import logging
from datetime import timedelta

from aiogram import Bot

from bot.database.repositories.inventory import InventoryRepository
from bot.database.repositories.logs import LogRepository
from bot.database.repositories.user import UserRepository
from bot.generator_specs import LITERS_PER_CAN
from bot.services.notifier import NotifierService
from bot.utils.clock import now_kyiv

LOW_STOCK_LITERS = 2 * LITERS_PER_CAN
STATS_DAYS = 7
NO_CONSUMPTION_HOURS_LEFT = 999


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

        if new_amount < LOW_STOCK_LITERS:
            await NotifierService(self.bot).notify_all(
                f"⚠️ <b>CRITICAL FUEL ALERT!</b>\nRemaining: {new_amount}L ({new_amount / LITERS_PER_CAN:.1f} cans)"
            )

        return new_amount

    async def add_cans(self, user_id: int, cans: int) -> int:
        liters = cans * LITERS_PER_CAN
        new_amount = await self.repo.update_stock(liters)
        await self.logs.log_action(user_id, "ADD_FUEL", f"Added: {cans} cans ({liters}L). Total: {new_amount}L")
        return new_amount

    async def get_detailed_stats(self) -> dict:
        stock_liters = await self.repo.get_stock()

        last_refill_event = await self.logs.get_last_action("ADD_FUEL")
        last_refill_date = last_refill_event.timestamp if last_refill_event else None

        since = now_kyiv() - timedelta(days=STATS_DAYS)
        total_consumed = 0.0
        for event in await self.logs.get_actions_since("TAKE_FUEL", since):
            # details look like "Taken: 20L. Remaining: ..."
            try:
                total_consumed += float(event.details.split("Taken: ")[1].split("L")[0])
            except (AttributeError, IndexError, ValueError):
                logging.warning(f"Unparsable TAKE_FUEL log id={event.id}: {event.details!r}")

        avg_daily = total_consumed / STATS_DAYS
        avg_hourly = avg_daily / 24.0
        hours_left = (stock_liters / avg_hourly) if avg_hourly > 0.001 else NO_CONSUMPTION_HOURS_LEFT

        return {
            "stock_liters": stock_liters,
            "stock_cans": stock_liters / LITERS_PER_CAN,
            "last_refill_date": last_refill_date,
            "avg_daily_consumption": avg_daily,
            "avg_hourly_consumption": avg_hourly,
            "hours_left": hours_left
        }
