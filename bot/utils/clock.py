from datetime import datetime
from zoneinfo import ZoneInfo

from bot.config import config


def now_local() -> datetime:
    """Wall-clock time in config.TIMEZONE as a naive datetime.

    The container clock is UTC, so a bare datetime.now() is not local time.
    """
    return datetime.now(ZoneInfo(config.TIMEZONE)).replace(tzinfo=None)
