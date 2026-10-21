"""When a generator is due for maintenance: after N run hours or M months since the last service,
whichever comes first. Run hours come from Generator.total_hours_run, so manual corrections count too.
"""
import calendar
from dataclasses import dataclass
from datetime import date

from bot.utils.clock import utc_to_local

# "Soon" warning: this share of the hour interval left, or this many days
SOON_HOURS_SHARE = 0.1
SOON_DAYS = 14


@dataclass(frozen=True)
class MaintenanceStatus:
    hours_left: float
    due_date: date
    days_left: int
    level: str  # ok, soon, due


def add_months(d: date, months: int) -> date:
    """31 Jan + 1 month -> 28/29 Feb."""
    month_index = d.month - 1 + months
    year, month = d.year + month_index // 12, month_index % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def maintenance_status(gen, today: date) -> MaintenanceStatus | None:
    """None until an admin records the last service."""
    if gen.last_maintenance is None:
        return None
    since = max(0.0, (gen.total_hours_run or 0.0) - (gen.maint_hours_at or 0.0))
    hours_left = gen.maint_interval_hours - since
    due_date = add_months(utc_to_local(gen.last_maintenance).date(), gen.maint_interval_months)
    days_left = (due_date - today).days
    if hours_left <= 0 or days_left <= 0:
        level = "due"
    elif hours_left <= gen.maint_interval_hours * SOON_HOURS_SHARE or days_left <= SOON_DAYS:
        level = "soon"
    else:
        level = "ok"
    return MaintenanceStatus(hours_left, due_date, days_left, level)


def format_status(st: MaintenanceStatus | None) -> str:
    if st is None:
        return "🔧 <b>ТО:</b> не задано"
    hours = f"{max(st.hours_left, 0.0):.0f} год"
    until = st.due_date.strftime("%d.%m.%Y")
    if st.level == "due":
        reason = "вичерпано мотогодини" if st.hours_left <= 0 else f"минув термін ({until})"
        return f"🛑 <b>Потрібне ТО:</b> {reason}"
    icon = "⚠️ <b>ТО скоро:</b>" if st.level == "soon" else "🔧 <b>До ТО:</b>"
    return f"{icon} {hours} або до {until}"
