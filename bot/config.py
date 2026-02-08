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
    LOG_FORMAT: str = "console"
    
    # Timezone
    TIMEZONE: str = "Europe/Kiev"
    
    # Security
    SECRET_KEY: SecretStr
    
    # Weather
    WEATHER_API_KEY: SecretStr
    CITY_LAT: float
    CITY_LON: float
    
    # Google Sheets
    GOOGLE_CREDENTIALS_PATH: str = "./credentials/google-sheets-key.json"
    SCHEDULE_SPREADSHEET_ID: str = ""
    SCHEDULE_SHEET_NAME: str = "Графік"
    
    # Energy Schedule Parser
    HOE_SCHEDULE_URL: str = "https://hoe.com.ua/page/pogodinni-vidkljuchennja"
    QUEUE_NUMBER: str = "1.1"  # Which queue to monitor
    
    # Slack
    SLACK_WEBHOOK_URL: SecretStr | None = None
    FUEL_THRESHOLD_CANS: float = 2.0
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

config = Settings()
