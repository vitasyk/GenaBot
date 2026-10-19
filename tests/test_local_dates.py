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
