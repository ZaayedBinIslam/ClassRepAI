"""Settings from environment variables (.env) plus a few fixed constants."""
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    TELEGRAM_BOT_TOKEN: str = ""
    GEMINI_API_KEY: str = ""
    GEMMA_MODEL: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./classrepai.db"
    PUBLIC_BASE_URL: str = ""
    APP_SECRET: str = ""

    @property
    def webhook_mode(self) -> bool:
        # A public URL means we are hosted and Telegram pushes updates to us.
        return bool(self.PUBLIC_BASE_URL)


settings = Settings()

# Fixed values (deliberately not env variables).
TZ = ZoneInfo("Asia/Dhaka")
MIN_VOTES = 3                      # a poll needs at least this many votes to decide anything
DEFAULT_POLL_MINUTES = 20
MAX_POLL_MINUTES = 120
TEACHER_DEADLINE_HOURS = 3         # or 30 min before the class, whichever comes first
HISTORY_KEEP = 50                  # chat messages kept per chat
HISTORY_DAYS = 3
HISTORY_IN_PROMPT = 30
MEMORY_IN_PROMPT = 30
DRAFT_HOURS = 24
