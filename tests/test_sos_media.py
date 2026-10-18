from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InputMediaDocument, InputMediaPhoto

from bot.handlers import admin, common
from bot.services.generator import GeneratorService
from bot.states import AdminStates


async def media_state(gen_id: int = 2) -> FSMContext:
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))
    await state.set_state(AdminStates.waiting_for_gen_media)
    await state.update_data(gen_id=gen_id)
    return state


def message(text=None, photo=None, document=None) -> MagicMock:
    msg = MagicMock()
    msg.text, msg.photo, msg.document = text, photo, document
    msg.from_user.id = 1
    msg.answer = AsyncMock()
    return msg


@pytest.fixture
def service():
    gen = SimpleNamespace(id=2, name="WILSON", instructions_media=None)
    svc = MagicMock()
    svc.get_by_id = AsyncMock(return_value=gen)

    async def add(user_id, gen_id, kind, file_id):
        gen.instructions_media = [*(gen.instructions_media or []), {"type": kind, "file_id": file_id}]
        return gen
    svc.add_instruction_media = AsyncMock(side_effect=add)
    return svc, gen


async def test_photo_and_pdf_are_attached_largest_photo_size(service):
    svc, gen = service
    state = await media_state()
    small, big = SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")

    await admin.admin_generator_media_input(message(photo=[small, big]), state, svc)
    pdf = SimpleNamespace(file_id="manual", mime_type="application/pdf")
    await admin.admin_generator_media_input(message(document=pdf), state, svc)

    assert gen.instructions_media == [{"type": "photo", "file_id": "big"}, {"type": "document", "file_id": "manual"}]
    assert await state.get_state() == AdminStates.waiting_for_gen_media.state  # admin can keep adding


async def test_other_files_and_text_are_rejected(service):
    svc, gen = service
    state = await media_state()
    zip_file = SimpleNamespace(file_id="z", mime_type="application/zip")

    await admin.admin_generator_media_input(message(document=zip_file), state, svc)
    await admin.admin_generator_media_input(message(text="привіт"), state, svc)

    svc.add_instruction_media.assert_not_called()


async def test_limit_of_ten_attachments(service):
    svc, gen = service
    gen.instructions_media = [{"type": "photo", "file_id": str(i)} for i in range(admin.SOS_MEDIA_MAX)]
    msg = message(photo=[SimpleNamespace(file_id="one-more")])

    await admin.admin_generator_media_input(msg, await media_state(), svc)

    svc.add_instruction_media.assert_not_called()
    assert "більше не можна" in msg.answer.call_args.args[0]


async def test_menu_button_cancels_media_step(service):
    svc, _ = service
    state = await media_state()
    await admin.admin_generator_media_input(message(text="⚡ Статус"), state, svc)
    assert await state.get_state() is None


async def test_sos_sends_single_files_alone_and_several_as_albums():
    msg = MagicMock()
    msg.answer_photo, msg.answer_document, msg.answer_media_group = AsyncMock(), AsyncMock(), AsyncMock()

    await common.send_instruction_media(msg, [{"type": "photo", "file_id": "p1"}, {"type": "document", "file_id": "d1"}])
    msg.answer_photo.assert_awaited_once_with("p1")
    msg.answer_document.assert_awaited_once_with("d1")

    msg.answer_media_group.reset_mock()
    await common.send_instruction_media(msg, [{"type": "photo", "file_id": "p1"}, {"type": "photo", "file_id": "p2"},
                                              {"type": "document", "file_id": "d1"}, {"type": "document", "file_id": "d2"}])
    albums = [call.args[0] for call in msg.answer_media_group.await_args_list]
    assert [type(m) for m in albums[0]] == [InputMediaPhoto, InputMediaPhoto]
    assert [type(m) for m in albums[1]] == [InputMediaDocument, InputMediaDocument]


async def test_service_replaces_the_json_list_so_the_change_is_saved():
    gen = SimpleNamespace(name="WILSON", instructions_media=[{"type": "photo", "file_id": "a"}])
    before = gen.instructions_media
    repo = MagicMock(get_by_id=AsyncMock(return_value=gen))
    svc = GeneratorService(repo, MagicMock(log_action=AsyncMock()), MagicMock(), MagicMock())

    await svc.add_instruction_media(1, 2, "document", "b")
    assert gen.instructions_media is not before and len(gen.instructions_media) == 2

    await svc.clear_instruction_media(1, 2)
    assert gen.instructions_media is None
