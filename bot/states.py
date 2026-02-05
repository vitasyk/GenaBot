from aiogram.fsm.state import State, StatesGroup

class GenStates(StatesGroup):
    waiting_for_fuel_amount = State()
    waiting_for_tank_capacity = State()
    waiting_for_consumption_rate = State()

class InventoryStates(StatesGroup):
    waiting_for_stock_amount = State()

class SessionStates(StatesGroup):
    waiting_for_generator = State()
    waiting_for_liters = State()
    waiting_for_notes = State()

class AdminStates(StatesGroup):
    waiting_for_check_interval = State()
    waiting_for_sheet_name = State()
