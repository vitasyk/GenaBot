from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from bot.services.schedule_parser import ScheduleParser, format_hours, parse_hours_input
from bot.services.schedule_recognizer import (
    RecognizedSchedule,
    ScheduleRecognitionError,
    ScheduleRecognizer,
)

TODAY = date(2026, 10, 18)
TOMORROW = date(2026, 10, 19)


@pytest.mark.parametrize("text, expected", [
    ("14-18, 22-24", [14, 15, 16, 17, 22, 23]),
    ("14 – 16", [14, 15]),
    ("9", [9]),
    ("08:00-10:00;20", [8, 9, 20]),
    ("0", []),
    ("немає", []),
])
def test_parse_hours_input(text, expected):
    assert parse_hours_input(text) == expected


@pytest.mark.parametrize("text", ["25", "18-14", "abc", "14-", ""])
def test_parse_hours_input_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_hours_input(text)


def test_format_hours_groups_consecutive_hours():
    assert format_hours([14, 15, 16, 22]) == "14:00–17:00, 22:00–23:00"
    assert format_hours([]) == "відключень немає"


@pytest.fixture
def parser(fake_redis) -> ScheduleParser:
    recognizer = MagicMock()
    recognizer.recognize = AsyncMock(return_value=[10, 11])
    parser = ScheduleParser(recognizer, fake_redis)
    parser._fetch_available_schedules = AsyncMock(return_value=[(TODAY, b"today-png"), (TOMORROW, b"tomorrow-png")])
    return parser


def frozen_today():
    return patch("bot.services.schedule_parser.now_kyiv", return_value=datetime.combine(TODAY, time(12)))


async def test_manual_hours_override_ai_for_that_day(parser):
    await parser.set_manual_hours(TODAY, "1.1", [20, 21])
    await parser.set_manual_hours(TOMORROW, "2.1", [5])  # another queue must not leak in

    with frozen_today():
        hours = await parser.get_hours_by_date("1.1")

    assert hours == {TODAY: [20, 21], TOMORROW: [10, 11]}
    parser.recognizer.recognize.assert_called_once_with(b"tomorrow-png", "1.1")


async def test_both_days_manual_skips_site_and_ai(parser):
    await parser.set_manual_hours(TODAY, "1.1", [])
    await parser.set_manual_hours(TOMORROW, "1.1", [3])

    with frozen_today():
        timeline = await parser.get_outage_timeline("1.1")

    assert timeline == [datetime.combine(TOMORROW, time(3))]
    parser._fetch_available_schedules.assert_not_called()


async def test_recognition_is_cached_by_image(parser):
    with frozen_today():
        await parser.get_hours_by_date("1.1")
        await parser.get_hours_by_date("1.1")
    assert parser.recognizer.recognize.call_count == 2  # one per image, not per check


async def test_failed_recognition_is_not_cached(parser):
    parser.recognizer.recognize = AsyncMock(side_effect=ScheduleRecognitionError("down"))
    with frozen_today():
        assert await parser.get_hours_by_date("1.1") == {TODAY: [], TOMORROW: []}
        await parser.get_hours_by_date("1.1")
    assert parser.recognizer.recognize.call_count == 4


def _response(parsed, stop_reason="end_turn"):
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason, _request_id="req_test")


async def test_recognizer_returns_sorted_valid_hours():
    client = MagicMock()
    client.messages.parse = AsyncMock(return_value=_response(
        RecognizedSchedule(queue_found=True, outage_hours=[18, 3, 3, 24, -1])
    ))
    hours = await ScheduleRecognizer(client, "claude-haiku-5-5").recognize(b"png", "1.1")

    assert hours == [3, 18]
    kwargs = client.messages.parse.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5"
    assert kwargs["output_format"] is RecognizedSchedule


@pytest.mark.parametrize("response", [
    _response(RecognizedSchedule(queue_found=False, outage_hours=[])),
    _response(None, stop_reason="refusal"),
    _response(None, stop_reason="max_tokens"),
])
async def test_recognizer_raises_when_answer_unusable(response):
    client = MagicMock()
    client.messages.parse = AsyncMock(return_value=response)
    with pytest.raises(ScheduleRecognitionError):
        await ScheduleRecognizer(client, "claude-haiku-5-5").recognize(b"png", "1.1")


async def test_recognizer_wraps_connection_errors():
    client = MagicMock()
    client.messages.parse = AsyncMock(side_effect=anthropic.APIConnectionError(request=MagicMock()))
    with pytest.raises(ScheduleRecognitionError):
        await ScheduleRecognizer(client, "claude-haiku-5-5").recognize(b"png", "1.1")
