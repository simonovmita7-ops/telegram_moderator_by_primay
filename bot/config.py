"""
Конфигурация бота.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
BOT_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

AIProvider = Literal["gemini", "openai", "claude"]


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    database_url: str
    log_level: str
    log_file: Path
    ai_provider: AIProvider = "openai"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    claude_api_key: str | None = None
    claude_model: str = "claude-3-5-haiku-20241022"
    ai_context_messages: int = 10
    ai_request_timeout: float = 60.0
    webapp_url: str = ""
    subscription_channel: str | None = None


def _require(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value.strip() == "":
        raise ValueError(f"Переменная окружения {name} не задана.")
    return value.strip()


def load_settings() -> Settings:
    ai_provider_raw = os.getenv("AI_PROVIDER", "openai").lower()
    if ai_provider_raw not in ("gemini", "openai", "claude"):
        raise ValueError("AI_PROVIDER должен быть 'gemini', 'openai' или 'claude'")
    ai_provider: AIProvider = ai_provider_raw  # type: ignore
    log_file = Path(os.getenv("LOG_FILE", str(BOT_DIR / "logs" / "bot.log")))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    db_path = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BOT_DIR / 'data' / 'moderator.db'}")
    if db_path.startswith("sqlite"):
        db_file = db_path.split("///")[-1]
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        ai_provider=ai_provider,
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        claude_api_key=os.getenv("CLAUDE_API_KEY", ""),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022"),
        database_url=db_path,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=log_file,
        ai_context_messages=int(os.getenv("AI_CONTEXT_MESSAGES", "10")),
        ai_request_timeout=float(os.getenv("AI_REQUEST_TIMEOUT", "60")),
        webapp_url=os.getenv("WEBAPP_URL", ""),
        subscription_channel=os.getenv("SUBSCRIPTION_CHANNEL", "").strip() or None,
    )

