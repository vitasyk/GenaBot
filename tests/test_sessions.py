from datetime import date, datetime, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.database.models import GenStatus, SessionStatus
from bot.handlers import outage, sessions
from bot.keyboards.inline_kb import GenCb
from bot.keyboards.session_kb import OutageAnswerCb, get_outage_warning_kb
from bot.services.session_service import SessionService, record_outage_answer

TODAY = date(2026, 10, 18)


def at(hour: int, minute: int = 0, day: date = TODAY):
    return patch("bot.services.session_service.now_local", return_value=datetime.combine(day, time(hour, minute)))


def fsm() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=7, user_id=7))


def message(text: str) -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = 7
    msg.from_user.full_name = "Петро <О.>"
    msg.answer = AsyncMock()
    return msg


async def finish(repo_result, notes="тиск < 2", take_fuel_error=None, reply_error=None):
    """Runs finish_session with the given complete_session() result; returns (msg, services, state, repo)."""
    state = fsm()
    await state.update_data(session_id=5, gen_fuel_data={"GEN-2 (003) WILSON": 20.0}, antigel_added=False)
    await state.set_state(sessions.SessionStates.waiting_for_notes)
    inventory = AsyncMock()
    inventory.take_fuel.return_value = 100
    inventory.take_fuel.side_effect = take_fuel_error
    generator = AsyncMock()
    generator.get_status.return_value = []
    repo = MagicMock()
    repo.complete_session = AsyncMock(return_value=repo_result)
    repo.session.commit = AsyncMock()
    repo.session.rollback = AsyncMock()
    msg = message(notes)
    if reply_error:
        async def reply_fails(*args, **kwargs):  # records whether the refuel was committed before the reply
            raise reply_error(repo.session.commit.await_count)
        msg.answer.side_effect = reply_fails
    with patch.object(sessions, "NotifierService") as notifier:
        notifier.return_value.notify_admins = AsyncMock()
        await sessions.finish_session(msg, state, MagicMock(), notes=notes, session_repo=repo,
                                      generator_service=generator, inventory_service=inventory)
    return msg, inventory, generator, state, repo


COMPLETED = SimpleNamespace(end_time=datetime(2026, 10, 18, 12, 30))


async def test_second_completion_does_not_deduct_fuel_again():
    # Regression: two workers completing the same session deducted fuel twice
    msg, inventory, generator, state, _ = await finish(repo_result=None)

    inventory.take_fuel.assert_not_called()
    generator.log_refuel.assert_not_called()
    assert "вже завершено" in msg.answer.call_args.args[0]
    assert await state.get_state() is None


async def test_note_with_html_is_escaped_and_state_cleared():
    # Regression: "<" in a note broke the reply, the state stayed, the next text completed again
    msg, inventory, generator, state, _ = await finish(repo_result=COMPLETED)

    inventory.take_fuel.assert_awaited_once_with(7, 20.0)
    generator.log_refuel.assert_awaited_once_with(7, "GEN-2 (003) WILSON", 20.0)
    text = msg.answer.call_args.args[0]
    assert "тиск &lt; 2" in text and "Петро &lt;О.&gt;" in text
    assert await state.get_state() is None


async def test_failed_reply_does_not_lose_the_refuel():
    # Regression: the reply failed after the fuel writes, the middleware rolled them back,
    # the session (committed separately) stayed completed with no fuel deducted
    class TelegramDown(Exception):
        def __init__(self, commits_before_reply: int):
            self.commits_before_reply = commits_before_reply

    with pytest.raises(TelegramDown) as err:
        await finish(repo_result=COMPLETED, reply_error=TelegramDown)
    assert err.value.commits_before_reply == 1


async def test_fuel_write_failure_rolls_back_and_lets_the_worker_retry():
    # Regression: a failed take_fuel was only logged, the user saw success and the session stayed completed
    msg, _, _, state, repo = await finish(repo_result=COMPLETED, take_fuel_error=RuntimeError("db"))

    repo.session.rollback.assert_awaited_once()
    repo.session.commit.assert_not_called()
    assert "зміни скасовано" in msg.answer.call_args.args[0]
    assert await state.get_state() == sessions.SessionStates.waiting_for_notes.state


