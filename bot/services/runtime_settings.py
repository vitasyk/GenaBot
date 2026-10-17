import logging
import re

from redis.asyncio import Redis

from bot.config import config

RESTRICT_ACCESS_KEY = "config:restrict_access"
NOTIFY_WORKERS_KEY = "config:notify_workers"
SCHEDULE_INTERVAL_KEY = "config:schedule_interval"
QUEUE_NUMBER_KEY = "config:queue_number"

_FLAGS = {RESTRICT_ACCESS_KEY: "RESTRICT_ACCESS", NOTIFY_WORKERS_KEY: "NOTIFY_WORKERS"}

# HOE queues are "<queue>.<subqueue>", e.g. 1.1 ... 6.2
QUEUE_NUMBER_PATTERN = re.compile(r"\d{1,2}\.\d")


def normalize_queue(text: str) -> str | None:
    """"1,1 " -> "1.1"; None if the text is not a queue number."""
    queue = text.strip().replace(",", ".")
    return queue if QUEUE_NUMBER_PATTERN.fullmatch(queue) else None


async def save_flag(redis: Redis, key: str, value: bool) -> None:
    await redis.set(key, int(value))


async def save_queue(redis: Redis, queue: str) -> None:
    config.QUEUE_NUMBER = queue
    await redis.set(QUEUE_NUMBER_KEY, queue)


async def load_flags(redis: Redis) -> None:
    """Applies admin toggles saved in Redis on top of the .env defaults."""
    for key, attr in _FLAGS.items():
        raw = await redis.get(key)
        if raw is not None:
            setattr(config, attr, int(raw) == 1)
            logging.info(f"Restored {attr}={getattr(config, attr)} from Redis")

    raw_queue = await redis.get(QUEUE_NUMBER_KEY)
    if raw_queue is not None:
        config.QUEUE_NUMBER = raw_queue.decode()
        logging.info(f"Restored QUEUE_NUMBER={config.QUEUE_NUMBER} from Redis")
