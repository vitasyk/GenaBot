from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from bot.services.hoe_schedule import _period_hours, parse_hoe_page, sync_queue_schedule

# Real page saved on 24.11.2026: base schedules for 24 and 25.11 plus two "additional hours" updates for 24.11
PAGE = (Path(__file__).parent / "fixtures" / "hoe_page_2026-11-24.html").read_text(encoding="utf-8")
TODAY = date(2026, 11, 24)


def test_real_page_base_schedules_and_additional_hours():
    s = parse_hoe_page(PAGE, TODAY)

    assert set(s) == {date(2026, 11, 24), date(2026, 11, 25)}  # "оновлено 23:20, 23.11.2026" is not a target day
    assert s[date(2026, 11, 25)]["2.1"] == {9, 10, 11, 16, 17, 18}
    # base 12:00-17:00 + additional 20:00-22:00
    assert s[date(2026, 11, 24)]["2.1"] == {12, 13, 14, 15, 16, 20, 21}
    assert {22, 23} <= s[date(2026, 11, 24)]["4.2"]  # "22:00-00:00" runs to midnight
    assert 0 in s[date(2026, 11, 24)]["6.2"]
    assert len(s[date(2026, 11, 25)]) == 12


def test_newer_base_post_replaces_older_one_for_the_same_day():
    old = "<p>За розпорядженням НЕК «Укренерго» 25.11.2026 р. ...</p><p>Підчерга 2.1 – 09:00-12:00.</p>"
    new = "<p>За розпорядженням НЕК «Укренерго» 25.11.2026 р. ...</p><p>Підчерга 2.1 – 14:00-15:00.</p>"
    assert parse_hoe_page(f"{new}<hr />{old}", TODAY)[date(2026, 11, 25)]["2.1"] == {14}


def test_day_month_date_rolls_over_new_year():
    page = "<p>НЕК «Укренерго» оновлено графік на 2 січня</p><p>Додаткові години</p><p>Підчерга 2.1 - 10:00-11:00.</p>"
    assert date(2027, 1, 2) in parse_hoe_page(page, date(2026, 12, 31))


def test_half_hours_widen_to_whole_hours():
    assert _period_hours("06:30-09:30") == {6, 7, 8, 9}


def _sync_deps():
    repo = MagicMock(clear_all_for_date=AsyncMock(), create_entry=AsyncMock())
    repo.session.commit = AsyncMock()
    return repo, MagicMock(notify_all=AsyncMock(return_value=1))


async def test_sync_announces_new_day_once_then_only_changes(fake_redis):
    repo, notifier = _sync_deps()
    day = date(2026, 11, 25)

    changed = await sync_queue_schedule({day: {"2.1": {9, 10, 16}}}, "2.1", TODAY, fake_redis, repo, notifier)
    assert changed == [day]
    repo.clear_all_for_date.assert_awaited_once_with(day, "2.1")
    assert [c.args for c in repo.create_entry.await_args_list] == [(day, "2.1", 9, 11), (day, "2.1", 16, 17)]
    assert "Графік на 25.11" in notifier.notify_all.await_args.args[0]

    # Same hours on the next check: silent
    assert await sync_queue_schedule({day: {"2.1": {9, 10, 16}}}, "2.1", TODAY, fake_redis, repo, notifier) == []
    assert notifier.notify_all.await_count == 1

    # HOE added hours: saved and announced as a change
    await sync_queue_schedule({day: {"2.1": {9, 10, 16, 20}}}, "2.1", TODAY, fake_redis, repo, notifier)
    msg = notifier.notify_all.await_args.args[0]
    assert "змінено" in msg and "➕ Додано:\n• 20:00 - 21:00" in msg


async def test_undelivered_announcement_is_retried_on_next_check(fake_redis):
    repo, notifier = _sync_deps()
    notifier.notify_all.return_value = 0  # Telegram unreachable
    schedules = {TODAY: {"2.1": {9}}}

    await sync_queue_schedule(schedules, "2.1", TODAY, fake_redis, repo, notifier)
    notifier.notify_all.return_value = 1
    await sync_queue_schedule(schedules, "2.1", TODAY, fake_redis, repo, notifier)

    assert notifier.notify_all.await_count == 2
    assert await sync_queue_schedule(schedules, "2.1", TODAY, fake_redis, repo, notifier) == []


async def test_sync_ignores_past_days_and_other_queues(fake_redis):
    repo, notifier = _sync_deps()
    schedules = {date(2026, 11, 23): {"2.1": {1}}, TODAY: {"1.1": {5}}}

    changed = await sync_queue_schedule(schedules, "2.1", TODAY, fake_redis, repo, notifier)

    assert changed == [TODAY]  # today is announced with no outages for 2.1
    repo.create_entry.assert_not_awaited()
    assert "відключень немає" in notifier.notify_all.await_args.args[0]


async def test_hoe_button_shows_text_schedule_for_selected_queue(monkeypatch):
    from bot.config import config
    from bot.handlers.schedule import recognition

    monkeypatch.setattr(config, "QUEUE_NUMBER", "2.1")
    monkeypatch.setattr(recognition, "now_local", lambda: MagicMock(date=lambda: TODAY))
    parser = MagicMock(fetch_page=AsyncMock(return_value=PAGE), get_schedules_data=AsyncMock())
    monkeypatch.setattr(recognition, "parser", parser)
    callback = MagicMock(data="hoe_tomorrow", answer=AsyncMock())
    callback.message = MagicMock(edit_text=AsyncMock(), answer_photo=AsyncMock())

    await recognition.process_hoe_download_callback(callback, MagicMock())

    text = callback.message.edit_text.await_args.args[0]
    assert "25.11" in text and "09:00 - 12:00" in text and "16:00 - 19:00" in text
    parser.get_schedules_data.assert_not_awaited()
