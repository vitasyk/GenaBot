from io import BytesIO

import openpyxl

from bot.services.hoe_addresses import (
    AddressRow,
    find_by_address,
    merge_rows,
    parse_workbook,
    streets_for_queue,
)


def _xlsx(rows: list[tuple]) -> bytes:
    """Workbook shaped like the HOE file: title, blank row, header, data."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(("Хмельницький РЕМ (побутові споживачі)", None, None, None))
    ws.append((None, None, None, None))
    ws.append(("Населений пункт", "Вулиця", "Список будинків", "Черга/підчерга"))
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


ROWS = [
    AddressRow("Хмельницький", "вул. Зарічанська", ["1", "10", "12А"], "1.1"),
    AddressRow("Хмельницький", "вул. Зарічанська", ["2", "14"], "4.2"),
    AddressRow("Хмельницький", "вул. Вінницька", ["1"], "1.1"),
    AddressRow("Антонівці", "вул. Центральна", ["10"], "1.1"),
]


def test_parse_workbook_reads_rows_and_normalizes_queue_and_houses():
    data = _xlsx([
        ("Антонівці", "вул. Польова", " 1, 10, 2а", "1.1. підчерга"),
        ("Андрійківці", "вул. Центральна", 267, "4.2. підчерга"),  # single house comes as a number
        ("Водички", "вул. Лесі Українки", 12.0, "6.1. підчерга"),
    ])

    rows = parse_workbook(data)

    assert rows == [
        AddressRow("Антонівці", "вул. Польова", ["1", "10", "2а"], "1.1"),
        AddressRow("Андрійківці", "вул. Центральна", ["267"], "4.2"),
        AddressRow("Водички", "вул. Лесі Українки", ["12"], "6.1"),
    ]


def test_find_by_address_with_house_picks_the_right_queue():
    found = find_by_address(ROWS, "зарічанська 14")
    assert [r.queue for r in found] == ["4.2"]

    # House letters are matched case-insensitively
    assert [r.queue for r in find_by_address(ROWS, "Хмельницький Зарічанська 12а")] == ["1.1"]


def test_find_by_address_without_house_returns_every_queue_of_the_street():
    assert {r.queue for r in find_by_address(ROWS, "Зарічанська")} == {"1.1", "4.2"}
    assert find_by_address(ROWS, "Неіснуюча") == []


def test_streets_for_queue_filters_by_settlement():
    assert {r.street for r in streets_for_queue(ROWS, "1.1")} == {
        "вул. Зарічанська", "вул. Вінницька", "вул. Центральна"}
    assert [r.settlement for r in streets_for_queue(ROWS, "1.1", "антонів")] == ["Антонівці"]


def test_merge_rows_joins_household_and_business_lists():
    merged = merge_rows([
        AddressRow("Хмельницький", "вул. Бандери", ["1", "22"], "1.1"),
        AddressRow("Хмельницький", "вул. Бандери", ["22", "40А"], "1.1"),
        AddressRow("Хмельницький", "вул. Бандери", ["5"], "2.1"),
    ])
    assert merged == [
        AddressRow("Хмельницький", "вул. Бандери", ["1", "22", "40А"], "1.1"),
        AddressRow("Хмельницький", "вул. Бандери", ["5"], "2.1"),
    ]


def _message(text: str):
    from unittest.mock import AsyncMock, MagicMock
    msg = MagicMock(text=text, answer=AsyncMock(), answer_document=AsyncMock())
    msg.answer.return_value = MagicMock(delete=AsyncMock())  # the "loading..." notice
    return msg


async def test_address_search_answers_queue_for_house(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from bot.handlers.schedule import addresses

    monkeypatch.setattr(addresses.addresses, "get_rows", AsyncMock(return_value=ROWS))
    msg = _message("Зарічанська 14")

    await addresses.address_search(msg, MagicMock(clear=AsyncMock()))

    reply = msg.answer.await_args_list[-1].args[0]
    assert "буд. 14 → черга 4.2" in reply and "1.1" not in reply


async def test_long_queue_list_is_paged_with_buttons(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from bot.handlers.schedule import addresses
    from bot.keyboards.schedule_kb import QueuePageCb

    many = [AddressRow("Хмельницький", f"вул. Довга {i}", [str(n) for n in range(30)], "1.1") for i in range(50)]
    monkeypatch.setattr(addresses.addresses, "get_rows", AsyncMock(return_value=many))
    msg = _message("1.1 Хмельницький")

    await addresses.queue_streets_list(msg, MagicMock(clear=AsyncMock()))

    call = msg.answer.await_args_list[-1]
    assert "стор. 1/" in call.args[0]
    assert "Довга 0" in call.args[0]
    buttons = [b.callback_data for b in call.kwargs["reply_markup"].inline_keyboard[0]]
    assert QueuePageCb(queue="1.1", place="Хмельницький", page=1).pack() in buttons

    # Next page edits the same message
    callback = MagicMock(answer=AsyncMock(), message=MagicMock(edit_text=AsyncMock()))
    await addresses.queue_streets_page(callback, QueuePageCb(queue="1.1", place="Хмельницький", page=1))
    page2 = callback.message.edit_text.await_args.args[0]
    assert "стор. 2/" in page2 and "Довга 0:" not in page2


def test_paginate_splits_on_line_boundaries():
    from bot.handlers.schedule.addresses import paginate

    pages = paginate(["a" * 40] * 10, limit=100)
    assert len(pages) == 5 and all(len(p) <= 100 for p in pages)
    assert "".join(p.replace("\n", "") for p in pages) == "a" * 400


async def test_queue_list_accepts_whole_queue_and_marks_subqueues(monkeypatch):
    from unittest.mock import AsyncMock, MagicMock

    from bot.handlers.schedule import addresses

    monkeypatch.setattr(addresses.addresses, "get_rows", AsyncMock(return_value=ROWS))
    msg = _message("4 Хмельницький")

    await addresses.queue_streets_list(msg, MagicMock(clear=AsyncMock()))

    reply = msg.answer.await_args_list[-1].args[0]
    assert "вул. Зарічанська [4.2]: 2, 14" in reply