async def enter_liters(needed: bool):
    state = fsm()
    await state.set_state(sessions.SessionStates.waiting_for_liters)
    await state.update_data(selected_gens=["WILSON"], current_gen_index=0, gen_fuel_data={})
    advice = SimpleNamespace(needed=needed, dose_ml=60)
    generator = MagicMock(get_status=AsyncMock(return_value=[SimpleNamespace(name="WILSON")]))
    generator.antigel.advise_for = AsyncMock(return_value=advice)
    msg = message("40")
    await sessions.liters_input(msg, state, generator)
    return msg, state


async def test_antigel_question_only_when_additive_is_needed():
    msg, state = await enter_liters(needed=False)
    assert await state.get_state() == sessions.SessionStates.waiting_for_notes.state
    assert (await state.get_data())["antigel_added"] is None
    assert "Антигель" not in msg.answer.call_args.args[0]

    msg, state = await enter_liters(needed=True)
    assert await state.get_state() == sessions.SessionStates.waiting_for_antigel.state
    assert "≈60 мл" in msg.answer.call_args.args[0]


@pytest.fixture
def service() -> SessionService:
    service = SessionService(AsyncMock(), bot=AsyncMock())
    service.repo = MagicMock()
    service.repo.get_overdue_sessions = AsyncMock(return_value=[])
    service.repo.exists_by_start_time = AsyncMock(return_value=False)
    service.repo.update_status = AsyncMock()
    service.repo.create_session = AsyncMock(side_effect=lambda **kw: SimpleNamespace(
        id=9, worker1_id=kw["worker1_id"], worker2_id=kw["worker2_id"], worker3_id=kw["worker3_id"],
        additional_workers=kw["additional_workers"]))
    service.notifier = AsyncMock()
    service.gen_repo = MagicMock(get_all=AsyncMock(return_value=[]))
    service.antigel = MagicMock(advise_for=AsyncMock(return_value=SimpleNamespace(needed=False)))
    service.sheets_service.get_workers_for_outage = MagicMock(return_value=[("Невідомий", ""), ("Петро", "")])

    async def by_name(name):
        return SimpleNamespace(id=555) if name == "Петро" else None
    service.user_repo = MagicMock()
    service.user_repo.get_by_sheet_name = AsyncMock(side_effect=by_name)
    service.user_repo.get_by_name = AsyncMock(return_value=None)
    return service


async def test_session_created_when_power_returns_with_correct_worker_links(service):
    service.get_outage_timeline_from_db = AsyncMock(return_value=[
        datetime.combine(TODAY, time(14)), datetime.combine(TODAY, time(15)),
    ])
    with at(16, 5):
        await service.check_power_outage()

    kwargs = service.repo.create_session.call_args.kwargs
    assert kwargs["start_time"] == datetime.combine(TODAY, time(16))
    assert kwargs["worker1_id"] == 555
    # Regression: names and ids were zipped by position, so the unknown worker got Петро's link
    admin_text = service.notifier.notify_admins.call_args.args[0]
    assert "<b>Невідомий</b>" in admin_text and "<a href='tg://user?id=555'>Петро</a>" in admin_text


def outage_from_16_to_19(service, gen_status=GenStatus.stopped, redis=None):
    service.get_outage_timeline_from_db = AsyncMock(return_value=[
        datetime.combine(TODAY, time(h)) for h in (16, 17, 18)
    ])
    service.gen_repo = MagicMock()
    service.gen_repo.get_all = AsyncMock(return_value=[SimpleNamespace(id=2, name="WILSON", status=gen_status)])
    service.redis = redis


async def test_outage_start_warning_after_grace_with_start_button(service, fake_redis):
    outage_from_16_to_19(service, redis=fake_redis)

    with at(16, 4):
        await service.check_power_outage()
    service.notifier.notify_user.assert_not_called()  # too early: give the power 5 minutes

    with at(16, 5):
        await service.check_power_outage()
    with at(16, 6):
        await service.check_power_outage()  # next scheduler tick must not repeat it

    service.notifier.notify_user.assert_awaited_once()
    user_id, text = service.notifier.notify_user.call_args.args
    kb = service.notifier.notify_user.call_args.kwargs["reply_markup"]
    assert user_id == 555 and "16:00" in text
    assert kb.inline_keyboard[0][0].callback_data == GenCb(action="start", id=2).pack()
    yes, no = kb.inline_keyboard[-1]
    assert yes.text == "✅ Так, світла немає" and no.text == "❌ Ні, світло є"
    assert no.callback_data == OutageAnswerCb(power=True, block=2026101816).pack()
    assert len(no.callback_data.encode()) <= 64
    service.notifier.notify_admins.assert_awaited_once()
    service.repo.create_session.assert_not_called()


