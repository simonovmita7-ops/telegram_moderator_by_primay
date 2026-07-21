"""
Сервис логирования событий.
"""
from __future__ import annotations
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from bot.models import LogEntry, LogEventType


class LoggingService:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger(__name__)

    async def log(
        self,
        session: AsyncSession,
        event_type: LogEventType,
        message: str,
        group_id: int | None = None,
        actor_telegram_id: int | None = None,
        target_telegram_id: int | None = None,
        details: dict | None = None,
        logging_mode: str = "full",
    ) -> None:
        # Полное отключение логирования в базу данных и в консоль
        return
