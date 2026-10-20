from aiogram.fsm.state import State, StatesGroup


class GenStates(StatesGroup):
    waiting_for_fuel_amount = State()
    waiting_for_tank_capacity = State()
    waiting_for_consumption_rate = State()

class InventoryStates(StatesGroup):
    waiting_for_stock_amount = State()

class RefuelAccumulatorStates(StatesGroup):
    accumulating = State()

class SessionStates(StatesGroup):
    selecting_generators = State()
    waiting_for_liters = State()
    waiting_for_antigel = State()
    waiting_for_notes = State()

class AdminStates(StatesGroup):
    waiting_for_check_interval = State()
    waiting_for_sheet_name = State()
    waiting_for_gen_name = State()
    waiting_for_gen_instructions = State()
    waiting_for_gen_media = State()
    waiting_for_gen_hours = State()

class ScheduleStates(StatesGroup):
    """States for manual schedule entry"""
    waiting_for_date = State()
    waiting_for_periods = State()
    confirming = State()
    waiting_for_download_confirm = State()
    waiting_for_screenshot = State()
    waiting_for_queue = State()
    waiting_for_address = State()
    waiting_for_queue_streets = State()

class SlackStates(StatesGroup):
    """States for Slack configuration"""
    waiting_for_threshold = State()
    waiting_for_message = State()
