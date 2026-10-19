import logging
import os
import re
import ssl
from datetime import date, datetime, time, timedelta

import aiohttp
import certifi

from bot.config import config
from bot.utils.clock import now_local

logger = logging.getLogger(__name__)

HOE_BASE_URL = "https://hoe.com.ua"


class ScheduleParser:
    """Downloads power outage schedule images from HOE.com.ua (recognition: ScheduleRecognizer)"""

    CACHE_DIR = "data/cache"

    def __init__(self):
        os.makedirs(self.CACHE_DIR, exist_ok=True)

    def _get_cache_path(self, day: date) -> str:
        """Cache file of the schedule for `day`: an image is never shown for another date.

        shortcut: one ~300 KB file per day, never pruned; fine while data/ is not a volume
        (each deploy starts empty), prune old files if data/cache ever becomes persistent.
        """
        return f"{self.CACHE_DIR}/schedule_{day.isoformat()}.png"

    def _save_to_cache(self, image_bytes: bytes, day: date):
        """Save the schedule image for `day` to the local cache"""
        try:
            path = self._get_cache_path(day)
            with open(path, "wb") as f:
                f.write(image_bytes)
            logger.info(f"Schedule image saved to cache ({day}): {path}")
        except OSError:
            logger.exception("Failed to save schedule to cache")

    def get_cached_schedule(self, day: date) -> bytes | None:
        """Last downloaded schedule image for `day`, if any"""
        path = self._get_cache_path(day)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except OSError:
                logger.exception(f"Failed to read schedule from cache ({day})")
        return None

    async def get_schedules_data(self) -> list[tuple[datetime, bytes]]:
        """Scrape the site and download schedule images for today and tomorrow: [(date, image_bytes)]"""
        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            timeout = aiohttp.ClientTimeout(total=20, connect=10)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.get(config.HOE_SCHEDULE_URL) as response:
                    if response.status != 200:
                        logger.error(f"Failed to load HOE page: {response.status}")
                        return []
                    html = await response.text()

                today = now_local().date()
                tomorrow = today + timedelta(days=1)
                # Filenames/alt texts contain dates like 20260205 or 05.02.26
                dates_to_find = {
                    d: [d.strftime("%Y%m%d"), d.strftime("%d.%m.%y"), d.strftime("%d.%m.%Y")]
                    for d in (today, tomorrow)
                }
                found: dict[date, bytes] = {}

                async def download(url: str, day: date) -> None:
                    async with session.get(f"{HOE_BASE_URL}{url}") as img_resp:
                        if img_resp.status == 200:
                            found[day] = await img_resp.read()
                            self._save_to_cache(found[day], day)
                            logger.info(f"Fetched schedule for {day}: {url}")

                for img_tag in re.findall(r'<img[^>]+>', html):
                    src_match = re.search(r'src="(/Content/Uploads/[^"]+\.png)"', img_tag)
                    if not src_match:
                        continue
                    url = src_match.group(1)
                    alt_match = re.search(r'alt="([^"]+)"', img_tag)
                    # Alt text first: the filename often holds the upload date, not the schedule date
                    for text in (alt_match.group(1).lower() if alt_match else "", url.lower()):
                        day = next((d for d, formats in dates_to_find.items()
                                    if d not in found and any(f in text for f in formats)), None)
                        if day:
                            await download(url, day)
                            break

                # Nothing dated for today/tomorrow: the first uploaded image is most likely the current one
                if not found:
                    first_img = re.search(r'src="(/Content/Uploads/[^"]+\.png)"', html)
                    if first_img:
                        logger.info(f"Fallback: fetching first available image {first_img.group(1)}")
                        await download(first_img.group(1), today)

            return [(datetime.combine(d, time.min), b) for d, b in found.items()]
        except Exception:
            logger.exception("Error fetching schedules")
            return []
