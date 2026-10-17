from aiogram.filters.callback_data import CallbackData

# gen_id in GenCallback(action="session") meaning "both / all generators"
ALL_GENERATORS_ID = 0


class GenCallback(CallbackData, prefix="gen"):
    """A generator button. action: start | standby | correct | refuel | session | sos | admin."""
    action: str
    gen_id: int


class RefuelAmountCallback(CallbackData, prefix="refuel_amt"):
    gen_id: int
    liters: int
