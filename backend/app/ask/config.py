"""Settings, read from environment variables or a local .env file."""

from datetime import date
from functools import lru_cache
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class AskSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    DATABASE_URL: str = "postgresql+psycopg://askdata:askdata@localhost:5433/askdata"
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
        # Hosted Postgres (Neon, Supabase) hands out postgres:// URLs; SQLAlchemy needs the psycopg driver named.
        for prefix in ("postgres://", "postgresql://"):
            if self.DATABASE_URL.startswith(prefix):
                return "postgresql+psycopg://" + self.DATABASE_URL[len(prefix):]
        return self.DATABASE_URL

    @property
    def as_of(self) -> date:
        return self.ASK_AS_OF_DATE or date.today()


@lru_cache
def get_ask_settings() -> AskSettings:
    return AskSettings()
