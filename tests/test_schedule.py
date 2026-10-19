from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import config
from bot.handlers.schedule import _common, manual, queue
from bot.scheduler import restore_runtime_settings
from bot.services.schedule_recognizer import RecognizedSchedule, ScheduleRecognitionError, ScheduleRecognizer
from bot.states import ScheduleStates
from bot.utils import clock


def fsm() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))


def message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = 1  # admin in conftest
    msg.answer = AsyncMock()
    return msg


def test_now_local_is_kyiv_time_not_container_utc():
    # Regression: in Docker datetime.now() is UTC, so "today" was yesterday between 00:00 and 03:00 Kyiv
    utc_late_evening = datetime(2026, 10, 18, 22, 30, tzinfo=timezone.utc)
    with patch.object(clock, "datetime") as fake_dt:
        fake_dt.now.side_effect = lambda tz: utc_late_evening.astimezone(tz)
        assert clock.now_local() == datetime(2026, 10, 19, 1, 30)


def test_hours_to_ranges():
    assert _common._hours_to_ranges([15, 14, 22, 23, 3]) == [(3, 4), (14, 16), (22, 24)]
    assert _common._hours_to_ranges([]) == []


async def test_date_after_photo_goes_straight_to_confirmation():
    # Regression: recognized periods were dropped and the admin had to type them again
    state = fsm()
    await state.update_data(periods=[[14, 18]])
    await state.set_state(ScheduleStates.waiting_for_date)

    await manual.process_date_input(message("Завтра"), state, user_repo=MagicMock())

    assert await state.get_state() == ScheduleStates.confirming.state
    data = await state.get_data()
    assert data["periods"] == [(14, 18)] or data["periods"] == [[14, 18]]


async def test_manual_date_without_photo_asks_for_periods():
    state = fsm()
    await state.set_state(ScheduleStates.waiting_for_date)
    await manual.process_date_input(message("05.02"), state, user_repo=MagicMock())
    assert await state.get_state() == ScheduleStates.waiting_for_periods.state


@pytest.mark.parametrize("text", ["18-19:30", "18:20-19", "18<b>-19"])
async def test_periods_with_minutes_are_rejected_not_truncated(text):
    # Regression: "18-19:30" was silently read as 18-19
    state = fsm()
    await state.set_state(ScheduleStates.waiting_for_periods)
    msg = message(text)
    await manual.process_periods_input(msg, state, schedule_repo=MagicMock(), user_repo=MagicMock())
    reply = msg.answer.call_args.args[0]
    assert "Лише цілі години" in reply and "<b>" not in reply
    assert await state.get_state() == ScheduleStates.waiting_for_periods.state


async def test_queue_input_is_validated_and_saved(fake_redis, monkeypatch):
    monkeypatch.setattr(config, "QUEUE_NUMBER", "1.1")
    state = fsm()
    state.storage.redis = fake_redis  # MemoryStorage has no redis; the handler uses RedisStorage.redis
    await state.set_state(ScheduleStates.waiting_for_queue)

    bad = message("abc")
    await queue.queue_input(bad, state)
    assert config.QUEUE_NUMBER == "1.1"

    await queue.queue_input(message("4,2"), state)
    assert config.QUEUE_NUMBER == "4.2"

    monkeypatch.setattr(config, "QUEUE_NUMBER", "1.1")  # restart: .env default, then Redis wins
    await restore_runtime_settings(fake_redis)
    assert config.QUEUE_NUMBER == "4.2"


def _response(parsed, stop_reason="end_turn"):
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason, _request_id="req_test")


async def test_recognizer_returns_sorted_valid_hours(monkeypatch):
    client = MagicMock()
    client.messages.parse = AsyncMock(return_value=_response(
        RecognizedSchedule(queue_found=True, outage_hours=[18, 3, 3, 24, -1])))
    monkeypatch.setattr(config, "SCHEDULE_AI_MODEL", "claude-haiku-5-5")

    assert await ScheduleRecognizer(client).recognize(b"\x89PNG...", "1.1") == [3, 18]
    kwargs = client.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["output_format"] is RecognizedSchedule
    assert kwargs["messages"][0]["content"][0]["source"]["media_type"] == "image/png"


@pytest.mark.parametrize("response", [
    _response(RecognizedSchedule(queue_found=False, outage_hours=[])),
    _response(None, stop_reason="refusal"),
    _response(None, stop_reason="max_tokens"),
])
async def test_recognizer_raises_when_answer_unusable(response):
    client = MagicMock()
    client.messages.parse = AsyncMock(return_value=response)
    with pytest.raises(ScheduleRecognitionError):
        await ScheduleRecognizer(client).recognize(b"jpeg", "1.1")


async def test_recognizer_wraps_connection_errors():
    client = MagicMock()
    client.messages.parse = AsyncMock(side_effect=anthropic.APIConnectionError(request=MagicMock()))
    with pytest.raises(ScheduleRecognitionError):
        await ScheduleRecognizer(client).recognize(b"jpeg", "1.1")


async def test_recognizer_without_api_key_fails_clearly(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    with pytest.raises(ScheduleRecognitionError, match="ANTHROPIC_API_KEY"):
        await ScheduleRecognizer().recognize(b"jpeg", "1.1")
