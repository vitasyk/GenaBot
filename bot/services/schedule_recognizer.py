import base64

import anthropic
from pydantic import BaseModel, Field

from bot.config import config

RECOGNITION_PROMPT = """This image is an hourly power outage schedule table from hoe.com.ua (Khmelnytskyi oblast, Ukraine).
Rows are outage queues (for example 1.1, 1.2, 2.1, ...). Columns are the hours of the day from 00 to 24.
Coloured (shaded) cells mean the power is OFF in that time slot; white cells mean the power is on.
A cell can be split into two halves of 30 minutes each.

Find the row for queue {queue}.
- queue_found: true only if that row is clearly present in the table.
- outage_hours: every hour H from 0 to 23 where the power is off for any part of the interval H:00-(H+1):00 in that row.
  Return an empty list if the row has no shaded cells."""


class RecognizedSchedule(BaseModel):
    queue_found: bool = Field(description="Whether the row for the requested queue is present in the table")
    outage_hours: list[int] = Field(description="Hours 0-23 with a power outage for the requested queue")


class ScheduleRecognitionError(Exception):
    """The schedule image could not be read (no API key, API failure, refusal, or queue row not found)."""


class ScheduleRecognizer:
    """Reads outage hours for one queue from a schedule image with Claude vision + structured output."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None):
        self._client = client

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            if not config.ANTHROPIC_API_KEY:
                raise ScheduleRecognitionError("ANTHROPIC_API_KEY не задано в .env")
            self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY.get_secret_value(), timeout=120.0)
        return self._client

    async def recognize(self, image_bytes: bytes, queue: str) -> list[int]:
        media_type = "image/png" if image_bytes.startswith(b"\x89PNG") else "image/jpeg"
        try:
            response = await self._get_client().messages.parse(
                model=config.SCHEDULE_AI_MODEL,
                max_tokens=16000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                            },
                        },
                        {"type": "text", "text": RECOGNITION_PROMPT.format(queue=queue)},
                    ],
                }],
                output_format=RecognizedSchedule,
            )
        except anthropic.APIStatusError as e:
            raise ScheduleRecognitionError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise ScheduleRecognitionError("Claude API недоступний") from e

        result = response.parsed_output
        if response.stop_reason != "end_turn" or result is None:
            raise ScheduleRecognitionError(f"Unexpected stop_reason={response.stop_reason} (request {response._request_id})")
        if not result.queue_found:
            raise ScheduleRecognitionError(f"Черги {queue} не знайдено на зображенні")

        return sorted({hour for hour in result.outage_hours if 0 <= hour < 24})
