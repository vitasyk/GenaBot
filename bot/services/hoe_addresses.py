"""Addresses by outage queue from the HOE Excel lists (Khmelnytskyi REM, household + non-household)."""
import asyncio
import logging
import re
import ssl
import time
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import quote

import aiohttp
import certifi
import openpyxl

from bot.config import config
from bot.services.schedule_parser import HOE_BASE_URL

logger = logging.getLogger(__name__)

# Both files of Khmelnytskyi REM: "..._Хмельницький_РЕМ_побут_09102026.xlsx" and "..._непобут_..."
XLSX_LINK = re.compile(r'(/Content/Uploads/[^"]*Хмельницький_РЕМ[^"]*\.xlsx)')
CACHE_TTL_SECONDS = 6 * 3600
# HOE answers 403 to clients without a browser User-Agent
HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass(frozen=True)
class AddressRow:
    settlement: str
    street: str
    houses: list[str]
    queue: str  # "1.1"


class HoeAddressError(Exception):
    """HOE page or files could not be downloaded or read."""


def _house(value: object) -> str:
    # Single house numbers come as int, sometimes float (12.0)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def parse_workbook(data: bytes) -> list[AddressRow]:
    """Rows of the first sheet below the "Населений пункт" header."""
    ws = openpyxl.load_workbook(BytesIO(data), read_only=True).worksheets[0]
    rows: list[AddressRow] = []
    in_data = False
    for settlement, street, houses, queue in ws.iter_rows(min_col=1, max_col=4, values_only=True):
        if not in_data:
            in_data = settlement == "Населений пункт"
            continue
        if not settlement or not street or queue is None:
            continue
        houses_list = [h.strip() for h in str(houses).split(",")] if isinstance(houses, str) else [_house(houses)]
        rows.append(AddressRow(
            settlement=str(settlement).strip(),
            street=str(street).strip(),
            houses=[h for h in houses_list if h and h != "None"],
            queue=str(queue).split(" ")[0].rstrip("."),  # "1.1. підчерга" -> "1.1"
        ))
    return rows


def merge_rows(rows: list[AddressRow]) -> list[AddressRow]:
    """One row per (settlement, street, queue): household and non-household files repeat streets."""
    merged: dict[tuple[str, str, str], list[str]] = {}
    for r in rows:
        houses = merged.setdefault((r.settlement, r.street, r.queue), [])
        houses += [h for h in r.houses if h not in houses]
    return [AddressRow(s, st, h, q) for (s, st, q), h in merged.items()]


def split_house(query: str) -> tuple[list[str], str | None]:
    """Query words and the house number: the last word, if it has a digit and isn't the only word."""
    words = query.casefold().split()
    house = words.pop() if len(words) > 1 and any(c.isdigit() for c in words[-1]) else None
    return words, house


def find_by_address(rows: list[AddressRow], query: str) -> list[AddressRow]:
    """Rows whose "settlement street" contains every word of the query; with a house number,
    only rows listing that house."""
    words, house = split_house(query)
    found = [r for r in rows if all(w in f"{r.settlement} {r.street}".casefold() for w in words)]
    if house:
        found = [r for r in found if house in (h.casefold() for h in r.houses)]
    return found


def streets_for_queue(rows: list[AddressRow], queue: str, settlement: str = "") -> list[AddressRow]:
    """Rows of one queue, optionally only settlements whose name contains `settlement`."""
    needle = settlement.casefold()
    return [r for r in rows if r.queue == queue and needle in r.settlement.casefold()]


class HoeAddressService:
    """Downloads and caches the address lists; one instance per process."""

    def __init__(self) -> None:
        self._rows: list[AddressRow] = []
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def get_rows(self) -> list[AddressRow]:
        async with self._lock:  # one download even if several users ask at once
            if not self._rows or time.monotonic() - self._loaded_at > CACHE_TTL_SECONDS:
                self._rows = await self._download()
                self._loaded_at = time.monotonic()
            return self._rows

    async def _download(self) -> list[AddressRow]:
        connector = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where()))
        timeout = aiohttp.ClientTimeout(total=60, connect=10)
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout, headers=HEADERS) as session:
                async with session.get(config.HOE_SCHEDULE_URL) as resp:
                    resp.raise_for_status()
                    links = sorted(set(XLSX_LINK.findall(await resp.text())))
                if not links:
                    raise HoeAddressError("на сторінці HOE немає Excel-файлів Хмельницького РЕМ")
                rows: list[AddressRow] = []
                for link in links:
                    async with session.get(HOE_BASE_URL + quote(link)) as file_resp:
                        file_resp.raise_for_status()
                        data = await file_resp.read()
                    rows += await asyncio.to_thread(parse_workbook, data)
                    logger.info("HOE address list loaded: %s", link)
        except (aiohttp.ClientError, TimeoutError) as e:
            raise HoeAddressError(f"сайт HOE недоступний ({type(e).__name__})") from e
        if not rows:
            raise HoeAddressError("файли HOE порожні або змінили формат")
        return merge_rows(rows)
