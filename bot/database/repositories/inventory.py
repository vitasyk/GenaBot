from sqlalchemy import select

from bot.database.repositories.base import BaseRepository
from bot.database.models import Inventory


class InventoryRepository(BaseRepository[Inventory]):
    """Single-row stock table. `fuel_cans` historically holds LITERS, not cans."""

    def __init__(self, session):
        super().__init__(session, Inventory)

    async def _get_row(self, for_update: bool = False) -> Inventory:
        # populate_existing: a row already in the session is refreshed, not served stale
        stmt = select(Inventory).order_by(Inventory.id).limit(1).execution_options(populate_existing=True)
        if for_update:
            stmt = stmt.with_for_update()
        inventory = (await self.session.execute(stmt)).scalar_one_or_none()
        if not inventory:
            inventory = Inventory(fuel_cans=0)
            self.session.add(inventory)
            await self.session.flush()
        return inventory

    async def get_stock(self) -> int:
        return (await self._get_row()).fuel_cans

    async def update_stock(self, change: int) -> int:
        """Changes stock by `change` liters under a row lock (concurrent taps don't lose updates).
        Never goes below zero. Returns the new stock."""
        inventory = await self._get_row(for_update=True)
        inventory.fuel_cans = max(inventory.fuel_cans + change, 0)
        return inventory.fuel_cans
