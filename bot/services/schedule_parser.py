import hashlib
import json
import logging
import re
import ssl
from datetime import date, datetime, time, timedelta
from typing import Optional

import aiohttp
import certifi
from redis.asyncio import Redis

from bot.config import config
from bot.services.schedule_recognizer import ScheduleRecognitionError, ScheduleRecognizer
from bot.utils.clock import now_kyiv

HOE_BASE_URL = "https://hoe.com.ua"
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)

MANUAL_HOURS_KEY = "schedule:manual:{queue}:{day}"
RECOGNIZED_HOURS_KEY = "schedule:ai:{digest}:{queue}"
SCHEDULE_CACHE_TTL = timedelta(days=3)

NO_OUTAGE_WORDS = {"0", "-", "немає", "нема", "ні", "none"}


def parse_hours_input(text: str) -> list[int]:
    """Parses admin input like "14-18, 22-24" or "9" into outage hours.

    Ranges are end-exclusive ("14-18" -> 14, 15, 16, 17). NO_OUTAGE_WORDS -> [].
    Raises ValueError on anything else.
    """
    text = text.strip().lower().replace("–", "-").replace("—", "-")
    if text in NO_OUTAGE_WORDS:
        return []

    text = re.sub(r"\s*-\s*", "-", text)
    hours: set[int] = set()
    for part in re.split(r"[,;\s]+", text):
        if not part:
            continue
        match = re.fullmatch(r"(\d{1,2})(?::00)?(?:-(\d{1,2})(?::00)?)?", part)
        if not match:
            raise ValueError(part)
        start = int(match[1])
        end = int(match[2]) if match[2] else start + 1
        if not 0 <= start < end <= 24:
            raise ValueError(part)
        hours.update(range(start, end))

    if not hours:
        raise ValueError(text)
    return sorted(hours)


def format_hours(hours: list[int]) -> str:
    """[14, 15, 16, 22] -> "14:00–17:00, 22:00–23:00"."""
    if not hours:
        return "відключень немає"

    blocks: list[list[int]] = []
    for hour in sorted(hours):
        if blocks and hour == blocks[-1][1]:
            blocks[-1][1] = hour + 1
        else:
            blocks.append([hour, hour + 1])
    return ", ".join(f"{start:02d}:00–{end:02d}:00" for start, end in blocks)


