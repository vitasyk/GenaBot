from unittest.mock import AsyncMock, MagicMock

from aiogram.types import CallbackQuery, Message

from bot.config import config
from bot.database.models import User, UserRole
from bot.middlewares.access import ACCESS_DENIED_TEXT, AccessMiddleware


def _data(role: UserRole | None, user_id: int = 42) -> dict:
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=User(id=user_id, name="x", role=role) if role else None)
    tg_user = MagicMock(id=user_id)
    return {"user_repo": repo, "event_from_user": tg_user}


def _message(text: str) -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _callback() -> MagicMock:
    cb = MagicMock(spec=CallbackQuery)
    cb.answer = AsyncMock()
    return cb


async def test_blocked_user_callback_is_rejected():
    handler = AsyncMock()
    cb = _callback()

    await AccessMiddleware()(handler, cb, _data(UserRole.blocked))

    handler.assert_not_awaited()
    cb.answer.assert_awaited_once_with(ACCESS_DENIED_TEXT, show_alert=True)


async def test_unknown_user_message_is_rejected():
    handler = AsyncMock()
    msg = _message("⛽ Заправити")

    await AccessMiddleware()(handler, msg, _data(None))

    handler.assert_not_awaited()
    msg.answer.assert_awaited_once_with(ACCESS_DENIED_TEXT)


async def test_start_passes_for_unknown_user():
    handler = AsyncMock(return_value="ok")
    data = _data(None)

    for text in ("/start", "/menu", "/help", "/start@GenaBot payload"):
        handler.reset_mock()
        assert await AccessMiddleware()(handler, _message(text), data) == "ok"
        handler.assert_awaited_once()
    data["user_repo"].get_by_id.assert_not_awaited()


async def test_worker_and_admin_pass():
    # conftest: ADMIN_IDS=[1], ALLOWED_IDS=[2]
    for role, user_id in ((UserRole.worker, 2), (UserRole.admin, 1)):
        handler = AsyncMock(return_value="ok")
        msg = _message("⚡ Статус")
        assert await AccessMiddleware()(handler, msg, _data(role, user_id)) == "ok"
        msg.answer.assert_not_awaited()

        handler = AsyncMock(return_value="ok")
        assert await AccessMiddleware()(handler, _callback(), _data(role, user_id)) == "ok"


async def test_revoked_worker_is_denied_and_blocked_in_db(monkeypatch):
    monkeypatch.setattr(config, "RESTRICT_ACCESS", True)
    handler = AsyncMock()
    msg = _message("⚡ Статус")
    data = _data(UserRole.worker, user_id=42)  # not in ALLOWED_IDS any more

    await AccessMiddleware()(handler, msg, data)

    handler.assert_not_awaited()
    msg.answer.assert_awaited_once_with(ACCESS_DENIED_TEXT)
    user = await data["user_repo"].get_by_id(42)
    assert user.role == UserRole.blocked


async def test_public_access_lets_blocked_user_through(monkeypatch):
    monkeypatch.setattr(config, "RESTRICT_ACCESS", False)
    handler = AsyncMock(return_value="ok")
    data = _data(UserRole.blocked, user_id=42)

    assert await AccessMiddleware()(handler, _callback(), data) == "ok"
    user = await data["user_repo"].get_by_id(42)
    assert user.role == UserRole.worker


async def test_admin_always_passes(monkeypatch):
    monkeypatch.setattr(config, "RESTRICT_ACCESS", True)
    handler = AsyncMock(return_value="ok")
    data = _data(UserRole.blocked, user_id=1)

    assert await AccessMiddleware()(handler, _message("⚡ Статус"), data) == "ok"
    user = await data["user_repo"].get_by_id(1)
    assert user.role == UserRole.admin
