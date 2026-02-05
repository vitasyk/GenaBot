import asyncio
from bot.database.main import session_maker
from bot.database.repositories.generator import GeneratorRepository
from sqlalchemy import select
from bot.database.models import Generator

async def check_db():
    async with session_maker() as session:
        stmt = select(Generator)
        result = await session.execute(stmt)
        gens = result.scalars().all()
        print("Existing Generators:")
        for g in gens:
            print(f"Name: '{g.name}', ID: {g.id}")

if __name__ == "__main__":
    asyncio.run(check_db())
