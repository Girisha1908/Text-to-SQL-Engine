"""Settings for the Ask Your Data feature.

Kept separate from the shared `app.core.config` so this feature adds env vars
without changing the shared contract.
"""

from datetime import date
from functools import lru_cache
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import settings as core_settings


class AskSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    ASK_DATABASE_URL: Optional[str] = None  # falls back to the shared DATABASE_URL
    ASK_DB_SCHEMA: str = "ask_demo"
    ASK_AS_OF_DATE: Optional[date] = None  # "today" for relative dates; None = real today
    ASK_MAX_ROWS: int = 200
    ASK_STATEMENT_TIMEOUT_MS: int = 5000

    ASK_LLM_PROVIDER: Literal["offline", "groq", "gemini"] = "offline"
    ASK_LLM_MODEL: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

    @property
    def database_url(self) -> str:
        return self.ASK_DATABASE_URL or core_settings.DATABASE_URL

    @property
    def as_of(self) -> date:
        return self.ASK_AS_OF_DATE or date.today()


@lru_cache
def get_ask_settings() -> AskSettings:
    return AskSettings()
