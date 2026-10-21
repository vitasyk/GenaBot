from datetime import date

from bot.services.schedule_parser import ScheduleParser


def test_cached_schedule_is_only_returned_for_its_own_date(monkeypatch, tmp_path):
    monkeypatch.setattr(ScheduleParser, "CACHE_DIR", str(tmp_path))
    parser = ScheduleParser()

    parser._save_to_cache(b"feb-image", date(2026, 2, 11))

    assert parser.get_cached_schedule(date(2026, 2, 11)) == b"feb-image"
    # A stale image must never be shown as another day's schedule
    assert parser.get_cached_schedule(date(2026, 10, 19)) is None


async def test_hoe_button_never_shows_another_days_cached_image(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from bot.handlers.schedule import recognition

    monkeypatch.setattr(ScheduleParser, "CACHE_DIR", str(tmp_path))
    # What prod images shipped: February pictures in the old undated slots
    (tmp_path / "schedule_today.png").write_bytes(b"feb-image")
    (tmp_path / "schedule_tomorrow.png").write_bytes(b"feb-image")
    parser = ScheduleParser()
    monkeypatch.setattr(recognition, "parser", parser)
    monkeypatch.setattr(parser, "get_schedules_data", AsyncMock(return_value=[]))  # HOE has no images today

    callback = MagicMock(data="hoe_today", answer=AsyncMock())
    callback.message = MagicMock(edit_text=AsyncMock(), delete=AsyncMock(), answer_photo=AsyncMock())

    await recognition.process_hoe_download_callback(callback, MagicMock())

    callback.message.answer_photo.assert_not_called()


def _hoe_callback():
    from unittest.mock import AsyncMock, MagicMock
    callback = MagicMock(data="hoe_today", answer=AsyncMock())
    callback.message = MagicMock(edit_text=AsyncMock(), delete=AsyncMock(), answer_photo=AsyncMock())
    return callback


async def test_no_published_schedule_is_not_reported_as_failure(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from bot.handlers.schedule import recognition
    from bot.utils.clock import now_local

    monkeypatch.setattr(ScheduleParser, "CACHE_DIR", str(tmp_path))
    parser = ScheduleParser()
    parser._save_to_cache(b"old-image", now_local().date())  # downloaded earlier today
    monkeypatch.setattr(recognition, "parser", parser)
    monkeypatch.setattr(parser, "get_schedules_data", AsyncMock(return_value=[]))  # page loaded, no images
    callback = _hoe_callback()

    await recognition.process_hoe_download_callback(callback, MagicMock())

    callback.message.answer_photo.assert_not_called()
    text = callback.message.edit_text.await_args.args[0]
    assert "немає опублікованого графіка" in text and "Не вдалося" not in text


async def test_hoe_unreachable_falls_back_to_cached_image(monkeypatch, tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from bot.handlers.schedule import recognition
    from bot.utils.clock import now_local

    monkeypatch.setattr(ScheduleParser, "CACHE_DIR", str(tmp_path))
    parser = ScheduleParser()
    parser._save_to_cache(b"today-image", now_local().date())
    monkeypatch.setattr(recognition, "parser", parser)
    monkeypatch.setattr(parser, "get_schedules_data", AsyncMock(return_value=None))  # site down
    callback = _hoe_callback()

    await recognition.process_hoe_download_callback(callback, MagicMock())

    callback.message.answer_photo.assert_awaited_once()
    assert "Не вдалося" in callback.message.answer_photo.await_args.kwargs["caption"]
