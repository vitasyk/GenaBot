import asyncio
from bot.database.repositories.user import UserRepository
from bot.database.main import session_maker
from bot.database.models import User

async def list_users():
    async with session_maker() as session:
        repo = UserRepository(session)
        users = await repo.get_all(include_blocked=True)
        print("ID | Name | Sheet Name | Role")
        print("-" * 40)
        for u in users:
            print(f"{u.id} | {u.name} | {u.sheet_name} | {u.role}")

if __name__ == "__main__":
    asyncio.run(list_users())
