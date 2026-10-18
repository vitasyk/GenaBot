from contextlib import asynccontextmanager
from datetime import datetime, time, date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.database.models import SessionStatus
from bot.handlers import sessions
from bot.services.session_service import SessionService

TODAY = date(2026, 10, 18)


def at(hour: int, minute: int = 0, day: date = TODAY):
    return patch("bot.services.session_service.now_local", return_value=datetime.combine(day, time(hour, minute)))


@asynccontextmanager
async def fake_session_maker():
    yield MagicMock()


def fsm() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=7, user_id=7))


def message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = 7
    msg.from_user.full_name = "Петро <О.>"
    msg.answer = AsyncMock()
    return msg


async def finish(repo_result, notes="тиск < 2"):
    """Runs finish_session with the given complete_session() result; returns (msg, services, state)."""
    state = fsm()
    await state.update_data(session_id=5, gen_fuel_data={"GEN-2 (003) WILSON": 20.0}, antigel_added=False)
    await state.set_state(sessions.SessionStates.waiting_for_notes)
    inventory = AsyncMock()
    inventory.take_fuel.return_value = 100
    generator = AsyncMock()
    generator.get_status.return_value = []
    repo = MagicMock()
    repo.complete_session = AsyncMock(return_value=repo_result)
    msg = message(notes)
    with patch.object(sessions, "session_maker", fake_session_maker), \
         patch.object(sessions, "SessionRepository", return_value=repo), \
         patch.object(sessions, "NotifierService") as notifier:
        notifier.return_value.notify_admins = AsyncMock()
        await sessions.finish_session(msg, state, MagicMock(), notes=notes,
                                      generator_service=generator, inventory_service=inventory)
    return msg, inventory, generator, state


async def test_second_completion_does_not_deduct_fuel_again():
    # Regression: two workers completing the same session deducted fuel twice
    msg, inventory, generator, state = await finish(repo_result=None)

    inventory.take_fuel.assert_not_called()
    generator.log_refuel.assert_not_called()
    assert "вже завершено" in msg.answer.call_args.args[0]
    assert await state.get_state() is None


async def test_note_with_html_is_escaped_and_state_cleared_first():
    # Regression: "<" in a note broke the reply, the state stayed, the next text completed again
    completed = SimpleNamespace(end_time=datetime(2026, 10, 18, 12, 30))
    msg, inventory, generator, state = await finish(repo_result=completed)

    inventory.take_fuel.assert_awaited_once_with(7, 20.0)
    generator.log_refuel.assert_awaited_once_with(7, "GEN-2 (003) WILSON", 20.0)
    text = msg.answer.call_args.args[0]
    assert "тиск &lt; 2" in text and "Петро &lt;О.&gt;" in text
    assert await state.get_state() is None


@pytest.fixture
def service() -> SessionService:
    service = SessionService(AsyncMock(), bot=AsyncMock())
    service.repo = MagicMock()
    service.repo.get_active_session = AsyncMock(return_value=None)
    service.repo.exists_by_start_time = AsyncMock(return_value=False)
    service.repo.update_status = AsyncMock()
    service.repo.create_session = AsyncMock(side_effect=lambda **kw: SimpleNamespace(
        id=9, worker1_id=kw["worker1_id"], worker2_id=kw["worker2_id"], worker3_id=kw["worker3_id"],
        additional_workers=kw["additional_workers"]))
    service.notifier = AsyncMock()
    service.sheets_service.get_workers_for_outage = MagicMock(return_value=[("Невідомий", ""), ("Петро", "")])

    async def by_name(name):
        return SimpleNamespace(id=555) if name == "Петро" else None
    service.user_repo = MagicMock()
    service.user_repo.get_by_sheet_name = AsyncMock(side_effect=by_name)
    service.user_repo.get_by_name = AsyncMock(return_value=None)
    return service


async def test_session_created_when_power_returns_with_correct_worker_links(service):
    service.get_outage_timeline_from_db = AsyncMock(return_value=[
        datetime.combine(TODAY, time(14)), datetime.combine(TODAY, time(15)),
    ])
    with at(16, 5):
        await service.check_power_outage()

    kwargs = service.repo.create_session.call_args.kwargs
    assert kwargs["start_time"] == datetime.combine(TODAY, time(16))
    assert kwargs["worker1_id"] == 555
    # Regression: names and ids were zipped by position, so the unknown worker got Петро's link
    admin_text = service.notifier.notify_admins.call_args.args[0]
    assert "<b>Невідомий</b>" in admin_text and "<a href='tg://user?id=555'>Петро</a>" in admin_text


async def test_overdue_session_reminds_once_and_expires(service):
    overdue = SimpleNamespace(id=3, status=SessionStatus.in_progress.value,
                              deadline=datetime.combine(TODAY, time(12)),
                              worker1_id=555, worker2_id=None, worker3_id=None, additional_workers=[])
    service.repo.get_active_session = AsyncMock(return_value=overdue)
    service.get_outage_timeline_from_db = AsyncMock(return_value=[])

    with at(12, 1):
        await service.check_power_outage()

    service.repo.update_status.assert_awaited_once_with(3, SessionStatus.expired)
    service.notifier.notify_user.assert_awaited_once()
