import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_url: str
    redis_url: str | None
    openai_api_key: str | None
    openai_model: str
    openai_enabled: bool
    openai_timeout_seconds: float


def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Missing required env var: '{key}'")
    return value


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


_openai_api_key = os.getenv("OPENAI_API_KEY")
_openai_enabled_default = bool(_openai_api_key)

settings = Settings(
    bot_token=_require("BOT_TOKEN"),
    database_url=_require("DATABASE_URL"),
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    openai_api_key=_openai_api_key,
    openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    openai_enabled=_parse_bool(os.getenv("OPENAI_ENABLED"), _openai_enabled_default),
    openai_timeout_seconds=float(os.getenv("OPENAI_TIMEOUT_SECONDS", "20")),
)
