from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.handlers.inventory import stock_date_selector_callback
from bot.services import google_sheets
from bot.services.google_sheets import GoogleSheetsService
from bot.utils import clock


def _freeze_utc(monkeypatch, instant: datetime) -> None:
    """Freeze the container clock (UTC) at `instant` for clock helpers and google_sheets."""

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            aware = instant.replace(tzinfo=UTC)
            return aware.replace(tzinfo=None) if tz is None else aware.astimezone(tz)

    monkeypatch.setattr(clock, "datetime", FrozenDatetime)
    monkeypatch.setattr(google_sheets, "datetime", FrozenDatetime, raising=False)


@pytest.fixture
def sheets() -> GoogleSheetsService:
    return GoogleSheetsService.__new__(GoogleSheetsService)  # skip credentials loading


async def test_outage_workers_use_kyiv_date(monkeypatch, sheets):
    # UTC 2026-11-01 23:30 is already 2026-11-02 01:30 in Kyiv
    _freeze_utc(monkeypatch, datetime(2026, 11, 1, 23, 30))
    looked_up = []
    sheets.get_workers_for_time = lambda day, hour: looked_up.append(day) or []

    sheets.get_workers_for_outage(10)

    assert looked_up and set(looked_up) == {datetime(2026, 11, 2).date()}


async def test_worker_names_use_kyiv_month(monkeypatch, sheets):
    # UTC 2026-11-30 23:30 is 2026-12-01 01:30 in Kyiv: December sheet
    _freeze_utc(monkeypatch, datetime(2026, 11, 30, 23, 30))
    requested = []

    def fake_worksheet(day):
        requested.append(day)
        return MagicMock(get_all_values=MagicMock(return_value=[]))

    sheets._get_worksheet = fake_worksheet

    sheets.get_all_worker_names()

    assert requested == [datetime(2026, 12, 1).date()]


async def test_stock_today_button_uses_kyiv_date(monkeypatch):
    _freeze_utc(monkeypatch, datetime(2026, 11, 1, 23, 30))
    cb = MagicMock()
    cb.from_user.id = 1  # conftest ADMIN_IDS=[1]
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()

    await stock_date_selector_callback(cb, user_repo=MagicMock())

    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    today = markup.inline_keyboard[0][0]
    assert today.text == "Сьогодні"
    assert today.callback_data == "stock_set_date_2026-11-02"


async def test_refill_date_correction_keeps_kyiv_time():
    from bot.services.inventory import InventoryService

    # Refill logged at 22:30 UTC on 2026-11-01 = 00:30 Kyiv on 2026-11-02
    event = MagicMock(timestamp=datetime(2026, 11, 1, 22, 30))
    logs = MagicMock(get_last_action=AsyncMock(return_value=event), log_action=AsyncMock())
    repo = MagicMock(session=MagicMock(commit=AsyncMock()))
    service = InventoryService(repo, logs, MagicMock(), MagicMock(), MagicMock())

    # Admin says it actually was on 2026-11-05 (Kyiv)
    assert await service.update_last_refill_date(1, datetime(2026, 11, 5))

    # 00:30 Kyiv on 2026-11-05 is 22:30 UTC on 2026-11-04
    assert event.timestamp == datetime(2026, 11, 4, 22, 30)


def test_utc_local_round_trip():
    utc = datetime(2026, 7, 1, 21, 15)  # summer, UTC+3
    assert clock.utc_to_local(utc) == datetime(2026, 7, 2, 0, 15)
    assert clock.local_to_utc(clock.utc_to_local(utc)) == utc
