from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.database.models import SessionStatus
from bot.services.session_service import SessionService

TODAY = date(2026, 2, 4)
TOMORROW = date(2026, 2, 5)
# Continuous outage 23:00 today -> 02:00 tomorrow
TIMELINE = [
    datetime.combine(TODAY, time(23)),
    datetime.combine(TOMORROW, time(0)),
    datetime.combine(TOMORROW, time(1)),
]


@pytest.fixture
def service() -> SessionService:
    parser = MagicMock()
    parser.get_outage_timeline = AsyncMock(return_value=TIMELINE)
    service = SessionService(AsyncMock(), parser, bot=AsyncMock())

    service.sheets_service.get_workers_for_outage = MagicMock(return_value=[("Worker 1", "p1"), ("Worker 2", "p2")])
    service.user_repo.get_by_sheet_name = AsyncMock(return_value=SimpleNamespace(id=123))
    service.repo.get_active_session = AsyncMock(return_value=None)
    service.repo.create_session = AsyncMock(return_value=SimpleNamespace(id=7))
    service.repo.update_status = AsyncMock()
    service.notifier = AsyncMock()
    return service


def at(day: date, hour: int, minute: int = 0):
    return patch("bot.services.session_service.now_kyiv", return_value=datetime.combine(day, time(hour, minute)))


async def test_no_session_earlier_than_30_minutes_before_outage(service):
    with at(TODAY, 22, 15):
        assert await service.check_power_outage() is None
    service.repo.create_session.assert_not_called()


async def test_session_created_30_minutes_before_block_spanning_midnight(service):
    with at(TODAY, 22, 35):
        await service.check_power_outage()

    kwargs = service.repo.create_session.call_args.kwargs
    assert kwargs["deadline"] == datetime.combine(TOMORROW, time(2))
    assert kwargs["worker1_id"] == 123
    service.sheets_service.get_workers_for_outage.assert_called_once_with(outage_start_hour=23, target_date=TODAY)


async def test_active_session_past_deadline_is_closed_and_workers_notified(service):
    # Regression: SessionStatus was not imported, so this branch crashed on every run
    service.repo.get_active_session = AsyncMock(return_value=SimpleNamespace(
        id=999,
        status=SessionStatus.in_progress.value,
        start_time=datetime.combine(TODAY, time(22, 30)),
        deadline=datetime.combine(TOMORROW, time(0)),
        worker1_id=123,
        worker2_id=456,
    ))

    with at(TOMORROW, 0, 30):
        await service.check_power_outage()

    service.repo.update_status.assert_called_once_with(999, SessionStatus.completed)
    restoration_recipients = [
        call.args[0] for call in service.notifier.notify_user.call_args_list
        if "Електроенергія має з'явитися" in call.args[1]
    ]
    assert restoration_recipients == [123, 456]
