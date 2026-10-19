import logging

import aiohttp
from pydantic import SecretStr


class SlackService:
    def __init__(self, webhook_url: SecretStr | None):
        self.webhook_url = webhook_url.get_secret_value() if webhook_url else None

    async def send_message(self, text: str):
        if not self.webhook_url:
            logging.warning("Slack notification skipped: SLACK_WEBHOOK_URL not configured.")
            return

        try:
            async with aiohttp.ClientSession() as session:
                payload = {"text": text}
                async with session.post(self.webhook_url, json=payload) as response:
                    if response.status != 200:
                        body = await response.text()
                        logging.error(f"Slack API error: {response.status} - {body}")
                    else:
                        logging.info("Slack notification sent successfully.")
        except Exception:
            logging.warning("Failed to send Slack notification", exc_info=True)
