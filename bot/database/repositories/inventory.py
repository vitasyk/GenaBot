from sqlalchemy import select, update
from bot.database.repositories.base import BaseRepository
from bot.database.models import Inventory

class InventoryRepository(BaseRepository[Inventory]):
    def __init__(self, session):
        super().__init__(session, Inventory)

    async def get_stock(self) -> int:
        stmt = select(Inventory).limit(1)
        result = await self.session.execute(stmt)
        inventory = result.scalar_one_or_none()
        if not inventory:
            # Fallback if init.sql wasn't run perfectly or table is empty
            inventory = Inventory(fuel_cans=0)
            self.session.add(inventory)
            await self.session.flush()
        return inventory.fuel_cans

    async def update_stock(self, change: int) -> int:
        """
        Updates stock by `change`. Can be positive (add) or negative (remove).
        Returns new stock level.
        """
        # We assume there is only one row in inventory for simplicity as per TZ
        stmt = select(Inventory).limit(1)
        result = await self.session.execute(stmt)
        inventory = result.scalar_one_or_none()
        
        if not inventory:
            inventory = Inventory(fuel_cans=0)
            self.session.add(inventory)
        
        inventory.fuel_cans += change
        if inventory.fuel_cans < 0:
            inventory.fuel_cans = 0
            
        return inventory.fuel_cans
