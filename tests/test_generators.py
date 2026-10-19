from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from sqlalchemy.dialects import postgresql

from bot.database.models import Generator, GenStatus, Inventory
from bot.database.repositories.generator import GeneratorRepository
from bot.database.repositories.inventory import InventoryRepository
from bot.handlers.inventory import refuel_accumulator_done
from bot.keyboards.inline_kb import GenCb, get_generator_control_kb, get_sos_kb
from bot.keyboards.main_kb import get_main_keyboard
from bot.keyboards.refuel_kb import get_refuel_kb
from bot.keyboards.session_kb import get_gen_selection_kb
from bot.services.generator import GeneratorService
from bot.states import RefuelAccumulatorStates
from bot.utils.clock import utcnow


def _gen(gen_id: int, name: str, status: GenStatus = GenStatus.stopped, **kw) -> Generator:
    return Generator(id=gen_id, name=name, status=status, is_active=True, fuel_level=20.0,
                     consumption_rate=2.0, total_hours_run=0.0, fuel_since_antigel=0.0, **kw)


def _callbacks(markup) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# --- keyboards are built from the given generators -------------------------

def test_control_kb_uses_generator_ids():
    gens = [_gen(7, "WILSON"), _gen(9, "Honda")]
    kb = get_generator_control_kb(gens)

    data = _callbacks(kb)
    assert GenCb(action="start", id=7).pack() in data
    assert GenCb(action="standby", id=9).pack() in data
    assert kb.inline_keyboard[0][0].text == "🟢 Старт WILSON"


def test_refuel_and_sos_kb_list_only_given_generators():
    gens = [_gen(3, "WILSON", GenStatus.running)]

    refuel = get_refuel_kb(gens)
    assert refuel.inline_keyboard[0][0].text == "🟢 WILSON"
    assert GenCb.unpack(refuel.inline_keyboard[0][0].callback_data) == GenCb(action="refuel", id=3)
    assert refuel.inline_keyboard[-1][0].callback_data == "refuel_close"

    sos = get_sos_kb(gens)
    assert _callbacks(sos) == [GenCb(action="sos", id=3).pack()]


def test_selection_kb_marks_selected_names():
    gens = [_gen(1, "A"), _gen(2, "B")]
    kb = get_gen_selection_kb(gens, ["B"])

    assert kb.inline_keyboard[0][0].text == "🔴 A"
    assert kb.inline_keyboard[1][0].text == "✅ 🔴 B"
    assert kb.inline_keyboard[2][0].callback_data == "gen_confirm"
    assert get_gen_selection_kb(gens, []).inline_keyboard[-1][0].callback_data != "gen_confirm"


def test_packed_callback_fits_telegram_limit():
    assert len(GenCb(action="antigel", id=2**63 - 1).pack().encode()) <= 64


def test_control_button_shown_to_workers():
    texts = {b.text for row in get_main_keyboard(is_admin=False).keyboard for b in row}
    assert "🔄 Керування" in texts
    assert "📊 Адмін-панель" not in texts


# --- enabling / disabling --------------------------------------------------

def _service(repo) -> GeneratorService:
    service = GeneratorService(repo, MagicMock(log_action=AsyncMock()), MagicMock(), MagicMock())
    service.weather = MagicMock(get_current_temperature=AsyncMock(return_value=5.0),
                                get_consumption_factor=MagicMock(return_value=1.0))
    return service


async def test_disabling_running_generator_stops_it_and_accounts_fuel():
    gen = _gen(5, "WILSON", GenStatus.running, current_run_start=utcnow() - timedelta(hours=2))
    repo = MagicMock(get_by_id=AsyncMock(return_value=gen), add_fuel=AsyncMock(return_value=16.0),
                     update_total_hours=AsyncMock(), set_status=AsyncMock())

    result = await _service(repo).set_active(user_id=1, gen_id=5, active=False)

    assert result is gen and gen.is_active is False
    repo.set_status.assert_awaited_with("WILSON", GenStatus.stopped)
    consumed = repo.add_fuel.await_args.args[1]
    assert consumed == pytest.approx(-4.0, abs=0.05)  # 2 h * 2 L/h
    assert repo.update_total_hours.await_args.args[1] == pytest.approx(2.0, abs=0.01)


async def test_disabling_standby_generator_sets_stopped():
    gen = _gen(5, "WILSON", GenStatus.standby)
    repo = MagicMock(get_by_id=AsyncMock(return_value=gen), add_fuel=AsyncMock(), set_status=AsyncMock())

    await _service(repo).set_active(user_id=1, gen_id=5, active=False)

    repo.set_status.assert_awaited_once_with("WILSON", GenStatus.stopped)
    repo.add_fuel.assert_not_awaited()
    assert gen.is_active is False


