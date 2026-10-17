import pytest

from bot.config import config
from bot.services.runtime_settings import load_flags, normalize_queue, save_queue


@pytest.mark.parametrize("text, expected", [("1.1", "1.1"), (" 4,2 ", "4.2"), ("12.1", "12.1")])
def test_normalize_queue_accepts(text, expected):
    assert normalize_queue(text) == expected


@pytest.mark.parametrize("text", ["1", "1.", "a.b", "1.1.1", "", "1.12"])
def test_normalize_queue_rejects(text):
    assert normalize_queue(text) is None


async def test_chosen_queue_survives_restart(fake_redis, monkeypatch):
    monkeypatch.setattr(config, "QUEUE_NUMBER", "1.1")
    await save_queue(fake_redis, "3.2")

    monkeypatch.setattr(config, "QUEUE_NUMBER", "1.1")  # fresh process reads .env default
    await load_flags(fake_redis)

    assert config.QUEUE_NUMBER == "3.2"
