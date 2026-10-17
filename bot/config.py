from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr

class Settings(BaseSettings):
    BOT_TOKEN: SecretStr
    ADMIN_IDS: list[int]
    ALLOWED_IDS: list[int] = []
    RESTRICT_ACCESS: bool = True
    NOTIFY_WORKERS: bool = False

    # Database
    DATABASE_URL: SecretStr

    # Redis
    REDIS_URL: SecretStr

    # Logging
    LOG_LEVEL: str = "INFO"

    # Weather
    WEATHER_API_KEY: SecretStr
    CITY_LAT: float
    CITY_LON: float

    # Google Sheets
    GOOGLE_CREDENTIALS_PATH: str = "./credentials/google-sheets-key.json"
    SCHEDULE_SPREADSHEET_ID: str = ""

    # Energy Schedule Parser
    HOE_SCHEDULE_URL: str = "https://hoe.com.ua/page/pogodinni-vidkljuchennja"
    QUEUE_NUMBER: str = "1.1"  # Which queue to monitor

    # Schedule image recognition (Claude)
    ANTHROPIC_API_KEY: SecretStr
    SCHEDULE_AI_MODEL: str = "claude-haiku-5-5"

    # extra="ignore": old .env files may still carry removed keys (SECRET_KEY, LOG_FORMAT, ...)
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

config = Settings()
