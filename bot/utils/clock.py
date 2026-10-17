from datetime import datetime
from zoneinfo import ZoneInfo

KYIV_TZ = ZoneInfo("Europe/Kyiv")


def now_kyiv() -> datetime:
    """Current Kyiv wall-clock time as a naive datetime (DB columns are naive)."""
    return datetime.now(KYIV_TZ).replace(tzinfo=None)
