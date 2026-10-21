from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.database.models import Generator, GenStatus
from bot.handlers.admin import generators as g
from bot.handlers.common import refuel_instructions_text
from bot.scheduler import notify_maintenance_due
from bot.services.maintenance import add_months, format_status, maintenance_status
from bot.states import AdminStates

TODAY = date(2026, 10, 21)


def _gen(total=100.0, at=50.0, done=datetime(2026, 5, 1, 9, 0), hours=200.0, months=12, gen_id=1):
    return SimpleNamespace(id=gen_id, name=f"GEN-{gen_id}", total_hours_run=total, maint_hours_at=at,
                           last_maintenance=done, maint_interval_hours=hours, maint_interval_months=months)


def test_add_months_clamps_to_month_end():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_ok_counts_hours_since_service_and_date():
    st = maintenance_status(_gen(), TODAY)
    assert st.level == "ok" and st.hours_left == 150.0 and st.due_date == date(2027, 5, 1)
    assert format_status(st) == "🔧 <b>До ТО:</b> 150 год або до 01.05.2027"


def test_due_by_hours_or_by_time_whichever_first():
    assert maintenance_status(_gen(total=251.0), TODAY).level == "due"
    st = maintenance_status(_gen(done=datetime(2025, 10, 1)), TODAY)  # 1 year standing idle
    assert st.level == "due" and "минув термін" in format_status(st)


def test_soon_by_hours_or_days():
    assert maintenance_status(_gen(total=235.0), TODAY).level == "soon"  # 15 h of 200 left
    assert maintenance_status(_gen(done=datetime(2025, 11, 1)), TODAY).level == "soon"  # 11 days left


def test_not_set_and_hours_corrected_below_service_mark():
    assert maintenance_status(_gen(done=None), TODAY) is None
    assert format_status(None) == "🔧 <b>ТО:</b> не задано"
    assert maintenance_status(_gen(total=10.0), TODAY).hours_left == 200.0


# --- alerts -------------------------------------------------------------------

async def test_alerts_once_per_level_and_restarts_after_service(fake_redis, monkeypatch):
    import bot.scheduler as sched
    monkeypatch.setattr(sched, "now_local", lambda: datetime(2026, 10, 21, 12, 0))
    notifier = AsyncMock()

    await notify_maintenance_due([_gen(total=100.0)], fake_redis, notifier)
    notifier.notify_all.assert_not_awaited()

    await notify_maintenance_due([_gen(total=235.0)], fake_redis, notifier)
    await notify_maintenance_due([_gen(total=240.0)], fake_redis, notifier)
    assert notifier.notify_all.await_count == 1 and "скоро" in notifier.notify_all.await_args.args[0]

    await notify_maintenance_due([_gen(total=251.0)], fake_redis, notifier)
    assert notifier.notify_all.await_count == 2 and "ПОТРІБНЕ" in notifier.notify_all.await_args.args[0]

    # service recorded: counter starts over, no alert while ok
    await notify_maintenance_due([_gen(total=251.0, at=251.0, done=datetime(2026, 10, 21))], fake_redis, notifier)
    assert notifier.notify_all.await_count == 2


async def test_generator_without_service_record_is_ignored(fake_redis):
    notifier = AsyncMock()
    await notify_maintenance_due([_gen(total=9999.0, done=None)], fake_redis, notifier)
    notifier.notify_all.assert_not_awaited()


# --- admin input -------------------------------------------------------------

def _state():
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))


def _msg(text):
    m = MagicMock(text=text, answer=AsyncMock())
    m.from_user.id = 1
    return m


def _admin_gen(total=120.0):
    return Generator(id=5, name="WILSON", status=GenStatus.stopped, is_active=True, fuel_level=20.0,
                     tank_capacity=170.0, consumption_rate=2.0, total_hours_run=total, instructions=None,
                     instructions_media=None, maint_interval_hours=200.0, maint_interval_months=12)


async def test_maintenance_date_then_hours_is_saved(monkeypatch):
    monkeypatch.setattr(g, "now_local", lambda: datetime(2026, 10, 21, 12, 0))
    gen = _admin_gen()
    svc = MagicMock(get_by_id=AsyncMock(return_value=gen), set_maintenance=AsyncMock(return_value=gen))
    state = _state()
    await state.set_state(AdminStates.waiting_for_maint_date)
    await state.update_data(gen_id=5)

    for bad in ("32.13.2026", "22.10.2026"):  # invalid, in the future
        await g.admin_maint_date_input(_msg(bad), state, svc)
    assert await state.get_state() == AdminStates.waiting_for_maint_date.state

    await g.admin_maint_date_input(_msg("01.05.2026"), state, svc)
    assert await state.get_state() == AdminStates.waiting_for_maint_hours.state

    await g.admin_maint_hours_input(_msg("500"), state, svc)  # more than the generator has run
    svc.set_maintenance.assert_not_awaited()
    await g.admin_maint_hours_input(_msg("50,5"), state, svc)
    _, gen_id, done_at, hours = svc.set_maintenance.await_args.args
    assert gen_id == 5 and hours == 50.5 and done_at == datetime(2026, 5, 1, 9, 0)  # noon Kyiv (UTC+3) in UTC
    assert await state.get_state() is None


async def test_maintenance_current_hours_button_uses_generator_total():
    gen = _admin_gen(total=77.0)
    svc = MagicMock(get_by_id=AsyncMock(return_value=gen), set_maintenance=AsyncMock(return_value=gen))
    state = _state()
    await state.set_state(AdminStates.waiting_for_maint_hours)
    await state.update_data(gen_id=5, maint_done_at=datetime(2026, 10, 21, 9).isoformat())
    cb = MagicMock(answer=AsyncMock())
    cb.from_user.id = 1
    cb.message.edit_text = AsyncMock()

    await g.admin_maint_current_hours(cb, state, svc)

    assert svc.set_maintenance.await_args.args[3] == 77.0


async def test_maintenance_interval_input():
    gen = _admin_gen()
    svc = MagicMock(set_maintenance_interval=AsyncMock(return_value=gen))
    state = _state()
    await state.set_state(AdminStates.waiting_for_maint_interval)
    await state.update_data(gen_id=5)

    for bad in ("200", "abc 12", "0 12", "200 40"):
        await g.admin_maint_interval_input(_msg(bad), state, svc)
    svc.set_maintenance_interval.assert_not_awaited()

    await g.admin_maint_interval_input(_msg("250 6"), state, svc)
    svc.set_maintenance_interval.assert_awaited_once_with(1, 5, 250.0, 6)


def test_refuel_instructions_dose_for_full_tank():
    text = refuel_instructions_text()
    assert "+5 °C" in text and "1 мл на 1 л" in text and "170 л — 170 мл" in text
