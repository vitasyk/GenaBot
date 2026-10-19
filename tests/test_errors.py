import logging
from unittest.mock import AsyncMock, MagicMock

from aiogram.types import ErrorEvent

from bot.handlers.errors import ERROR_TEXT, on_error


def _event(message=None, callback=None) -> ErrorEvent:
    update = MagicMock(update_id=10, message=message, callback_query=callback)
    return ErrorEvent.model_construct(update=update, exception=RuntimeError("boom"))


async def test_message_error_is_logged_with_user_and_answered(caplog):
    message = MagicMock(answer=AsyncMock())
    message.from_user.id = 42

    with caplog.at_level(logging.ERROR):
        assert await on_error(_event(message=message)) is True

    message.answer.assert_awaited_once_with(ERROR_TEXT)
    assert "42" in caplog.text and "boom" in caplog.text


async def test_callback_error_shows_alert():
    callback = MagicMock(answer=AsyncMock())
    callback.from_user.id = 7

    await on_error(_event(callback=callback))

    callback.answer.assert_awaited_once_with(ERROR_TEXT, show_alert=True)


async def test_failure_to_reply_does_not_raise():
    message = MagicMock(answer=AsyncMock(side_effect=RuntimeError("telegram down")))
    message.from_user.id = 42

    assert await on_error(_event(message=message)) is True


async def test_update_without_user_is_only_logged():
    assert await on_error(_event()) is True


async def test_dispatcher_routes_errors_from_other_routers():
    from datetime import datetime

    from aiogram import Bot, Dispatcher, Router
    from aiogram.methods import SendMessage
    from aiogram.types import Chat, Message, Update, User

    from bot.handlers import errors

    failing = Router()

    @failing.message()
    async def boom(message: Message) -> None:
        raise RuntimeError("boom")

    dp = Dispatcher()
    dp.include_router(failing)
    dp.include_router(errors.router)
    bot = Bot("42:TEST")
    bot.session = AsyncMock()
    update = Update(update_id=1, message=Message(
        message_id=1, date=datetime.now(), chat=Chat(id=5, type="private"),
        from_user=User(id=5, is_bot=False, first_name="u"), text="hi"))

    await dp.feed_update(bot, update)

    method = bot.session.await_args.args[1]
    assert isinstance(method, SendMessage) and method.text == errors.ERROR_TEXT
