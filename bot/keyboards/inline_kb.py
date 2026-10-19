from collections.abc import Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.database.models import Generator, GenStatus

STALE_MENU_TEXT = "Меню застаріло, відкрийте його знову"


class GenCb(CallbackData, prefix="gen"):
    """Generator button: action (start, standby, refuel, correct, sos, toggle, antigel) + generator id."""
    action: str
    id: int


def status_icon(status: GenStatus) -> str:
    if status == GenStatus.running:
        return "🟢"
    if status == GenStatus.standby:
        return "🟡"
    return "🔴"


def get_generator_control_kb(gens: Sequence[Generator], exclude_correction: bool = False, exclude_stop_all: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text=f"🟢 Старт {g.name}", callback_data=GenCb(action="start", id=g.id).pack()),
            InlineKeyboardButton(text=f"🟡 Чергування {g.name}", callback_data=GenCb(action="standby", id=g.id).pack()),
        ]
        for g in gens
    ]

    bottom_row = []

    if not exclude_stop_all:
        bottom_row.append(InlineKeyboardButton(text="🛑 Зупинити всі", callback_data="stop_all_gens"))

    if not exclude_correction:
        bottom_row.append(InlineKeyboardButton(text="🔧 Корегування", callback_data="correct_fuel_menu"))

    if bottom_row:
        buttons.append(bottom_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_generator_pick_kb(
    gens: Sequence[Generator],
    action: str,
    footer: InlineKeyboardButton | None = None,
    with_status: bool = False,
) -> InlineKeyboardMarkup:
    """One button per generator (GenCb(action, id)), plus an optional footer button."""
    builder = InlineKeyboardBuilder()
    for g in gens:
        text = f"{status_icon(g.status)} {g.name}" if with_status else g.name
        builder.row(InlineKeyboardButton(text=text, callback_data=GenCb(action=action, id=g.id).pack()))
    if footer:
        builder.row(footer)
    return builder.as_markup()


def get_start_generator_kb(gens: Sequence[Generator]) -> InlineKeyboardMarkup:
    """'Generator started' buttons for the outage warning."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🟢 Генератор {g.name} запущено", callback_data=GenCb(action="start", id=g.id).pack())]
        for g in gens
    ])


def get_sos_kb(gens: Sequence[Generator]) -> InlineKeyboardMarkup:
    return get_generator_pick_kb(gens, "sos")
