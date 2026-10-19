import logging

import aiohttp
from pydantic import SecretStr

logger = logging.getLogger(__name__)


class SlackService:
    def __init__(self, webhook_url: SecretStr | None):
        self.webhook_url = webhook_url.get_secret_value() if webhook_url else None

    async def send_message(self, text: str):
        if not self.webhook_url:
            logger.warning("Slack notification skipped: SLACK_WEBHOOK_URL not configured.")
            return

        try:
            async with aiohttp.ClientSession() as session:
                payload = {"text": text}
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status != 200:
                        body = await response.text()
                        logger.error(f"Slack API error: {response.status} - {body}")
                    else:
                        logger.info("Slack notification sent successfully.")
        except Exception:
            logger.warning("Failed to send Slack notification", exc_info=True)
