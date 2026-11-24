"""HOE text schedule: parsing the outage page and watching it for changes of the selected queue.

The page is a list of posts separated by <hr>, newest first:
- a base schedule: "... 25.11.2026 р. ... Години відсутності електроенергії: Підчерга 2.1 – 09:00-12:00; ..."
- an update: "... оновлено графік ... на 24 листопада ... Додаткові години ...: Підчерга 2.1 - 20:00-22:00."
"""
import html as html_lib
import json
import logging
import re
from datetime import date

from redis.asyncio import Redis

from bot.database.repositories.schedule import ScheduleRepository
from bot.services.notifier import NotifierService

logger = logging.getLogger(__name__)

# Last published hours per queue and day, so each change is announced once
SEEN_KEY = "hoe:seen:{queue}:{day}"
SEEN_TTL_SECONDS = 3 * 24 * 3600

_MONTHS = ("січня", "лютого", "березня", "квітня", "травня", "червня",
           "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")
_DAY_MONTH_RE = re.compile(r"на\s+(\d{1,2})\s+(" + "|".join(_MONTHS) + ")", re.IGNORECASE)
_FULL_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s*р")
_QUEUE_LINE_RE = re.compile(r"Підчерга\s+(\d{1,2}\.\d)\s*[–—-]\s*([^\n]+)")
_PERIOD_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[–—-]\s*(\d{1,2}):(\d{2})")


def hours_to_ranges(hours) -> list[tuple[int, int]]:
    """[15, 14, 22, 23, 3] -> [(3, 4), (14, 16), (22, 24)]"""
    hours = sorted(hours)
    ranges: list[tuple[int, int]] = []
    for h in hours:
        if ranges and ranges[-1][1] == h:
            ranges[-1] = (ranges[-1][0], h + 1)
        else:
            ranges.append((h, h + 1))
    return ranges


def format_ranges(ranges: list[tuple[int, int]]) -> str:
    if not ranges:
        return "• відключень немає"
    return "\n".join(f"• {s:02d}:00 - {e:02d}:00" for s, e in ranges)


def _section_date(text: str, today: date) -> date | None:
    """Target day of a post. "на 24 листопада" first: an update also carries its own timestamp date."""
    m = _DAY_MONTH_RE.search(text)
    if m:
        month = _MONTHS.index(m.group(2).lower()) + 1
        year = today.year + (1 if month < today.month - 6 else -1 if month > today.month + 6 else 0)
        return date(year, month, int(m.group(1)))
    m = _FULL_DATE_RE.search(text)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _period_hours(periods: str) -> set[int]:
    """'09:00-12:00; 22:00-00:00' -> {9, 10, 11, 22, 23}.

    shortcut: half-hours are widened to whole hours (schedule_entries stores hours);
    store minutes if HOE starts publishing non-hour boundaries regularly.
    """
    hours: set[int] = set()
    for h1, m1, h2, m2 in _PERIOD_RE.findall(periods):
        start = int(h1)
        end = int(h2) + (1 if int(m2) else 0)
        if end == 0 or end <= start:  # "22:00-00:00" ends at midnight
            end = 24
        hours.update(range(start, min(end, 24)))
    return hours


def parse_hoe_page(page_html: str, today: date) -> dict[date, dict[str, set[int]]]:
    """Outage hours per day and queue from the HOE page text.

    A base post sets the day's schedule; "Додаткові години" posts add hours on top of it.
    Posts are applied oldest first, so a newer base post replaces an older one.
    """
    text = re.sub(r"<br\s*/?>|</p>", "\n", page_html, flags=re.IGNORECASE)
    sections = re.split(r"<hr\s*/?>", text, flags=re.IGNORECASE)
    result: dict[date, dict[str, set[int]]] = {}
    for raw in reversed(sections):
        section = html_lib.unescape(re.sub(r"<[^>]+>", " ", raw))
        if "Укренерго" not in section or "Підчерга" not in section:
            continue
        day = _section_date(section, today)
        if day is None:
            logger.warning("HOE post without a recognizable date: %.120s", section.strip())
            continue
        queues = {q: _period_hours(p) for q, p in _QUEUE_LINE_RE.findall(section)}
        if "Додатков" in section:
            for q, hours in queues.items():
                result.setdefault(day, {}).setdefault(q, set()).update(hours)
        else:
            result[day] = queues
    return result


async def sync_queue_schedule(
    schedules: dict[date, dict[str, set[int]]],
    queue: str,
    today: date,
    redis: Redis,
    schedule_repo: ScheduleRepository,
    notifier: NotifierService,
) -> list[date]:
    """Save and announce days whose published hours for `queue` changed since the last check.

    Replaces that day's schedule_entries for the queue (HOE is the official source) and commits.
    Returns the changed days.
    """
    changed: list[date] = []
    for day in sorted(d for d in schedules if d >= today):
        hours = sorted(schedules[day].get(queue, set()))
        key = SEEN_KEY.format(queue=queue, day=day.isoformat())
        raw = await redis.get(key)
        previous = json.loads(raw) if raw is not None else None
        if previous == hours:
            continue

        await schedule_repo.clear_all_for_date(day, queue)
        for start, end in hours_to_ranges(hours):
            await schedule_repo.create_entry(day, queue, start, end)
        await schedule_repo.session.commit()
        changed.append(day)

        ranges = hours_to_ranges(hours)
        day_str = day.strftime("%d.%m")
        if previous is None:
            msg = f"📅 <b>Графік на {day_str}</b> (черга {html_lib.escape(queue)})\n\n{format_ranges(ranges)}"
        else:
            added = hours_to_ranges(set(hours) - set(previous))
            removed = hours_to_ranges(set(previous) - set(hours))
            msg = (f"🔄 <b>Графік на {day_str} змінено</b> (черга {html_lib.escape(queue)})\n\n"
                   f"Тепер:\n{format_ranges(ranges)}")
            if added:
                msg += f"\n\n➕ Додано:\n{format_ranges(added)}"
            if removed:
                msg += f"\n\n➖ Скасовано:\n{format_ranges(removed)}"
        logger.info("HOE schedule for queue %s on %s: %s -> %s", queue, day, previous, hours)
        # Marked as seen only once delivered: a Telegram outage must not swallow the announcement
        if await notifier.notify_all(msg):
            await redis.set(key, json.dumps(hours), ex=SEEN_TTL_SECONDS)
    return changed