def _stop_repo(*gens, fuel_left: float = 100.0):
    return MagicMock(get_all=AsyncMock(return_value=list(gens)), add_fuel=AsyncMock(return_value=fuel_left),
                     update_total_hours=AsyncMock(), set_status=AsyncMock())


async def test_stop_reports_runtime_fuel_and_notifies_all_when_enabled():
    started = utcnow() - timedelta(hours=2, minutes=41)
    service = _service(_stop_repo(_gen(5, "WILSON <3>", GenStatus.running, current_run_start=started), fuel_left=101.3))
    service.redis = MagicMock(get=AsyncMock(return_value=None))  # notifications on by default
    service.notifier = MagicMock(notify_all=AsyncMock())

    text = await service.stop_all(user_id=1)

    assert "WILSON &lt;3&gt; зупинено" in text
    assert "2 год 41 хв" in text and "≈5.4 л" in text and "≈101.3 л" in text  # 2.68 h * 2 L/h
    service.notifier.notify_all.assert_awaited_once_with(text)


async def test_standby_report_includes_runtime_and_respects_notify_toggle():
    gen = _gen(5, "WILSON", GenStatus.running, current_run_start=utcnow() - timedelta(minutes=30))
    service = _service(_stop_repo(gen))
    service.redis = MagicMock(get=AsyncMock(return_value=b"0"))  # notifications switched off
    service.notifier = MagicMock(notify_all=AsyncMock())

    text = await service.set_standby(user_id=1, name="WILSON")

    assert "30 хв" in text and "ЧЕРГУВАННЯ" in text
    service.notifier.notify_all.assert_not_awaited()


async def test_stop_all_without_running_generator_reports_nothing():
    service = _service(_stop_repo(_gen(5, "WILSON", GenStatus.standby)))
    service.redis = MagicMock(get=AsyncMock(return_value=None))
    service.notifier = MagicMock(notify_all=AsyncMock())

    assert await service.stop_all(user_id=1) == ""
    service.notifier.notify_all.assert_not_awaited()


async def test_get_active_hides_disabled_generator():
    gen = _gen(5, "OLD")
    gen.is_active = False
    service = _service(MagicMock(get_by_id=AsyncMock(return_value=gen)))
    assert await service.get_active(5) is None


async def test_add_generator_rejects_duplicate_name():
    repo = MagicMock(get_by_name=AsyncMock(return_value=_gen(1, "WILSON")), create=AsyncMock())
    assert await _service(repo).add_generator(1, "WILSON") is None
    repo.create.assert_not_awaited()


# --- stock / fuel updates lock the row --------------------------------------

def _session_returning(obj):
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    session.execute = AsyncMock(return_value=result)
    return session


def _sql(session) -> str:
    stmt = session.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.dialect()))


async def test_inventory_update_locks_row():
    session = _session_returning(Inventory(id=1, fuel_cans=100))

    assert await InventoryRepository(session).update_stock(-20) == 80
    sql = _sql(session)
    assert "FOR UPDATE" in sql
    assert session.execute.await_args.args[0].get_execution_options()["populate_existing"] is True


async def test_generator_add_fuel_locks_row():
    session = _session_returning(_gen(1, "WILSON"))

    assert await GeneratorRepository(session).add_fuel("WILSON", 5) == 25.0
    assert "FOR UPDATE" in _sql(session)


# --- refuel failure must roll back -------------------------------------------

async def test_refuel_error_is_reraised_for_rollback():
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))
    await state.set_state(RefuelAccumulatorStates.accumulating)
    await state.update_data(gen_id=3, gen_name="WILSON", accumulated_liters=20)

    callback = MagicMock()
    callback.from_user.id = 1
    callback.answer = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    inventory_service = MagicMock(take_fuel=AsyncMock(return_value=100))
    generator_service = MagicMock(get_active=AsyncMock(return_value=_gen(3, "WILSON")),
                                  log_refuel=AsyncMock(side_effect=RuntimeError("db down")))

    with pytest.raises(RuntimeError):
        await refuel_accumulator_done(callback, state, inventory_service, generator_service)

    inventory_service.take_fuel.assert_awaited_once_with(1, 20)
    callback.message.answer.assert_awaited_once()
    callback.message.edit_text.assert_not_awaited()
