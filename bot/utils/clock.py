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


def utc_to_local(dt: datetime) -> datetime:
    """Naive UTC (as stored in logs/generators) -> naive config.TIMEZONE time."""
    return dt.replace(tzinfo=UTC).astimezone(ZoneInfo(config.TIMEZONE)).replace(tzinfo=None)


def local_to_utc(dt: datetime) -> datetime:
    """Naive config.TIMEZONE time -> naive UTC for storing in logs/generators."""
    return dt.replace(tzinfo=ZoneInfo(config.TIMEZONE)).astimezone(UTC).replace(tzinfo=None)