class ScheduleParser:
    """Outage schedule for today and tomorrow.

    Manual hours entered by an admin win; otherwise the image from hoe.com.ua is read by Claude.
    Recognized hours are cached in Redis by image hash, so a 15-minute check does not call the API again.
    """

    def __init__(self, recognizer: ScheduleRecognizer, redis: Redis):
        self.recognizer = recognizer
        self.redis = redis

    async def get_manual_hours(self, day: date, queue: str) -> Optional[list[int]]:
        raw = await self.redis.get(MANUAL_HOURS_KEY.format(queue=queue, day=day.isoformat()))
        return json.loads(raw) if raw is not None else None

    async def set_manual_hours(self, day: date, queue: str, hours: list[int]) -> None:
        key = MANUAL_HOURS_KEY.format(queue=queue, day=day.isoformat())
        await self.redis.set(key, json.dumps(hours), ex=SCHEDULE_CACHE_TTL)

    async def clear_manual_hours(self, day: date, queue: str) -> None:
        await self.redis.delete(MANUAL_HOURS_KEY.format(queue=queue, day=day.isoformat()))

    async def _fetch_available_schedules(self) -> list[tuple[date, bytes]]:
        """Scrape site to find and download schedules for today and tomorrow"""
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)

            schedules = []
            async with aiohttp.ClientSession(connector=connector, timeout=HTTP_TIMEOUT) as session:
                async with session.get(config.HOE_SCHEDULE_URL) as response:
                    if response.status != 200:
                        logging.error(f"Failed to load HOE page: {response.status}")
                        return []
                    html = await response.text()

                img_tags = re.findall(r'<img[^>]+>', html)

                today = now_kyiv()
                tomorrow = today + timedelta(days=1)
                dates_to_check = [
                    (day.date(), [day.strftime("%Y%m%d"), day.strftime("%d.%m.%y"), day.strftime("%d.%m.%Y")])
                    for day in (today, tomorrow)
                ]

                found_dates = set()
                for img_tag in img_tags:
                    src_match = re.search(r'src="(/Content/Uploads/[^"]+\.png)"', img_tag)
                    if not src_match:
                        continue

                    url = src_match.group(1)
                    alt_match = re.search(r'alt="([^"]+)"', img_tag)
                    alt_text = alt_match.group(1) if alt_match else ""
                    search_blob = f"{url} {alt_text}".lower()

                    for d_obj, formats in dates_to_check:
                        if d_obj in found_dates:
                            continue

                        if any(f in search_blob for f in formats):
                            full_url = f"{HOE_BASE_URL}{url}"
                            async with session.get(full_url) as img_resp:
                                if img_resp.status == 200:
                                    schedules.append((d_obj, await img_resp.read()))
                                    found_dates.add(d_obj)
                                    logging.info(f"Fetched schedule for {d_obj}: {full_url}")

                # Nothing dated for today/tomorrow: the first uploaded image is most likely the current one
                if not schedules:
                    first_img = re.search(r'src="(/Content/Uploads/[^"]+\.png)"', html)
                    if first_img:
                        full_url = f"{HOE_BASE_URL}{first_img.group(1)}"
                        async with session.get(full_url) as img_resp:
                            if img_resp.status == 200:
                                logging.info(f"Fallback: Fetching first available image {full_url}")
                                schedules.append((today.date(), await img_resp.read()))

            return schedules
        except Exception:
            logging.exception("Error fetching schedules")
            return []

    async def _recognize_cached(self, image_bytes: bytes, queue: str) -> list[int]:
        key = RECOGNIZED_HOURS_KEY.format(digest=hashlib.sha256(image_bytes).hexdigest(), queue=queue)
        cached = await self.redis.get(key)
        if cached is not None:
            return json.loads(cached)

        try:
            hours = await self.recognizer.recognize(image_bytes, queue)
        except ScheduleRecognitionError:
            logging.exception("Schedule recognition failed, admin can enter hours manually")
            return []

        await self.redis.set(key, json.dumps(hours), ex=SCHEDULE_CACHE_TTL)
        logging.info(f"Recognized outage hours for queue {queue}: {hours}")
        return hours

    async def get_hours_by_date(self, queue: str) -> dict[date, list[int]]:
        """Outage hours for today and tomorrow; a date is missing when nothing is known for it."""
        today = now_kyiv().date()
        hours_by_date: dict[date, list[int]] = {}
        for day in (today, today + timedelta(days=1)):
            manual = await self.get_manual_hours(day, queue)
            if manual is not None:
                hours_by_date[day] = manual

        if len(hours_by_date) < 2:
            for day, image_bytes in await self._fetch_available_schedules():
                if day not in hours_by_date:
                    hours_by_date[day] = await self._recognize_cached(image_bytes, queue)

        return hours_by_date

    async def get_outage_timeline(self, queue: str) -> list[datetime]:
        """Datetimes (on the hour) of scheduled outages, merged from today and tomorrow."""
        hours_by_date = await self.get_hours_by_date(queue)
        timeline = {
            datetime.combine(day, time(hour, 0))
            for day, hours in hours_by_date.items()
            for hour in hours
        }
        return sorted(timeline)

    async def fetch_latest_schedule_image(self) -> Optional[bytes]:
        schedules = await self._fetch_available_schedules()
        if not schedules:
            return None
        today = now_kyiv().date()
        for day, image_bytes in schedules:
            if day == today:
                return image_bytes
        return schedules[0][1]
