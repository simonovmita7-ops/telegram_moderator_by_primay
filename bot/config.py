"""
Конфигурация бота.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
BOT_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    database_url: str
    log_level: str
    log_file: Path
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    sambanova_api_key: str | None = None
    sambanova_model: str = "Meta-Llama-3.3-70B-Instruct"
    ai_context_messages: int = 10
    ai_request_timeout: float = 60.0
    webapp_url: str = ""
    subscription_channel: str | None = None
    status_channel_id: str | None = None
    status_message_id: int | None = None
    bot_version: str = "Beta 1.3"


def _require(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value.strip() == "":
        raise ValueError(f"Переменная окружения {name} не задана.")
    return value.strip()


def load_settings() -> Settings:
    log_file = Path(os.getenv("LOG_FILE", str(BOT_DIR / "logs" / "bot.log")))
    log_file.parent.mkdir(parents=True, exist_ok=True)
    db_path = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BOT_DIR / 'data' / 'moderator.db'}")
    if db_path.startswith("sqlite"):
        db_file = db_path.split("///")[-1]
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    return Settings(
        telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        sambanova_api_key=os.getenv("SAMBANOVA_API_KEY", ""),
        sambanova_model=os.getenv("SAMBANOVA_MODEL", "Meta-Llama-3.1-405B-Instruct"),
        database_url=db_path,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        log_file=log_file,
        ai_context_messages=int(os.getenv("AI_CONTEXT_MESSAGES", "10")),
        ai_request_timeout=float(os.getenv("AI_REQUEST_TIMEOUT", "60")),
        webapp_url=os.getenv("WEBAPP_URL", ""),
        subscription_channel=os.getenv("SUBSCRIPTION_CHANNEL", "").strip() or None,
        status_channel_id=os.getenv("STATUS_CHANNEL_ID", "").strip() or None,
        status_message_id=int(os.getenv("STATUS_MESSAGE_ID", "").strip()) if os.getenv("STATUS_MESSAGE_ID", "").strip().isdigit() else None,
        bot_version=os.getenv("BOT_VERSION", "Beta 1.3").strip(),
    )