@pytest.mark.parametrize("answers, created", [
    ([], True),                       # no answer: session as before
    ([True], False),                  # "Ні, світло є"
    ([False], True),                  # "Так, світла немає"
    ([True, False], True),            # last answer wins
])
async def test_outage_answer_decides_refuel_session(service, fake_redis, answers, created):
    outage_from_16_to_19(service, redis=fake_redis)
    for power_on in answers:
        await record_outage_answer(fake_redis, 2026101816, power_on)
    with at(19, 0):
        await service.check_power_outage()
    assert service.repo.create_session.called is created


async def test_outage_answer_handler_edits_message(fake_redis):
    gens = [SimpleNamespace(id=2, name="WILSON")]
    for power_on in (True, False):
        cb = MagicMock(from_user=SimpleNamespace(full_name="Петро <x>"), answer=AsyncMock())
        cb.message = MagicMock(html_text="⚠️ warn", edit_text=AsyncMock(),
                               reply_markup=get_outage_warning_kb(gens, 2026101816))
        await outage.outage_answer(cb, OutageAnswerCb(power=power_on, block=2026101816), fake_redis)

        text, kb = cb.message.edit_text.call_args.args[0], cb.message.edit_text.call_args.kwargs["reply_markup"]
        assert "Петро &lt;x&gt;" in text
        if power_on:
            assert "світло є" in text and kb is None
            assert await fake_redis.get("outage:power_on:2026101816")
        else:
            assert "Світла немає" in text
            assert [r[0].callback_data for r in kb.inline_keyboard] == [GenCb(action="start", id=2).pack()]
            assert await fake_redis.get("outage:power_on:2026101816") is None


async def test_no_outage_warning_when_generator_already_running(service, fake_redis):
    outage_from_16_to_19(service, gen_status=GenStatus.running, redis=fake_redis)
    with at(16, 5):
        await service.check_power_outage()
    service.notifier.notify_user.assert_not_called()
    service.notifier.notify_admins.assert_not_called()


async def test_no_outage_warning_without_redis_or_after_power_returns(service, fake_redis):
    outage_from_16_to_19(service, redis=None)  # admin "force check" has no redis: refuel logic only
    with at(16, 5):
        await service.check_power_outage()
    service.notifier.notify_user.assert_not_called()

    outage_from_16_to_19(service, redis=fake_redis)
    with at(19, 0):
        await service.check_power_outage()
    assert "Світло з'явилося" in service.notifier.notify_user.call_args.args[1]  # only the refuel one


async def test_refuel_message_carries_antigel_dose_when_needed(service):
    outage_from_16_to_19(service)
    service.antigel.advise_for = AsyncMock(return_value=SimpleNamespace(
        needed=True, dose_ml=90, untreated_l=90.0, forecast_min=-3.0, too_cold_now=False))
    with at(19, 0):
        await service.check_power_outage()
    text = service.notifier.notify_user.call_args.args[1]
    assert "Потрібна присадка в WILSON" in text and "≈90 мл" in text


async def test_overdue_session_reminds_once_and_expires(service):
    overdue = SimpleNamespace(id=3, status=SessionStatus.in_progress.value,
                              deadline=datetime.combine(TODAY, time(12)),
                              worker1_id=555, worker2_id=None, worker3_id=None, additional_workers=[])
    service.repo.get_overdue_sessions = AsyncMock(return_value=[overdue])
    service.get_outage_timeline_from_db = AsyncMock(return_value=[])

    with at(12, 1):
        await service.check_power_outage()

    service.repo.update_status.assert_awaited_once_with(3, SessionStatus.expired)
    service.notifier.notify_user.assert_awaited_once()
