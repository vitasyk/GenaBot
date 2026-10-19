from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from bot.config import config


def now_local() -> datetime:
    """Wall-clock time in config.TIMEZONE as a naive datetime.

    The container clock is UTC, so a bare datetime.now() is not local time.
    """
    return datetime.now(ZoneInfo(config.TIMEZONE)).replace(tzinfo=None)


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (generators and logs store naive UTC).

    Replaces the deprecated datetime.utcnow().
    """
    return datetime.now(UTC).replace(tzinfo=None)
